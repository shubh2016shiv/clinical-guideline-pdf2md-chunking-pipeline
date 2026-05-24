"""
pipeline_orchestrator.py
=========================
Wires the preflight gate and Stage 1 modules together into a single call.

This is the only place that knows the order: intake → hash → provision →
scan → classify.  Entrypoints (CLI, API) call this and receive a result
object — they never touch stage-internal modules directly.

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
from .stage1_document_prescanning import (
    DocumentComplexityClassifier,
    DocumentPageStructureScanner,
    DocumentSHA256Hasher,
)


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
        self._scanner = DocumentPageStructureScanner(config.document_constraints)
        self._classifier = DocumentComplexityClassifier(config.engine_routing)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_stage1(self, document_path: Path) -> Stage1Result:
        """
        Preflight → hash → provision → scan → classify.

        Returns a ``Stage1Result`` on success.  Raises ``DocumentError`` on
        any failure (preflight rejection, corrupt file, unsupported format,
        page count exceeded, invalid config).
        """
        t0 = time.perf_counter()
        errors: list[str] = []

        # -- Preflight (stat-only, < 1 ms) ---------------------------------
        self._intake.validate(document_path)

        # -- Hash (streaming, 100 ms – 1.5 s) ------------------------------
        hash_result = self._hasher.compute(document_path)

        # -- Workspace provisioning -----------------------------------------
        output_dir = self._store.provision(hash_result.sha256_hex)

        # -- Page structure scan --------------------------------------------
        scan_result = self._scanner.scan(document_path, hash_result.document_type)

        # -- Complexity classification --------------------------------------
        classification = self._classifier.classify(scan_result.profiles)

        elapsed = (time.perf_counter() - t0) * 1000

        return Stage1Result(
            document_name=document_path.name,
            document_path=document_path,
            job_id=hash_result.sha256_hex,
            document_type=hash_result.document_type.value,
            file_size_bytes=hash_result.file_size_bytes,
            total_pages=scan_result.total_pages,
            output_dir=output_dir,
            engine=classification.engine.value,
            complexity_score=classification.complexity_score,
            confidence=classification.confidence,
            reason=classification.reason,
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
