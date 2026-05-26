"""
pipeline_orchestrator.py
=========================
Wires the preflight gate and Stage 1 modules together into a single call.

This is the only place that knows the order: intake → hash → provision →
feature extraction → deterministic capability routing.  Entrypoints (CLI, API)
call this and receive a result object — they never touch stage-internal modules
directly.

Usage
-----
::

    from doc2md_conversion_engine.src.pipeline_orchestrator import (
        PipelineOrchestrator,
        Stage1Result,
    )
    from doc2md_conversion_engine.src.contracts.configurations.pipeline_config import (
        PipelineConfig,
    )

    config = PipelineConfig()
    orchestrator = PipelineOrchestrator(config)

    result = orchestrator.run_stage1(Path("/data/Headache.pdf"))
    print(result.engine)           # "mineru"
    print(result.complexity_score) # 3.25
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from pathlib import Path

from .contracts.configurations.pipeline_config import PipelineConfig
from .contracts.exceptions import DocumentError
from .contracts.pipeline_domain_types import (
    ConversionJob,
    EngineClassification,
    PageResult,
)
from .file_upload_management import DocumentUploadIntake, UploadedDocumentStagingStore
from .stage1_document_prescanning import (
    DocumentFeatureExtractor,
    DocumentFeatureProfile,
    DocumentSHA256Hasher,
    EngineRoutingPolicy,
)
from .stage2_page_extraction import WindowedPageExtractionOrchestrator


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
        result = orchestrator.run_stage1(Path("/data/Headache.pdf"))
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._intake = DocumentUploadIntake(config.document_constraints)
        self._hasher = DocumentSHA256Hasher(config.document_constraints)
        self._store = UploadedDocumentStagingStore(config.storage)
        self._feature_extractor = DocumentFeatureExtractor(
            feature_config=config.document_feature_extraction,
            constraints=config.document_constraints,
        )
        self._router = EngineRoutingPolicy(config.engine_routing)
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
        """
        outcome = self._prescan(document_path)
        async for page_result in self.run_stage2(outcome.job, outcome.classification):
            yield page_result

    async def run_stage2(
        self,
        job: ConversionJob,
        classification: EngineClassification,
    ) -> AsyncGenerator[PageResult, None]:
        """
        Drive Stage 2 for an already-prescanned job, streaming each extracted page.

        Takes the live ``ConversionJob`` and ``EngineClassification`` from Stage 1
        (the engine choice plus its backend and output paths) and yields the page
        stream produced by the windowed, checkpointed, fault-tolerant extractor.
        """
        async for page_result in self._stage2.extract(job, classification):
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
