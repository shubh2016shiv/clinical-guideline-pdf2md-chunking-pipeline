"""
stage2_page_extraction/windowed_extraction/windowed_page_extraction_orchestrator.py
===================================================================================
Stage 2 · the entry point — drive the whole page-extraction loop.

This is the conductor. Everything else in Stage 2 is an instrument; this class plays
them in order to turn one document into a stream of extracted pages. It is the single
class the rest of the pipeline imports from Stage 2.

The loop, in one breath
------------------------
Work out where to resume from (the checkpoint, validated against disk), figure out
which windows are left, build the engine Stage 1 chose (wrapped so it falls back to
Docling on failure), then for each remaining window: take the GPU lease, convert the
window's pages, hand each finished page downstream, and once the window is done write
a checkpoint so a crash can resume from here. When the last window finishes, delete
the checkpoint — the run is complete.

What it guarantees
------------------
  * memory-bounded — only one window's pages are in flight at a time,
  * resumable      — a checkpoint after every window, validated on restart,
  * fault-tolerant — the engine degrades to Docling rather than failing the document,
  * GPU-safe       — one engine on the GPU at a time, via the window lease,
  * observable     — one audit event per completed page.

It yields ``PageResult`` objects as a stream, so Stage 3 (figures) and Stage 4
(assembly) can begin working on early pages while later windows are still converting.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from ...checkpointing import CheckpointResumeStateLoader, WindowedCheckpointFileStore
from ...contracts.configurations.pipeline_config import PipelineConfig
from ...contracts.exceptions import DocumentError
from ...contracts.pipeline_domain_types import (
    ConversionJob,
    EngineClassification,
    ExtractionEngine,
    PageResult,
)
from ...contracts.windowed_checkpoint_store_interface import CheckpointState, WindowRecord
from ...fault_tolerance import AsyncOperationTimeoutGuard
from ...gpu_resource_management import GPUVRAMUsageMonitor
from ...observability import PerPageConversionEventLogger
from ..conversion_engines import ConversionEngineFactory
from .gpu_window_scheduler import GpuWindowScheduler
from .page_window_planner import PageWindow, plan_remaining_windows
from .window_result_store import load_window_page_results, persist_page_result

logger = logging.getLogger(__name__)


class WindowedPageExtractionOrchestrator:
    """
    Run Stage 2 for one document: resume-aware, checkpointed, fault-tolerant.

    Constructed once per pipeline run with the full config; ``extract`` is called per
    document with the job and Stage 1's engine choice::

        orchestrator = WindowedPageExtractionOrchestrator(config)
        async for page_result in orchestrator.extract(job, classification):
            ...   # feed Stage 3 / Stage 4
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config
        self._engine_factory = ConversionEngineFactory(config)
        self._page_event_logger = PerPageConversionEventLogger()
        self._vram_monitor = GPUVRAMUsageMonitor(config.gpu)
        self._timeout_guard = AsyncOperationTimeoutGuard(config.fault_tolerance.timeouts)

    async def extract(
        self,
        job: ConversionJob,
        classification: EngineClassification,
    ) -> AsyncGenerator[PageResult, None]:
        """
        Convert ``job`` page by page, yielding each ``PageResult`` as it completes.

        Resumes from a validated checkpoint when one exists, processes only the
        remaining windows, checkpoints after each, and deletes the checkpoint on
        successful completion.
        """
        total_pages = self._require_total_pages(job)

        checkpoint_store = WindowedCheckpointFileStore(job.output_dir, self._config.checkpointing)
        resume_loader = CheckpointResumeStateLoader(checkpoint_store, job.output_dir)
        resume_plan = await resume_loader.resolve_resume_plan(job.job_id, classification)
        checkpoint_state = resume_plan.state

        if resume_plan.is_resume:
            logger.info(
                "stage2.resume job_id=%s from_page=%s discarded_windows=%s",
                job.job_id,
                resume_plan.resume_from_page,
                resume_plan.discarded_windows,
            )
            # Already-extracted windows are replayed from disk so every page still
            # reaches the downstream stages — without spending GPU time re-extracting.
            async for replayed_page in self._replay_completed_windows(job, checkpoint_state):
                yield replayed_page

        remaining_windows = plan_remaining_windows(
            total_pages=total_pages,
            window_size=self._config.windowed_extraction.window_size,
            last_completed_page=checkpoint_state.last_completed_page,
        )

        engine = self._engine_factory.build_engine(job, classification)
        scheduler = GpuWindowScheduler(
            self._config.gpu,
            self._vram_monitor,
            self._timeout_guard,
            component_name=f"stage2.engine.{classification.engine.value}",
        )

        async with engine:
            for window in remaining_windows:
                window_results: list[PageResult] = []
                window_output_dir = self._prepare_window_dir(job, window)

                async with scheduler.lease_for_window(window.index):
                    async for page_result in engine.convert_window(
                        window.page_numbers, str(job.document_path), str(window_output_dir)
                    ):
                        # Persist before streaming so a finished page is durable on disk
                        # the moment the consumer sees it.
                        persist_page_result(window_output_dir, page_result)
                        self._page_event_logger.log_page_completed(job, page_result)
                        window_results.append(page_result)
                        yield page_result

                await self._checkpoint_completed_window(
                    store=checkpoint_store,
                    state=checkpoint_state,
                    window=window,
                    window_output_dir=window_output_dir,
                    window_results=window_results,
                )

        await self._finalize(checkpoint_store, job.job_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_total_pages(job: ConversionJob) -> int:
        """Return the document's page count, or fail clearly if Stage 1 never set it."""
        if job.total_pages is None:
            raise DocumentError(
                "Stage 2 requires job.total_pages, but it was not set by Stage 1.",
                context={"job_id": job.job_id},
            )
        return job.total_pages

    async def _replay_completed_windows(
        self,
        job: ConversionJob,
        state: CheckpointState,
    ) -> AsyncGenerator[PageResult, None]:
        """
        Re-emit pages from windows finished in a previous run, read back from disk.

        On resume the downstream stages still need every page, but the completed ones
        must not be re-extracted (that is the GPU time the checkpoint exists to save).
        Each completed window's persisted ``PageResult`` files are loaded and yielded
        in order, ahead of the windows that remain.
        """
        for completed_window in state.completed_windows:
            window_output_dir = job.output_dir / completed_window.result_dir
            for page_result in load_window_page_results(window_output_dir):
                logger.debug(
                    "stage2.replay job_id=%s page=%s window=%s",
                    job.job_id,
                    page_result.page_number,
                    completed_window.window_index,
                )
                yield page_result

    def _prepare_window_dir(self, job: ConversionJob, window: PageWindow) -> Path:
        """Create and return this window's result directory under the job output dir."""
        window_output_dir = job.output_dir / f"window_{window.index:03d}"
        window_output_dir.mkdir(parents=True, exist_ok=True)
        return window_output_dir

    async def _checkpoint_completed_window(
        self,
        *,
        store: WindowedCheckpointFileStore,
        state: CheckpointState,
        window: PageWindow,
        window_output_dir: Path,
        window_results: list[PageResult],
    ) -> None:
        """
        Record a finished window in the checkpoint and persist it.

        The window's engine is taken from the pages it actually produced, so a window
        that degraded to the fallback is recorded as such. ``result_dir`` is stored
        relative to the job output dir, matching how the resume loader validates it.
        """
        if not self._config.checkpointing.enabled:
            return

        engine_used = (
            window_results[0].engine_used if window_results else state.engine_snapshot.engine
        )
        state.completed_windows.append(
            WindowRecord(
                window_index=window.index,
                start_page=window.start_page,
                end_page=window.end_page,
                result_dir=window_output_dir.name,
                engine_used=engine_used,
                backend_used=(
                    state.engine_snapshot.backend
                    if engine_used == ExtractionEngine.MINERU
                    else None
                ),
            )
        )
        state.last_completed_page = window.end_page
        await store.save(state)

    async def _finalize(self, store: WindowedCheckpointFileStore, job_id: str) -> None:
        """Delete the checkpoint once the whole document has been extracted."""
        if self._config.checkpointing.enabled:
            await store.delete(job_id)
