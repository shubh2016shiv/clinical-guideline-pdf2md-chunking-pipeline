"""
stage3_figure_summarization/figure_summarization_worker_pool.py
================================================================
The N-worker concurrent consumer of the figure queue.

Responsibilities (one place, one read):

1. Pull a :class:`Figure` from the bounded queue.
2. Skip if its token already has a persisted summary (resume short-circuit).
3. Consult the sha256 dedup cache; on hit, copy the summary under this
   figure's token and continue — no VLM call needed.
4. Otherwise, acquire the concurrency limiter, optionally acquire the
   GPU lock, call the vision client through the resilience stack
   (timeout + retry + circuit breaker), persist the summary under this
   figure's token and under its sha256.
5. Apply poison-pill behaviour: after ``figure_retries`` consecutive
   failures the worker writes a degraded placeholder summary so Stage 4
   can complete the document, and increments the failure counter.

Why a class and not a bare ``asyncio.gather`` of coroutines?
------------------------------------------------------------
The pool owns a small but real amount of state: per-worker tasks, a
counters object for metrics, a shutdown signal.  Encapsulating that in a
class gives a clean ``start`` / ``join`` lifecycle that the orchestrator
can drive, plus a single place to swap in alternative scheduling policies.

Resilience stack composition
----------------------------
Per VLM call the wrap order is::

    timeout_guard.custom(...)
        circuit_breaker.call_async(
            retry_policy.call_async(
                limiter.acquire():
                    [optional gpu lock]:
                        vision_client.summarize(...)
            )
        )

The outer-most layer is the timeout, so a stuck call cannot live forever
even if the circuit-breaker library has a bug.  The breaker is next-outer
so it sees timeouts as failures (which is what we want for trip
thresholds).  Retry is innermost-of-resilience so each attempt is bounded
by its own breaker state and timeout reset.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from ..contracts import (
    AbstractFigureDedupCache,
    AbstractFigureSummaryStore,
    AbstractFigureWorkQueue,
    AbstractVisionFigureClient,
    DocumentDomain,
    Figure,
    FigurePoisonPillError,
    FigureSummarizationError,
    FigureSummary,
    LegibilityLevel,
    RenderingStrategy,
)
from ..contracts.figure_summarization_types import FigureType
from ..fault_tolerance import (
    AsyncOperationTimeoutGuard,
    EngineCircuitBreaker,
    ExponentialBackoffRetry,
)
from ..gpu_resource_management import ExclusiveGPUContextManager
from .local_vision_concurrency_limiter import LocalVisionConcurrencyLimiter

logger = logging.getLogger(__name__)


# Exception classes that are worth retrying via ExponentialBackoffRetry.
# - FigureSummarizationError covers our own raised failures (validation
#   exhaustion, image preprocessing failures).
# - OSError covers transient socket / file-descriptor problems against the
#   local Ollama daemon.
# Cancellation is *not* listed — it must propagate immediately.
_TRANSPORT_RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    FigureSummarizationError,
    OSError,
)


# ---------------------------------------------------------------------------
# Counters surfaced to the orchestrator for ConversionSummary fields
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class FigureSummarizationCounters:
    """
    Counters Stage 3 surfaces to the orchestrator at the end of a job.

    Mirrors the three fields on :class:`ConversionSummary` so the
    orchestrator can copy them across without any further bookkeeping.
    """

    figures_summarized: int = 0
    figures_deduplicated: int = 0
    figures_failed: int = 0


# ---------------------------------------------------------------------------
# Worker pool
# ---------------------------------------------------------------------------


class FigureSummarizationWorkerPool:
    """
    A small fixed-size pool of async workers that summarise figures.

    The pool is single-use: instantiate, ``start()`` it, then ``join()``
    once Stage 2 has closed the queue.  ``join`` waits for every in-flight
    figure to finish and returns the final counters.
    """

    def __init__(
        self,
        *,
        queue: AbstractFigureWorkQueue,
        vision_client: AbstractVisionFigureClient,
        dedup_cache: AbstractFigureDedupCache,
        summary_store: AbstractFigureSummaryStore,
        concurrency_limiter: LocalVisionConcurrencyLimiter,
        retry_policy: ExponentialBackoffRetry,
        timeout_guard: AsyncOperationTimeoutGuard,
        circuit_breaker: EngineCircuitBreaker,
        gpu_context_factory: Callable[[], ExclusiveGPUContextManager] | None,
        worker_pool_size: int,
        figure_retries: int,
        degraded_placeholder_markdown: str,
        deduplication_enabled: bool,
    ) -> None:
        if worker_pool_size < 1:
            raise ValueError("worker_pool_size must be ≥ 1")
        if figure_retries < 1:
            raise ValueError("figure_retries must be ≥ 1")

        self._queue = queue
        self._vision_client = vision_client
        self._dedup_cache = dedup_cache
        self._summary_store = summary_store
        self._limiter = concurrency_limiter
        self._retry_policy = retry_policy
        self._timeout_guard = timeout_guard
        self._circuit_breaker = circuit_breaker
        self._gpu_context_factory = gpu_context_factory
        self._worker_pool_size = worker_pool_size
        self._figure_retries = figure_retries
        self._degraded_placeholder_markdown = degraded_placeholder_markdown
        self._deduplication_enabled = deduplication_enabled

        self._tasks: list[asyncio.Task[None]] = []
        self._counters = FigureSummarizationCounters()
        self._counters_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the worker tasks.  Idempotent: calling twice is a no-op."""
        if self._tasks:
            return
        for worker_index in range(self._worker_pool_size):
            task = asyncio.create_task(
                self._worker_loop(worker_index),
                name=f"stage3.figure_worker.{worker_index}",
            )
            self._tasks.append(task)
        logger.info(
            "stage3.worker_pool.started worker_count=%d", self._worker_pool_size
        )

    async def join(self) -> FigureSummarizationCounters:
        """
        Wait for all workers to finish processing then return final counters.

        Callers must have called :meth:`AbstractFigureWorkQueue.close`
        first; otherwise workers will hang on the queue forever.
        """
        if not self._tasks:
            return self._counters
        await asyncio.gather(*self._tasks)
        self._tasks.clear()
        logger.info(
            "stage3.worker_pool.joined summarized=%d deduplicated=%d failed=%d",
            self._counters.figures_summarized,
            self._counters.figures_deduplicated,
            self._counters.figures_failed,
        )
        return self._counters

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    async def _worker_loop(self, worker_index: int) -> None:
        logger.debug("stage3.worker.started index=%d", worker_index)
        while True:
            figure = await self._queue.get()
            if figure is None:
                # Producer closed; this worker's shutdown sentinel arrived.
                logger.debug("stage3.worker.exit index=%d", worker_index)
                return
            try:
                await self._process_one_figure(figure, worker_index=worker_index)
            except Exception as exc:  # noqa: BLE001 — last-resort safety net
                # Any uncaught exception here is a *bug*: per-figure
                # exceptions are meant to be poison-pilled into a degraded
                # placeholder.  We log loudly but keep the worker alive so
                # one bad figure cannot starve the rest of the document.
                logger.exception(
                    "stage3.worker.unhandled index=%d token=%s exc=%s",
                    worker_index, figure.token, type(exc).__name__,
                )
                await self._record_failed(figure)

    # ------------------------------------------------------------------
    # Per-figure pipeline
    # ------------------------------------------------------------------

    async def _process_one_figure(self, figure: Figure, *, worker_index: int) -> None:
        # 1. Resume short-circuit — token already done.
        if await self._summary_store.contains(figure.token):
            logger.debug(
                "stage3.worker.resume_skip token=%s worker=%d",
                figure.token, worker_index,
            )
            return

        # 2. SHA-256 dedup cache hit — copy across.
        if self._deduplication_enabled:
            cached = await self._dedup_cache.get(figure.sha256)
            if cached is not None:
                # Cached entry is keyed by content hash, so its ``token``
                # field refers to whichever figure was summarised first.
                # We must rewrite the token before persisting under *this*
                # figure's token.
                rebound = cached.model_copy(update={"token": figure.token})
                await self._summary_store.put(rebound)
                async with self._counters_lock:
                    self._counters.figures_deduplicated += 1
                logger.info(
                    "stage3.worker.dedup_hit token=%s sha256=%s worker=%d",
                    figure.token, figure.sha256[:12], worker_index,
                )
                return

        # 3. Live VLM call through the resilience stack.
        try:
            summary = await self._call_vision_with_resilience(figure)
        except FigurePoisonPillError:
            # Already counted; nothing else to do — the placeholder was
            # written inside ``_call_vision_with_resilience``.
            return

        await self._summary_store.put(summary)
        if self._deduplication_enabled:
            await self._dedup_cache.put(figure.sha256, summary)
        async with self._counters_lock:
            self._counters.figures_summarized += 1
        logger.info(
            "stage3.worker.summarized token=%s figure_type=%s confidence=%.2f worker=%d",
            figure.token, summary.figure_type.value, summary.confidence,
            worker_index,
        )

    async def _call_vision_with_resilience(self, figure: Figure) -> FigureSummary:
        """
        Run one VLM call wrapped in the full resilience stack.

        The retry policy decides how many attempts to make; on exhaustion
        we materialise a *degraded placeholder* (poison-pill) rather than
        propagate the exception, so Stage 4 can always complete the
        document.
        """

        async def invocation() -> FigureSummary:
            # Acquire the in-flight semaphore and (optionally) the GPU lock.
            # GPU lock is acquired here rather than at the orchestrator level
            # because the cost-of-holding is exactly one VLM call's duration.
            async with self._limiter.acquire():
                if self._gpu_context_factory is not None:
                    gpu_context = self._gpu_context_factory()
                    async with gpu_context:
                        return await self._vision_client.summarize(
                            image_path=figure.image_path,
                            token=figure.token,
                        )
                return await self._vision_client.summarize(
                    image_path=figure.image_path,
                    token=figure.token,
                )

        async def guarded_invocation() -> FigureSummary:
            # No outer ``llm_batch_call`` timeout here: that knob was
            # cloud-sized (60 s, batched API) and routinely fires on a
            # local 4B model that needs ~30 s per figure.  The Ollama
            # client owns its own ``request_timeout_seconds`` (default
            # 120 s) which is sized for local-VLM realities.  Keeping
            # only one timeout layer also avoids confusing
            # double-timeouts in logs.
            return await self._vision_client_call_through_breaker(invocation)

        try:
            # ONE retry layer — sized by ``figure_retries`` from the
            # Stage 3 config.  An earlier revision nested two retry layers
            # (an outer figure-retry loop wrapping stamina's own attempts),
            # which multiplied to 9 calls per figure and routinely
            # produced 4-5 minute per-figure failure cycles on a local VLM.
            # stamina is the single source of truth for retry count; the
            # per-figure budget is plumbed in via ``_build_stage3_retry_policy``.
            return await self._retry_policy.call_async(
                guarded_invocation,
                _TRANSPORT_RETRYABLE_EXCEPTIONS,
            )
        except FigureSummarizationError as exc:
            logger.error(
                "stage3.worker.poison_pill token=%s reason=%s",
                figure.token, type(exc).__name__,
            )
            await self._record_failed(figure)
            raise FigurePoisonPillError(
                f"Figure {figure.token!r} permanently failed after "
                f"{self._figure_retries} attempts.",
                context={
                    "token": figure.token,
                    "image_path": str(figure.image_path),
                    "sha256": figure.sha256,
                    "cause": str(exc),
                },
            ) from exc

    async def _vision_client_call_through_breaker(
        self,
        invocation: Callable[[], Coroutine[Any, Any, FigureSummary]],
    ) -> FigureSummary:
        return await self._circuit_breaker.call_async(invocation)

    # ------------------------------------------------------------------
    # Degraded placeholder
    # ------------------------------------------------------------------

    async def _record_failed(self, figure: Figure) -> None:
        """
        Materialise a degraded placeholder summary and persist it under the
        figure's token so Stage 4 can complete without blocking.

        Marked ``DECORATIVE`` + ``decorative_note`` so Stage 4's existing
        logic for non-informative figures handles the substitution, but the
        marker text is the explicit failure placeholder so a reviewer can
        spot it.
        """
        placeholder = FigureSummary(
            token=figure.token,
            figure_type=FigureType.DECORATIVE,
            rendering_strategy=RenderingStrategy.DECORATIVE_NOTE,
            is_informative=False,
            markdown_result=self._degraded_placeholder_markdown,
            legibility=LegibilityLevel.POOR,
            confidence=0.0,
            document_domain=DocumentDomain.CLINICAL,
        )
        await self._summary_store.put(placeholder)
        async with self._counters_lock:
            self._counters.figures_failed += 1
