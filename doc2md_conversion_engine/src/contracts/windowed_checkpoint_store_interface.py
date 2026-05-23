"""
contracts/windowed_checkpoint_store_interface.py
=================================================
Interface and state model for the checkpoint persistence system.

What is checkpointing and why does it matter here?
--------------------------------------------------
Processing a 500-page clinical guideline takes several minutes of GPU time.
If the process is killed (power cut, OOM, Ctrl-C) we must be able to resume
from the last completed window rather than restarting from page 1.

The checkpoint stores:
  - Which pages have been fully extracted.
  - Which engine / backend was being used.
  - The circuit-breaker failure count so the resumed run does not reset it.

The interface here separates the *what* (state schema + abstract store) from
the *how* (file-based implementation in ``checkpointing/``).  This means the
file store can be swapped for a Redis or database store in future without
touching any stage code.

Jargon — windowed checkpoint: progress is saved at window granularity (every
N pages, configurable via ``checkpointing.checkpoint_interval_pages``) rather
than page-by-page.  This keeps I/O overhead low while still bounding how much
work can be lost to at most one window's worth of pages.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .pipeline_domain_types import (
    EngineClassification,
    ExtractionEngine,
    MinerUBackend,
)


# ---------------------------------------------------------------------------
# State model
# ---------------------------------------------------------------------------


class WindowRecord(BaseModel):
    """
    Metadata for a single extraction window that has been completed and
    whose results are safely on disk.
    """

    model_config = ConfigDict(frozen=True)

    window_index: int = Field(..., ge=0, description="0-based window sequence number.")

    start_page: int = Field(..., ge=1, description="First page (inclusive) of this window.")

    end_page: int = Field(..., ge=1, description="Last page (inclusive) of this window.")

    result_dir: str = Field(
        ...,
        description=(
            "Relative path (from the job output_dir) to the directory containing "
            "this window's extracted page markdown files and figure PNGs."
        ),
    )

    engine_used: ExtractionEngine
    backend_used: MinerUBackend | None = None

    completed_at: datetime = Field(default_factory=datetime.utcnow)


class EngineSnapshot(BaseModel):
    """
    A point-in-time snapshot of the engine state saved inside the checkpoint.

    On resume, the pipeline restores this snapshot so:
      - The circuit-breaker failure count is not reset to zero.
      - If the engine was switched to the fallback before the crash, the
        resumed run continues with the fallback rather than retrying primary.
    """

    model_config = ConfigDict(frozen=False)

    engine: ExtractionEngine
    backend: MinerUBackend | None = None

    failures_since_last_success: int = Field(
        default=0,
        ge=0,
        description=(
            "Consecutive failures recorded by the circuit breaker.  "
            "Restored on resume so failure history is not lost across restarts."
        ),
    )


class CheckpointState(BaseModel):
    """
    The full state persisted to disk after each completed window.

    Serialised to JSON by pydantic and written atomically (write-to-temp
    then rename) so a kill -9 mid-write never produces a partial file.

    Schema version
    --------------
    ``schema_version`` must be incremented whenever field names or types
    change in a backwards-incompatible way, so the ``CheckpointCorruptedError``
    recovery path can detect and discard stale checkpoints rather than
    silently loading wrong values.
    """

    model_config = ConfigDict(frozen=False)

    schema_version: int = Field(
        default=1,
        description="Increment when the checkpoint schema changes incompatibly.",
    )

    job_id: str = Field(
        ...,
        description="SHA-256 of the source document.  Validated on load to detect file mix-ups.",
    )

    last_completed_page: int = Field(
        default=0,
        ge=0,
        description=(
            "The highest page number that has been fully extracted and whose "
            "result is safely on disk.  0 means no pages have been completed yet."
        ),
    )

    engine_snapshot: EngineSnapshot = Field(
        ...,
        description="Engine state at the time this checkpoint was written.",
    )

    completed_windows: list[WindowRecord] = Field(
        default_factory=list,
        description="All windows that have been fully extracted, in order.",
    )

    header_tree_snapshot: dict = Field(
        default_factory=dict,
        description=(
            "Serialised heading hierarchy accumulated so far.  "
            "Restored in the assembler so cross-window heading continuity is "
            "maintained (e.g. an H2 started on page 8 is still in scope on "
            "page 9 after a resume)."
        ),
    )

    created_at: datetime = Field(default_factory=datetime.utcnow)

    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def next_window_index(self) -> int:
        """Index of the next window to process (0-based)."""
        return len(self.completed_windows)

    @classmethod
    def fresh(cls, job_id: str, classification: EngineClassification) -> CheckpointState:
        """
        Factory: create a brand-new checkpoint for a job that has no prior run.
        """
        return cls(
            job_id=job_id,
            engine_snapshot=EngineSnapshot(
                engine=classification.engine,
                backend=classification.backend,
            ),
        )


# ---------------------------------------------------------------------------
# Abstract store interface
# ---------------------------------------------------------------------------


class AbstractCheckpointStore(ABC):
    """
    Interface for persisting and retrieving ``CheckpointState``.

    The pipeline calls these methods via the interface so the concrete
    implementation (file store, Redis, etc.) is never imported directly by
    any stage.
    """

    @abstractmethod
    async def save(self, state: CheckpointState) -> None:
        """
        Atomically persist ``state`` to the backing store.

        Must be crash-safe: if the process is killed mid-write, the
        previously saved state must remain intact (write-to-temp + rename
        is the standard file-based approach).

        Parameters
        ----------
        state:
            The checkpoint state to persist.  ``updated_at`` should be
            refreshed by the implementation before writing.
        """

    @abstractmethod
    async def load(self, job_id: str) -> CheckpointState | None:
        """
        Load a previously saved checkpoint for the given job.

        Parameters
        ----------
        job_id:
            The SHA-256 document hash used as the checkpoint key.

        Returns
        -------
        CheckpointState
            The restored state if a valid checkpoint exists.
        None
            If no checkpoint exists for this job (first run).

        Raises
        ------
        CheckpointCorruptedError
            If a checkpoint file exists but cannot be deserialised.
        """

    @abstractmethod
    async def delete(self, job_id: str) -> None:
        """
        Remove the checkpoint for a completed or abandoned job.

        Called by the orchestrator when the pipeline finishes successfully
        so stale checkpoints do not accumulate on disk.

        Must be idempotent — deleting a non-existent checkpoint must not raise.
        """

    @abstractmethod
    async def exists(self, job_id: str) -> bool:
        """
        Return True if a checkpoint exists for the given job, False otherwise.

        Used at pipeline startup to decide whether to show "Resuming from
        page N" or "Starting fresh" in the progress display.
        """
