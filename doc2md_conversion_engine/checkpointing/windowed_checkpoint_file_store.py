"""
checkpointing/windowed_checkpoint_file_store.py
===============================================
Crash-safe persistence of conversion progress to a local file.

What this is, in plain terms
----------------------------
A long conversion (a 500-page guideline can take minutes of GPU time) writes its
progress to disk after every window so that a power cut, an out-of-memory kill, or
a Ctrl-C does not throw away the work already done. This module is the component
that writes and reads that progress file.

What it stores
--------------
Just the *bookkeeping* — a small ``CheckpointState`` JSON (a few kilobytes): which
windows are finished, which engine ran, how far we got. The heavy output (the page
Markdown and figure PNGs) is already on disk in the job's ``output_dir``; the
checkpoint only points at it. See ``CHECKPOINTING_DESIGN.md`` for the full rationale.

Where it stores it
------------------
One file per document, alongside that document's own results::

    <output_dir>/<checkpoint_dir>/<job_id>.json
    e.g.  doc_assets/<job_id>/output/.checkpoints/<job_id>.json

Keeping the checkpoint on the *same filesystem* as the results it describes is
deliberate: a single write-ordering discipline (flush the window's data, then write
the checkpoint) keeps the two from ever disagreeing after a crash.

How the write is made crash-safe
--------------------------------
Every save is atomic: the JSON is written to a temporary file, flushed all the way
to physical disk (``fsync``), and then *renamed* over the real file. Rename is an
atomic operation on POSIX filesystems, so a process killed mid-write leaves the
*previous* checkpoint fully intact — never a half-written one.

Why ``asyncio.to_thread``
-------------------------
The store satisfies an ``async`` interface because the orchestrator above it is
async and may be streaming pages while a checkpoint is written. File I/O is blocking,
so the actual disk work runs in a worker thread to avoid stalling the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from ..contracts import (
    AbstractCheckpointStore,
    CheckpointCorruptedError,
    CheckpointError,
    CheckpointingConfig,
    CheckpointState,
)

logger = logging.getLogger(__name__)

# The only checkpoint schema this store knows how to read. A checkpoint written by
# a future, incompatible version is treated as corrupt (discarded and restarted)
# rather than silently mis-read — see ``_deserialize_state``.
_SUPPORTED_SCHEMA_VERSION = 1


class WindowedCheckpointFileStore(AbstractCheckpointStore):
    """
    Persist ``CheckpointState`` as one crash-safe JSON file per job.

    Scoped to a single document's workspace. The pipeline processes one document
    at a time (see ``CHECKPOINTING_DESIGN.md`` §7), so the store is constructed with
    that document's ``output_dir`` and writes its checkpoint underneath it::

        store = WindowedCheckpointFileStore(job.output_dir, config.checkpointing)
        await store.save(state)

    ``job_id`` is still the file key, so the store remains correct even if the same
    instance is asked about more than one job.
    """

    def __init__(self, output_dir: Path, config: CheckpointingConfig) -> None:
        # The checkpoint directory lives inside the job's output workspace, so the
        # progress file and the results it describes share one filesystem.
        self._checkpoint_dir = output_dir / config.checkpoint_dir

    async def save(self, state: CheckpointState) -> None:
        """
        Atomically write ``state`` to disk, refreshing its ``updated_at`` stamp.

        The caller's object is not mutated — a copy carrying the new timestamp is
        serialized instead, so ``save`` has no surprising side effect on the state
        the orchestrator still holds.
        """
        state_to_persist = state.model_copy(update={"updated_at": datetime.utcnow()})
        payload = state_to_persist.model_dump_json(indent=2)
        checkpoint_path = self._checkpoint_path(state.job_id)
        try:
            await asyncio.to_thread(self._write_atomically, checkpoint_path, payload)
        except OSError as exc:
            raise CheckpointError(
                f"Failed to persist checkpoint for job {state.job_id}.",
                context={"job_id": state.job_id, "path": str(checkpoint_path)},
            ) from exc

    async def load(self, job_id: str) -> CheckpointState | None:
        """
        Read a previously saved checkpoint, or ``None`` when none exists yet.

        A missing file is the normal "first run" case and returns ``None``. A file
        that exists but cannot be parsed is genuine corruption and raises
        ``CheckpointCorruptedError`` so the caller can discard it and start fresh.
        """
        checkpoint_path = self._checkpoint_path(job_id)
        try:
            raw_json = await asyncio.to_thread(checkpoint_path.read_text, "utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CheckpointError(
                f"Failed to read checkpoint for job {job_id}.",
                context={"job_id": job_id, "path": str(checkpoint_path)},
            ) from exc
        return self._deserialize_state(raw_json, job_id, checkpoint_path)

    async def delete(self, job_id: str) -> None:
        """
        Remove a job's checkpoint; a no-op when it is already gone (idempotent).

        Called when a run finishes successfully so completed checkpoints do not
        accumulate.
        """
        checkpoint_path = self._checkpoint_path(job_id)
        try:
            await asyncio.to_thread(checkpoint_path.unlink, True)  # missing_ok=True
        except OSError as exc:
            raise CheckpointError(
                f"Failed to delete checkpoint for job {job_id}.",
                context={"job_id": job_id, "path": str(checkpoint_path)},
            ) from exc

    async def exists(self, job_id: str) -> bool:
        """Return whether a checkpoint file is present for this job."""
        checkpoint_path = self._checkpoint_path(job_id)
        return await asyncio.to_thread(checkpoint_path.is_file)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _checkpoint_path(self, job_id: str) -> Path:
        """Resolve the on-disk path of a job's checkpoint file."""
        return self._checkpoint_dir / f"{job_id}.json"

    def _deserialize_state(
        self,
        raw_json: str,
        job_id: str,
        checkpoint_path: Path,
    ) -> CheckpointState:
        """
        Parse checkpoint JSON into a validated ``CheckpointState``.

        Both a malformed/truncated file and a state from an incompatible schema
        version are surfaced as ``CheckpointCorruptedError`` — the contract's agreed
        signal that the safe recovery is to discard and restart, never to guess at
        unreadable progress.
        """
        try:
            state = CheckpointState.model_validate_json(raw_json)
        except ValidationError as exc:
            raise CheckpointCorruptedError(
                f"Checkpoint for job {job_id} exists but could not be deserialised.",
                context={"job_id": job_id, "path": str(checkpoint_path)},
            ) from exc

        if state.schema_version != _SUPPORTED_SCHEMA_VERSION:
            raise CheckpointCorruptedError(
                f"Checkpoint for job {job_id} has unsupported schema version "
                f"{state.schema_version} (this build reads version "
                f"{_SUPPORTED_SCHEMA_VERSION}).",
                context={
                    "job_id": job_id,
                    "path": str(checkpoint_path),
                    "found_schema_version": state.schema_version,
                    "supported_schema_version": _SUPPORTED_SCHEMA_VERSION,
                },
            )
        return state

    def _write_atomically(self, destination: Path, payload: str) -> None:
        """
        Write ``payload`` to ``destination`` so a crash never leaves a partial file.

        The sequence — write to a temp file in the *same* directory, fsync it,
        ``os.replace`` it over the destination, then fsync the directory — is the
        standard durable-atomic-write recipe. Same-directory temp guarantees the
        rename stays on one filesystem (cross-filesystem renames are not atomic).
        """
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

        temp_fd, temp_name = tempfile.mkstemp(
            dir=self._checkpoint_dir,
            prefix=f"{destination.stem}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as temp_file:
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())  # data durably on disk before the rename
            os.replace(temp_path, destination)  # atomic swap on the same filesystem
            self._fsync_directory(self._checkpoint_dir)  # persist the rename itself
        except BaseException:
            # Never leave a stray temp file behind on any failure (including the
            # event loop cancelling the worker thread).
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        """
        Flush a directory entry so a freshly renamed file survives power loss.

        Best-effort: a few filesystems (some network mounts) reject directory
        fsync. The ``os.replace`` above is still atomic in that case, so consistency
        is preserved even where this extra durability step is unavailable.
        """
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        except OSError:
            logger.debug("Directory fsync unsupported for %s; rename remains atomic", directory)
        finally:
            os.close(dir_fd)
