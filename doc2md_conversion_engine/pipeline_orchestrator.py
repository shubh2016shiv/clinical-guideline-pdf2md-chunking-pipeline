"""
pipeline_orchestrator.py
=========================
Wires the preflight gate and Stage 1 modules together into a single call.

This is the only place that knows the order: intake → hash → provision → feature
extraction → deterministic capability routing (Stage 1), then engine bootstrap
(untimed model preparedness) → windowed page extraction (Stage 2).  Entrypoints
(CLI, API) call this and receive a result object — they never touch stage-internal
modules directly.

Usage
-----
::

    from doc2md_conversion_engine.pipeline_orchestrator import (
        PipelineOrchestrator,
        Stage1Result,
    )
    from doc2md_conversion_engine.contracts.configurations.pipeline_config import (
        PipelineConfig,
    )

    config = PipelineConfig()
    orchestrator = PipelineOrchestrator(config)

    result = orchestrator.run_stage1(Path("/path/to/document.<ext>"))
    print(result.engine)           # e.g. "mineru" or "docling"
    print(result.complexity_score) # routing score; engine-dependent
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path

from .contracts.assembly_interfaces import AbstractFigureSummaryProvider
from .contracts.configurations.pipeline_config import PipelineConfig
from .contracts.exceptions import DocumentError
from .contracts.figure_summarization_types import DocumentDomain, FigureSummary
from .contracts.pipeline_domain_types import (
    ConversionJob,
    ConversionSummary,
    EngineClassification,
    PageResult,
)
from .engine_bootstrap import EngineBootstrapSelector
from .file_upload_management import DocumentUploadIntake, UploadedDocumentStagingStore
from .stage1_document_prescanning import (
    DocumentFeatureExtractor,
    DocumentFeatureProfile,
    DocumentSHA256Hasher,
    EngineRoutingPolicy,
)
from .stage2_page_extraction import WindowedPageExtractionOrchestrator
from .stage3_figure_summarization import (
    FigureSummarizationCounters,
    FigureSummarizationOrchestrator,
)
from .stage4_assembly_and_output import StreamingDocumentAssembler

logger = logging.getLogger(__name__)


@dataclass
class Stage1Result:
    """Everything Stage 1 knows about a document after prescanning."""

    document_name: str
    document_path: Path
    job_id: str
    document_type: str
    file_size_bytes: int
    total_pages: int
    output_dir: Path
    engine: str
    complexity_score: float
    confidence: float
    reason: str
    feature_summary: str
    inferred_requirements: list[str]
    elapsed_ms: float
    errors: list[str] = field(default_factory=list)


@dataclass
class DocumentConversionStream:
    """
    Live handle to one in-flight document conversion.

    Returned by :meth:`PipelineOrchestrator.start_conversion`.  Bundles the
    three things a caller (CLI / API / Stage 4 assembler) needs in lock-step:

    * the live :class:`ConversionJob` and :class:`EngineClassification`,
    * the **async generator of pages** — iterating this drives Stage 2
      extraction AND, transparently, feeds every figure into Stage 3 so the
      worker pool is summarising while the caller is still consuming pages,
    * the **Stage 3 orchestrator handle** — exposed so Stage 4's token
      resolver can call :meth:`FigureSummarizationOrchestrator.get_summary`
      against the same instance that is being fed from Stage 2.

    Lifecycle::

        stream = orchestrator.start_conversion(path)
        async for page_result in stream.page_results:
            # Stage 4 can resolve tokens here using stream.figure_summarization
            ...
        counters = await stream.finalize()

    Why a session object (not just a generator)?
    ---------------------------------------------
    Stage 3's correctness depends on three lifecycle events happening in
    order: ``start`` (before any figure is enqueued), ``enqueue_figure`` per
    page, and ``drain_and_close`` (exactly once after the last page).  A
    bare generator would either hide ``drain_and_close`` from the caller or
    expose it through error-prone side channels.  A session makes the
    contract explicit: the caller calls :meth:`finalize` exactly once.
    """

    job: ConversionJob
    classification: EngineClassification
    figure_summarization: FigureSummarizationOrchestrator
    page_results: AsyncGenerator[PageResult, None]

    async def finalize(self) -> FigureSummarizationCounters:
        """
        Close the figure queue and wait for Stage 3 workers to finish.

        Must be called exactly once, after :attr:`page_results` is fully
        exhausted (or the iteration is abandoned).  Returns the counters
        that flow straight into :class:`ConversionSummary`.
        """
        return await self.figure_summarization.drain_and_close()


class _Stage3FigureSummaryProviderAdapter(AbstractFigureSummaryProvider):
    """
    Expose the Stage 3 orchestrator under the read-only Stage 4 contract.

    Stage 4 must not see Stage 3's producer-side methods
    (``enqueue_figure``, ``drain_and_close``).  This adapter narrows the
    handle to ``get_summary`` only, enforcing the architectural rule that
    Stage 4 is a *consumer* of Stage 3, never a co-driver.
    """

    def __init__(
        self, figure_summarization: FigureSummarizationOrchestrator
    ) -> None:
        self._figure_summarization = figure_summarization

    async def get_summary(self, token: str) -> FigureSummary | None:
        return await self._figure_summarization.get_summary(token)


@dataclass
class _PrescanOutcome:
    """The rich Stage 1 domain objects, before they are flattened for reporting.

    ``run_stage1`` flattens these into a ``Stage1Result`` for the CLI; Stage 2 needs
    the live ``ConversionJob`` and ``EngineClassification`` (which carry the engine
    backend and output paths that the flattened result drops), so both paths share
    this one prescan.
    """

    job: ConversionJob
    classification: EngineClassification
    feature_profile: DocumentFeatureProfile
    file_size_bytes: int
    elapsed_ms: float


class PipelineOrchestrator:
    """
    Wires preflight + Stage 1 into ``run_stage1()``.

    Instantiate once per application lifetime::

        orchestrator = PipelineOrchestrator(PipelineConfig())
        result = orchestrator.run_stage1(Path("/path/to/document.<ext>"))
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config
        self._intake = DocumentUploadIntake(config.document_constraints)
        self._hasher = DocumentSHA256Hasher(config.document_constraints)
        self._store = UploadedDocumentStagingStore(config.storage)
        self._feature_extractor = DocumentFeatureExtractor(
            feature_config=config.document_feature_extraction,
            constraints=config.document_constraints,
        )
        self._router = EngineRoutingPolicy(config.engine_routing)
        self._engine_bootstrap = EngineBootstrapSelector(config)
        self._stage2 = WindowedPageExtractionOrchestrator(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_stage1(self, document_path: Path) -> Stage1Result:
        """
        Preflight → hash → provision → feature extraction → route.

        Returns a ``Stage1Result`` on success.  Raises ``DocumentError`` on
        any failure (preflight rejection, corrupt file, unsupported format,
        invalid config, or failed feature extraction).
        """
        outcome = self._prescan(document_path)
        job = outcome.job
        classification = outcome.classification
        return Stage1Result(
            document_name=document_path.name,
            document_path=document_path,
            job_id=job.job_id,
            document_type=job.document_type.value,
            file_size_bytes=outcome.file_size_bytes,
            total_pages=outcome.feature_profile.page_or_unit_count,
            output_dir=job.output_dir,
            engine=classification.engine.value,
            complexity_score=classification.complexity_score,
            confidence=classification.confidence,
            reason=classification.reason,
            feature_summary=outcome.feature_profile.compact_summary(),
            inferred_requirements=outcome.feature_profile.requirements.rationale,
            elapsed_ms=outcome.elapsed_ms,
            errors=[],
        )

    async def convert_document(self, document_path: Path) -> AsyncGenerator[PageResult, None]:
        """
        Run the full conversion: Stage 1 prescan, then Stage 2 extraction.

        Yields one ``PageResult`` per page as it is extracted, so callers can stream
        results into Stage 3 (figures) and Stage 4 (assembly) while later pages are
        still being converted. Resumes automatically from a prior checkpoint when one
        exists for this document.

        Note: this method does **not** wire Stage 3.  Callers that need figure
        summarization should use :meth:`start_conversion` instead, which returns a
        :class:`DocumentConversionStream` that drives Stage 2 + Stage 3 together
        and exposes the :class:`FigureSummarizationOrchestrator` to Stage 4.  This
        method is retained for the Stage 1/2-only diagnostic path used by the CLI's
        ``--no-figures`` mode and by tests.
        """
        outcome = self._prescan(document_path)
        async for page_result in self.run_stage2(outcome.job, outcome.classification):
            yield page_result

    def start_conversion(
        self,
        document_path: Path,
        *,
        document_domain: DocumentDomain = DocumentDomain.AUTO,
    ) -> DocumentConversionStream:
        """
        Begin a full Stage 1 → Stage 2 → Stage 3 conversion session.

        Returns a :class:`DocumentConversionStream` immediately; the actual
        extraction work runs when the caller starts iterating
        :attr:`DocumentConversionStream.page_results`.

        Wiring (the contract this method is responsible for):

        * Stage 1 prescan runs here, synchronously, so any
          :class:`DocumentError` / :class:`DocumentTooLargeError` /
          :class:`ConfigurationError` surfaces before any GPU work begins.
        * The Stage 3 orchestrator is constructed (per job, with the job's
          ``output_dir`` rooting the dedup cache and summary store) and
          started before the first page is yielded.  This guarantees a
          worker is ready when the first ``enqueue_figure`` arrives.
        * The page generator wraps :meth:`run_stage2` and enqueues every
          ``figure`` on every ``PageResult`` into Stage 3 *before* yielding
          the page to the caller.  Backpressure from Stage 3 therefore
          slows Stage 2 naturally — exactly the architectural intent.
        * The caller is responsible for calling
          :meth:`DocumentConversionStream.finalize` once iteration is done
          to drain Stage 3 and collect the counters.

        Parameters
        ----------
        document_path:
            The source document to convert.
        document_domain:
            Optional domain hint passed into the Stage 3 prompt.  Defaults
            to ``AUTO``, letting the VLM infer the domain from visual
            context — appropriate for mixed corpora.  Pass
            ``DocumentDomain.CLINICAL`` (or another concrete value) when the
            caller knows the corpus a priori.
        """
        outcome = self._prescan(document_path)
        stage3 = self._build_stage3_orchestrator(
            job=outcome.job,
            document_domain=document_domain,
        )
        # Stage 3 is *not* eagerly started here — its worker tasks require a
        # running event loop.  ``enqueue_figure`` lazy-starts on first use,
        # which is guaranteed to happen inside the caller's event loop when
        # the page generator runs.

        page_generator = self._page_stream_feeding_stage3(
            job=outcome.job,
            classification=outcome.classification,
            stage3=stage3,
        )

        return DocumentConversionStream(
            job=outcome.job,
            classification=outcome.classification,
            figure_summarization=stage3,
            page_results=page_generator,
        )

    async def convert_to_markdown(
        self,
        document_path: Path,
        *,
        document_domain: DocumentDomain = DocumentDomain.AUTO,
    ) -> ConversionSummary:
        """
        Run the full Stage 1 → 2 → 3 → 4 pipeline and publish the assembled
        Markdown file atomically.

        Returns the :class:`ConversionSummary` populated with the on-disk
        path of the published ``.md`` and the figure counters from Stage 3.

        Lifecycle (the contract this method owns)
        -----------------------------------------
        1. ``start_conversion`` builds the Stage 3 orchestrator and returns
           a :class:`DocumentConversionStream`.
        2. A Stage 4 :class:`StreamingDocumentAssembler` is built against
           the *same* Stage 3 handle, exposed as a read-only
           :class:`AbstractFigureSummaryProvider` — Stage 4 cannot
           accidentally call producer-side Stage 3 methods.
        3. The assembler's ``run`` consumes ``stream.page_results``.  Each
           page is iterated to drive Stage 2 *and* enqueue figures into
           Stage 3 (see :meth:`_page_stream_feeding_stage3`); the assembler
           polls Stage 3 for each ``${FIG:...}`` token as it arrives.
        4. After the page stream exhausts, ``stream.finalize()`` drains
           Stage 3 workers and returns the figure counters.  ``try/finally``
           ensures Stage 3 is always drained, even if the assembler raises.
        5. The assembler's ``build_conversion_summary`` folds the counters
           into the final :class:`ConversionSummary`.
        """
        stream = self.start_conversion(
            document_path, document_domain=document_domain
        )
        assembler = StreamingDocumentAssembler.build(
            job=stream.job,
            assembly_config=self._config.assembly,
            fault_tolerance_config=self._config.fault_tolerance,
            figure_summary_provider=_Stage3FigureSummaryProviderAdapter(
                stream.figure_summarization
            ),
        )

        counters: FigureSummarizationCounters | None = None
        try:
            output_markdown_path = await assembler.run(stream.page_results)
        finally:
            counters = await stream.finalize()

        return assembler.build_conversion_summary(
            output_markdown_path=output_markdown_path,
            figures_summarized=counters.figures_summarized,
            figures_deduplicated=counters.figures_deduplicated,
            figures_failed=counters.figures_failed,
        )

    async def run_stage2(
        self,
        job: ConversionJob,
        classification: EngineClassification,
    ) -> AsyncGenerator[PageResult, None]:
        """
        Drive Stage 2 for an already-prescanned job, streaming each extracted page.

        First makes the chosen engine ready (``engine_bootstrap``), then streams the
        page results from the windowed, checkpointed, fault-tolerant extractor.

        Bootstrap runs here, *before* the timed engine lifecycle, and is deliberately
        untimed: a first-run model download may legitimately take minutes. Doing it
        here is what lets Stage 2's startup and per-window timeouts bound only real
        extraction work, never a model download.
        """
        readiness = await self._engine_bootstrap.bootstrap_for(classification.engine).ensure_ready()
        logger.info(
            "stage2.bootstrap.ready job_id=%s engine=%s backend=%s gpu_enabled=%s notes=%s",
            job.job_id,
            readiness.engine.value,
            readiness.resolved_backend,
            readiness.gpu_enabled,
            "; ".join(readiness.notes),
        )

        async for page_result in self._stage2.extract(job, classification):
            yield page_result

    # ------------------------------------------------------------------
    # Stage 3 wiring (build + producer-side feed)
    # ------------------------------------------------------------------

    def _build_stage3_orchestrator(
        self,
        *,
        job: ConversionJob,
        document_domain: DocumentDomain,
    ) -> FigureSummarizationOrchestrator:
        """
        Build a job-scoped :class:`FigureSummarizationOrchestrator`.

        Stage 3 state (dedup cache, summary store) is rooted under the
        job's ``output_dir`` so two concurrent conversions cannot stomp on
        each other's caches, and so a resume always finds the state where
        it left it.  All resilience and GPU collaborators are derived from
        the same :class:`PipelineConfig` instance Stage 2 uses, so Stage 3's
        timeouts / retry policy / breaker stay consistent with the rest of
        the pipeline.
        """
        return FigureSummarizationOrchestrator.build(
            figure_summarization_config=self._config.figure_summarization,
            fault_tolerance_config=self._config.fault_tolerance,
            gpu_config=self._config.gpu,
            assembly_config=self._config.assembly,
            job_output_dir=job.output_dir,
            document_domain=document_domain,
        )

    async def _page_stream_feeding_stage3(
        self,
        *,
        job: ConversionJob,
        classification: EngineClassification,
        stage3: FigureSummarizationOrchestrator,
    ) -> AsyncGenerator[PageResult, None]:
        """
        Stream pages from Stage 2 and feed each page's figures into Stage 3.

        Per page, the order is intentional:

        1. Enqueue every figure on the page **first**.  Stage 3 starts
           working on these as soon as a worker is free, in parallel with
           the caller's consumption of the page.
        2. Yield the page to the caller.  Stage 4 may begin assembling
           immediately and call ``stage3.get_summary(token)`` for each
           ``${FIG:...}`` placeholder.

        ``enqueue_figure`` is bounded by the Stage 3 queue, so if Stage 3
        falls behind, Stage 2 naturally throttles here without any extra
        coordination code.  Backpressure flows the right way: from the
        slow component to the fast one.

        Note on lifecycle: this generator does *not* call
        ``stage3.drain_and_close``.  The :class:`DocumentConversionStream`
        ``finalize`` method owns that, so the contract stays explicit:
        finishing the page stream is *not* the same as committing Stage 3.
        """
        async for page_result in self.run_stage2(job, classification):
            for figure in page_result.figures:
                await stage3.enqueue_figure(figure)
            yield page_result

    # ------------------------------------------------------------------
    # Shared prescan (Stage 1)
    # ------------------------------------------------------------------

    def _prescan(self, document_path: Path) -> _PrescanOutcome:
        """
        Run the Stage 1 steps and return the live domain objects.

        Preflight → hash → provision → feature extraction → deterministic routing.
        Produces the ``ConversionJob`` (with the page count discovered during feature
        extraction) and the ``EngineClassification`` that Stage 2 consumes. Raises
        ``DocumentError`` / ``DocumentTooLargeError`` / ``ConfigurationError`` on any
        failure, exactly as the individual Stage 1 components do.
        """
        started_at = time.perf_counter()

        # -- Preflight (stat-only, < 1 ms) ---------------------------------
        self._intake.validate(document_path)

        # -- Hash (streaming, 100 ms – 1.5 s) ------------------------------
        hash_result = self._hasher.compute(document_path)

        # -- Workspace provisioning -----------------------------------------
        output_dir = self._store.provision(hash_result.sha256_hex)

        # -- Deterministic feature evidence ---------------------------------
        feature_profile = self._feature_extractor.extract(document_path, hash_result.document_type)

        # -- Deterministic capability-based engine routing ------------------
        classification = self._router.route(feature_profile)

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        job = ConversionJob(
            job_id=hash_result.sha256_hex,
            document_path=document_path,
            document_type=hash_result.document_type,
            output_dir=output_dir,
            total_pages=feature_profile.page_or_unit_count,
        )
        return _PrescanOutcome(
            job=job,
            classification=classification,
            feature_profile=feature_profile,
            file_size_bytes=hash_result.file_size_bytes,
            elapsed_ms=elapsed_ms,
        )

    # ------------------------------------------------------------------
    # Convenience: batch over a directory
    # ------------------------------------------------------------------

    def collect_documents(self, root: Path, *, recursive: bool = False) -> list[Path]:
        """
        Walk *root* and return supported document paths, sorted.

        Raises ``DocumentError`` if *root* is neither a file nor a directory.
        """
        if root.is_file():
            return [root]
        if not root.is_dir():
            raise DocumentError(f"Not a file or directory: {root}")

        pattern = "**/*" if recursive else "*"
        supported = {".pdf", ".docx", ".pptx", ".html", ".htm"}
        return sorted(
            p for p in root.glob(pattern) if p.is_file() and p.suffix.lower() in supported
        )
