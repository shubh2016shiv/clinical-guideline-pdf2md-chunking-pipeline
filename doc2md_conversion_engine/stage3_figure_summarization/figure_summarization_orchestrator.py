"""
stage3_figure_summarization/figure_summarization_orchestrator.py
=================================================================
The entry point for Stage 3 — figure summarization.

Composition root (the only place where concretes are wired together)
--------------------------------------------------------------------
The pipeline calls a single object: this orchestrator.  Everything below
(prompt builder, vision client, dedup cache, summary store, queue, worker
pool, concurrency limiter, GPU context, resilience primitives) is wired
here from configuration.  No other Stage 3 module depends on a concrete
class outside of contracts — this orchestrator is the only place
``OllamaVisionFigureClient``, ``JsonFigureSummaryStore`` etc. are
constructed.

Public surface
--------------
* :meth:`enqueue_figure` — Stage 2 calls this for every figure it extracts.
  Applies backpressure: if the worker pool is behind, Stage 2 waits here.
* :meth:`drain_and_close` — Stage 2 calls this after the last page is
  emitted; orchestrator closes the queue, waits for workers, returns the
  final counters.
* :meth:`get_summary` — synchronous-style lookup used by Stage 4's figure
  token resolver.  Returns ``None`` when the token is not yet ready.

The orchestrator implements no logic beyond composition and these three
methods — all behaviour lives in the named collaborators where it can be
reasoned about and replaced in isolation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Self

from ..contracts import (
    AbstractFigureDedupCache,
    AbstractFigureSummaryStore,
    AbstractFigureWorkQueue,
    AbstractVisionFigureClient,
    AssemblyConfig,
    DocumentDomain,
    FaultToleranceConfig,
    Figure,
    FigureSummarizationConfig,
    FigureSummary,
    FigureVisionProvider,
    GPUConfig,
)
from ..fault_tolerance import (
    AsyncOperationTimeoutGuard,
    EngineCircuitBreaker,
    ExponentialBackoffRetry,
)
from ..gpu_resource_management import ExclusiveGPUContextManager
from .async_bounded_figure_queue import AsyncBoundedFigureQueue
from .figure_sha256_deduplication_cache import JsonFigureSha256DeduplicationCache
from .figure_summarization_prompt import FigureSummarizationPromptBuilder
from .figure_summarization_worker_pool import (
    FigureSummarizationCounters,
    FigureSummarizationWorkerPool,
)
from .figure_summary_store import JsonFigureSummaryStore
from .local_vision_concurrency_limiter import LocalVisionConcurrencyLimiter
from .ollama_vision_client import OllamaVisionFigureClient
from .openai_vision_client import OpenAIVisionFigureClient

logger = logging.getLogger(__name__)


# A logical name used for circuit-breaker telemetry and GPU-lock logs.
# Kept here (not in config) because it is part of the structured-log
# vocabulary the operator-facing dashboards depend on.
_STAGE3_COMPONENT_NAME = "stage3.figure_summarization"


class FigureSummarizationOrchestrator:
    """
    The Stage 3 entry point.

    Construction is via :meth:`build` (a factory) which performs all the
    dependency wiring from configuration.  Direct ``__init__`` is reserved
    for tests / advanced callers that want to inject custom collaborators
    (e.g. an in-memory store, a recording vision client).
    """

    def __init__(
        self,
        *,
        queue: AbstractFigureWorkQueue,
        worker_pool: FigureSummarizationWorkerPool,
        summary_store: AbstractFigureSummaryStore,
        dedup_cache: AbstractFigureDedupCache,
        vision_client: AbstractVisionFigureClient,
        enabled: bool,
    ) -> None:
        self._queue = queue
        self._worker_pool = worker_pool
        self._summary_store = summary_store
        self._dedup_cache = dedup_cache
        self._vision_client = vision_client
        self._enabled = enabled
        self._started = False

    # ------------------------------------------------------------------
    # Factory — composition root
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        figure_summarization_config: FigureSummarizationConfig,
        fault_tolerance_config: FaultToleranceConfig,
        gpu_config: GPUConfig,
        assembly_config: AssemblyConfig,
        job_output_dir: Path,
        document_domain: DocumentDomain = DocumentDomain.AUTO,
    ) -> Self:
        """
        Build a fully-wired orchestrator from configuration objects.

        Path conventions:

        * Dedup cache    →  ``<job_output_dir>/<deduplication_cache_dir>``
        * Summary store  →  ``<job_output_dir>/<summary_store_dir>``
        * Image cache    →  configured directly on
          :class:`OllamaVisionClientConfig` (relative or absolute; the
          orchestrator does not relocate it).

        Provider selection: ``figure_summarization_config.provider`` decides
        between the local Ollama client (default) and the cloud
        ``vision_llm`` path.  Today only the local path is implemented;
        attempting to select ``cloud`` raises a clear error rather than
        silently degrading.
        """
        prompt_builder = FigureSummarizationPromptBuilder()

        vision_client = cls._build_vision_client(
            config=figure_summarization_config,
            prompt_builder=prompt_builder,
            document_domain=document_domain,
        )

        dedup_cache = JsonFigureSha256DeduplicationCache(
            cache_directory=job_output_dir
            / figure_summarization_config.deduplication_cache_dir,
        )
        summary_store = JsonFigureSummaryStore(
            store_directory=job_output_dir
            / figure_summarization_config.summary_store_dir,
        )

        queue = AsyncBoundedFigureQueue(
            max_queue_size=figure_summarization_config.max_queue_size,
            num_workers=figure_summarization_config.worker_pool_size,
        )

        limiter = LocalVisionConcurrencyLimiter(
            in_flight_limit=figure_summarization_config.local_vision_in_flight_limit,
        )

        timeout_guard = AsyncOperationTimeoutGuard(fault_tolerance_config.timeouts)
        # Stage 3 gets its own retry policy whose ``attempts`` is sourced
        # from ``figure_retries`` — that knob exists precisely so Stage 3's
        # retry budget can be tuned independently of Stage 2 engines, which
        # share the global ``fault_tolerance.retry`` config.  Backoff
        # parameters are inherited from the global config so jitter /
        # exponential growth stay consistent across the pipeline.
        stage3_retry_config = fault_tolerance_config.retry.model_copy(
            update={"attempts": figure_summarization_config.figure_retries},
        )
        retry_policy = ExponentialBackoffRetry(stage3_retry_config)
        circuit_breaker = EngineCircuitBreaker(
            fault_tolerance_config.circuit_breaker,
            component_name=_STAGE3_COMPONENT_NAME,
        )

        # GPU lock is only meaningful when (a) GPU is enabled and (b) the
        # vision client actually uses the local GPU.  The cloud client
        # talks to a remote API, so the lock would just serialise workers
        # for no reason — skip it.
        gpu_context_factory = None
        uses_local_gpu = (
            figure_summarization_config.provider == FigureVisionProvider.LOCAL_OLLAMA
        )
        if uses_local_gpu and gpu_config.enabled and not gpu_config.force_cpu:
            gpu_context_factory = lambda: ExclusiveGPUContextManager(  # noqa: E731
                gpu_config,
                timeout_guard,
                component_name=_STAGE3_COMPONENT_NAME,
            )

        worker_pool = FigureSummarizationWorkerPool(
            queue=queue,
            vision_client=vision_client,
            dedup_cache=dedup_cache,
            summary_store=summary_store,
            concurrency_limiter=limiter,
            retry_policy=retry_policy,
            timeout_guard=timeout_guard,
            circuit_breaker=circuit_breaker,
            gpu_context_factory=gpu_context_factory,
            worker_pool_size=figure_summarization_config.worker_pool_size,
            figure_retries=figure_summarization_config.figure_retries,
            degraded_placeholder_markdown=assembly_config.degraded_mode_placeholder,
            deduplication_enabled=figure_summarization_config.deduplication_enabled,
        )

        return cls(
            queue=queue,
            worker_pool=worker_pool,
            summary_store=summary_store,
            dedup_cache=dedup_cache,
            vision_client=vision_client,
            enabled=figure_summarization_config.enabled,
        )

    @staticmethod
    def _build_vision_client(
        *,
        config: FigureSummarizationConfig,
        prompt_builder: FigureSummarizationPromptBuilder,
        document_domain: DocumentDomain,
    ) -> AbstractVisionFigureClient:
        """
        Resolve the configured ``provider`` to a concrete vision client.

        * ``CLOUD`` (default) → :class:`OpenAIVisionFigureClient` —
          OpenAI-compatible Responses / Chat API (``gpt-5-nano``,
          ``qvq-max`` on DashScope, etc.).  Reliable, fast, no local GPU
          required.
        * ``LOCAL_OLLAMA`` → :class:`OllamaVisionFigureClient` — local
          Qwen-VL via Ollama.  Opt-in for capable on-box GPUs / PHI
          isolation requirements.
        """
        if config.provider == FigureVisionProvider.CLOUD:
            return OpenAIVisionFigureClient(
                config=config.vision_llm,
                prompt_builder=prompt_builder,
                document_domain=document_domain,
            )
        if config.provider == FigureVisionProvider.LOCAL_OLLAMA:
            return OllamaVisionFigureClient(
                config=config.ollama_vision_client,
                prompt_builder=prompt_builder,
                document_domain=document_domain,
            )
        raise NotImplementedError(
            f"Unknown vision provider {config.provider!r}.  Valid values: "
            f"{FigureVisionProvider.CLOUD.value!r} (default), "
            f"{FigureVisionProvider.LOCAL_OLLAMA.value!r}."
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the worker pool.  Idempotent.

        When ``enabled=False`` the orchestrator is a no-op shell: figures
        enqueued are accepted but never summarised, ``drain_and_close``
        returns zero counters, and Stage 4 will substitute the degraded
        placeholder for every ``${FIG:...}`` token via its normal timeout
        path.  This is the documented behaviour of
        ``figure_summarization.enabled=false`` for fast dev cycles.
        """
        if self._started or not self._enabled:
            self._started = True
            return
        self._worker_pool.start()
        self._started = True
        logger.info("stage3.orchestrator.started")

    # ------------------------------------------------------------------
    # Producer-side API (called by Stage 2 / pipeline orchestrator)
    # ------------------------------------------------------------------

    async def enqueue_figure(self, figure: Figure) -> None:
        """
        Hand one figure to the worker pool.

        Blocks (via the bounded queue) when summarization cannot keep up
        with extraction — this is the backpressure that protects RAM.

        No-op when Stage 3 is disabled: figures pass through silently and
        Stage 4's degraded path handles the substitution.
        """
        if not self._enabled:
            return
        if not self._started:
            self.start()
        await self._queue.put(figure)

    async def drain_and_close(self) -> FigureSummarizationCounters:
        """
        Signal "no more figures coming" and wait for workers to finish.

        Returns the final counters so the pipeline orchestrator can copy
        them into :class:`ConversionSummary`.
        """
        if not self._enabled:
            return FigureSummarizationCounters()
        await self._queue.close()
        return await self._worker_pool.join()

    # ------------------------------------------------------------------
    # Consumer-side API (called by Stage 4 / token resolver)
    # ------------------------------------------------------------------

    async def get_summary(self, token: str) -> FigureSummary | None:
        """
        Look up the persisted summary for a ``${FIG:...}`` token.

        Returns ``None`` when the token is not yet ready — Stage 4 polls
        through a timeout guard and falls back to the degraded placeholder
        when its budget elapses.
        """
        return await self._summary_store.get(token)
