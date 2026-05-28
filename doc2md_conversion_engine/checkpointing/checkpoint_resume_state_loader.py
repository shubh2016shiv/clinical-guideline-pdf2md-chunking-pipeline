"""
checkpointing/checkpoint_resume_state_loader.py
===============================================
Decide, at startup, whether to resume a conversion and from exactly where.

What this is, in plain terms
----------------------------
When the pipeline starts on a document, it asks one question: "have I done any of
this before, and if so, how far did I really get?" This module answers it. It reads
the saved checkpoint (via the store) and then — crucially — *checks the answer
against what is actually on disk* before trusting it.

Why we don't just trust the checkpoint
--------------------------------------
A checkpoint is a pointer to results sitting in the job's ``output_dir``. Those
result folders could have been moved, partially deleted, or restored from a stale
backup since the checkpoint was written. So this loader walks the windows the
checkpoint claims are done and keeps only the leading run whose result folders are
genuinely present. If window 5's results are missing, windows 5-onward are
discarded and we resume from the end of window 4 — never from a window whose data
isn't there.

What it does NOT check, and why
-------------------------------
It verifies that each window's result folder *exists and is non-empty* — not that
every individual page file is present. It cannot, without hard-coding Stage 2's
page-file naming, which would couple this module to Stage 2's internals. It does not
need to: the orchestrator writes a window's data first and the checkpoint *after*,
so any window recorded in a loaded checkpoint had its pages fully written before the
record existed. Presence-on-disk is therefore the right and sufficient check here.

What it returns
---------------
A ``ResumePlan`` — a single, explicit object telling the orchestrator everything it
needs: the reconciled checkpoint state, whether this is a resume or a fresh start,
the page to start from, and how many claimed windows had to be discarded.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from ..contracts import (
    AbstractCheckpointStore,
    CheckpointCorruptedError,
    CheckpointState,
    EngineClassification,
    WindowRecord,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResumePlan:
    """
    The startup decision for one document: resume from disk, or begin fresh.

    Fields
    ------
    state
        The ``CheckpointState`` to drive the run with. For a fresh start it is a new
        ``CheckpointState.fresh(...)``; for a resume it is the loaded state
        reconciled against on-disk reality (claimed-but-missing windows removed).
    is_resume
        ``True`` when prior, verified progress exists. Used for the "Resuming from
        page N" vs "Starting fresh" message and metrics.
    resume_from_page
        The 1-based page the orchestrator should process next (1 on a fresh start).
    discarded_windows
        How many windows the checkpoint claimed but whose results could not be found
        on disk. Normally 0; a positive value is worth logging as a warning.
    """

    state: CheckpointState
    is_resume: bool
    resume_from_page: int
    discarded_windows: int


class CheckpointResumeStateLoader:
    """
    Resolve a document's ``ResumePlan`` at pipeline startup.

    Depends only on the abstract store and the job's ``output_dir`` (needed to
    resolve each ``WindowRecord``'s relative ``result_dir`` into an absolute path).
    The concrete store — file-based today, Redis later — is injected, so this loader
    is unaware of where checkpoints physically live::

        loader = CheckpointResumeStateLoader(store, job.output_dir)
        plan = await loader.resolve_resume_plan(job.job_id, classification)
    """

    def __init__(self, store: AbstractCheckpointStore, output_dir: Path) -> None:
        self._store = store
        self._output_dir = output_dir

    async def resolve_resume_plan(
        self,
        job_id: str,
        classification: EngineClassification,
    ) -> ResumePlan:
        """
        Load, validate, and reconcile prior progress into a single resume decision.

        Any condition that makes prior progress untrustworthy — no checkpoint, a
        corrupted file, or a job-id mismatch (a file mix-up) — resolves cleanly to a
        fresh start, discarding the unusable checkpoint so it cannot mislead a later
        run. Otherwise the checkpoint is reconciled against on-disk results and a
        resume plan is returned.
        """
        loaded_state = await self._load_or_discard_unusable(job_id)
        if loaded_state is None:
            return self._fresh_plan(job_id, classification)

        verified_windows = await asyncio.to_thread(
            self._leading_windows_present_on_disk, loaded_state.completed_windows
        )
        return self._reconcile(loaded_state, verified_windows)

    # ------------------------------------------------------------------
    # Loading / integrity
    # ------------------------------------------------------------------

    async def _load_or_discard_unusable(self, job_id: str) -> CheckpointState | None:
        """
        Return a usable loaded state, or ``None`` if there is nothing to resume from.

        Folds the three "cannot trust this" cases into one ``None`` result, deleting
        the offending checkpoint so the next run is not tripped by it again:
          * no checkpoint exists (first run),
          * the checkpoint is corrupted/unsupported, or
          * the checkpoint's ``job_id`` does not match the document being processed.
        """
        try:
            state = await self._store.load(job_id)
        except CheckpointCorruptedError:
            logger.warning(
                "Checkpoint for job %s is corrupted; discarding and starting fresh.",
                job_id,
            )
            await self._store.delete(job_id)
            return None

        if state is None:
            return None

        if state.job_id != job_id:
            logger.warning(
                "Checkpoint job_id mismatch (file holds %s, expected %s); "
                "discarding and starting fresh.",
                state.job_id,
                job_id,
            )
            await self._store.delete(job_id)
            return None

        return state

    # ------------------------------------------------------------------
    # On-disk validation
    # ------------------------------------------------------------------

    def _leading_windows_present_on_disk(
        self,
        completed_windows: list[WindowRecord],
    ) -> list[WindowRecord]:
        """
        Keep the longest leading run of windows whose results are present on disk.

        Walks oldest to newest and stops at the first window whose result folder is
        missing or empty. Stopping at the first gap (rather than skipping it) keeps
        the resume point on a *contiguous* range of completed pages — there must be
        no hole between page 1 and the page we resume from.
        """
        verified: list[WindowRecord] = []
        for window in completed_windows:
            if not self._window_results_present(window):
                break
            verified.append(window)
        return verified

    def _window_results_present(self, window: WindowRecord) -> bool:
        """Return whether a window's result folder exists on disk and is non-empty."""
        result_path = self._output_dir / window.result_dir
        return result_path.is_dir() and any(result_path.iterdir())

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def _reconcile(
        self,
        loaded_state: CheckpointState,
        verified_windows: list[WindowRecord],
    ) -> ResumePlan:
        """
        Build the resume plan from the loaded state and the verified window run.

        When every claimed window is present, the loaded state is used unchanged.
        When some were missing, a reconciled copy is produced whose
        ``completed_windows`` and ``last_completed_page`` reflect only what is truly
        on disk, so the run continues from the last verifiable page.
        """
        discarded = len(loaded_state.completed_windows) - len(verified_windows)

        if discarded == 0:
            reconciled_state = loaded_state
        else:
            last_verified_page = verified_windows[-1].end_page if verified_windows else 0
            reconciled_state = loaded_state.model_copy(
                update={
                    "completed_windows": verified_windows,
                    "last_completed_page": last_verified_page,
                }
            )
            logger.warning(
                "Discarded %d checkpoint window(s) for job %s whose results were "
                "not found on disk; resuming from page %d.",
                discarded,
                loaded_state.job_id,
                reconciled_state.last_completed_page + 1,
            )

        return ResumePlan(
            state=reconciled_state,
            is_resume=reconciled_state.last_completed_page > 0,
            resume_from_page=reconciled_state.last_completed_page + 1,
            discarded_windows=discarded,
        )

    @staticmethod
    def _fresh_plan(job_id: str, classification: EngineClassification) -> ResumePlan:
        """Build the plan for a document with no usable prior progress."""
        return ResumePlan(
            state=CheckpointState.fresh(job_id, classification),
            is_resume=False,
            resume_from_page=1,
            discarded_windows=0,
        )
