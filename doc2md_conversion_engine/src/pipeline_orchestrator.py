"""
pipeline_orchestrator.py
=========================
Wires the preflight gate and Stage 1 modules together into a single call.

This is the only place that knows the order: intake → hash → provision →
feature extraction → optional local visual adjudication → capability routing.
Entrypoints (CLI, API) call this and receive a result object — they never touch
stage-internal modules directly.

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
from dataclasses import dataclass, field
from pathlib import Path

from .contracts.configurations.pipeline_config import PipelineConfig
from .contracts.exceptions import DocumentError
from .file_upload_management import DocumentUploadIntake, UploadedDocumentStagingStore
from .stage1_document_prescanning import DocumentSHA256Hasher
from .stage1_document_prescanning.doc_feature_extraction import (
    CapabilityBasedEngineRouter,
    DocumentFeatureExtractionEntryPoint,
)
from .stage1_document_prescanning.engine_decision_router import EngineRoutingAgent


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
    ollama_payload: dict[str, object] | None
    elapsed_ms: float
    errors: list[str] = field(default_factory=list)


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
        self._feature_extractor = DocumentFeatureExtractionEntryPoint(config.document_feature_extraction)
        self._routing_agent = EngineRoutingAgent(config.engine_routing.ollama_client)
        self._router = CapabilityBasedEngineRouter(config.engine_routing)

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
        t0 = time.perf_counter()
        errors: list[str] = []

        # -- Preflight (stat-only, < 1 ms) ---------------------------------
        self._intake.validate(document_path)

        # -- Hash (streaming, 100 ms – 1.5 s) ------------------------------
        hash_result = self._hasher.compute(document_path)

        # -- Workspace provisioning -----------------------------------------
        output_dir = self._store.provision(hash_result.sha256_hex)

        # -- Deterministic feature evidence ---------------------------------
        feature_profile = self._feature_extractor.extract(document_path, hash_result.document_type)
        ollama_payload = None
        visual_decision = None
        if feature_profile.requirements.needs_local_vlm_adjudication:
            try:
                visual_decision = self._routing_agent.decide(feature_profile)
                ollama_payload = visual_decision.model_dump(mode="json")
            except DocumentError as exc:
                errors.append(str(exc))

        # -- Capability-based engine routing --------------------------------
        classification = self._router.route(feature_profile, visual_decision=visual_decision)

        elapsed = (time.perf_counter() - t0) * 1000

        return Stage1Result(
            document_name=document_path.name,
            document_path=document_path,
            job_id=hash_result.sha256_hex,
            document_type=hash_result.document_type.value,
            file_size_bytes=hash_result.file_size_bytes,
            total_pages=feature_profile.page_or_unit_count,
            output_dir=output_dir,
            engine=classification.engine.value,
            complexity_score=classification.complexity_score,
            confidence=classification.confidence,
            reason=classification.reason,
            feature_summary=feature_profile.compact_summary(),
            inferred_requirements=feature_profile.requirements.rationale,
            ollama_payload=ollama_payload,
            elapsed_ms=elapsed,
            errors=errors,
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
