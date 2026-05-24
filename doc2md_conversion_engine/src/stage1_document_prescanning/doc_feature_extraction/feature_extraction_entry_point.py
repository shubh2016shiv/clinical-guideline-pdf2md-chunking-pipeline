"""
doc_feature_extraction/feature_extraction_entry_point.py
=========================================================
Single public entry point for deterministic document feature extraction.

Callers hand in a document path and its type; this module hands back a
``DocumentFeatureProfile``.  The fact that PDF, DOCX, PPTX, and HTML each
have their own extractor module is an implementation detail hidden here.
"""

from __future__ import annotations

from pathlib import Path

from ...contracts.configurations.pipeline_config import DocumentFeatureExtractionConfig
from ...contracts.exceptions import DocumentError
from ...contracts.pipeline_domain_types import DocumentType
from .docx import extract_docx_features
from .html import extract_html_features
from .models import DocumentFeatureProfile
from .pdf import extract_pdf_features
from .pptx import extract_pptx_features

# Maps each accepted document type to the function that extracts its features.
# All extractor functions share the same signature:
#   (path: Path, config: DocumentFeatureExtractionConfig | None) -> DocumentFeatureProfile
FORMAT_EXTRACTORS = {
    DocumentType.PDF: extract_pdf_features,
    DocumentType.DOCX: extract_docx_features,
    DocumentType.PPTX: extract_pptx_features,
    DocumentType.HTML: extract_html_features,
}


class DocumentFeatureExtractionEntryPoint:
    """
    Produce a ``DocumentFeatureProfile`` for any supported document format.

    Config (thresholds from ``settings.yaml``) is injected once at construction
    and forwarded to every per-format extractor call — so tuning a threshold in
    ``settings.yaml`` takes effect for all formats without touching this class.
    """

    def __init__(self, config: DocumentFeatureExtractionConfig | None = None) -> None:
        self._config = config or DocumentFeatureExtractionConfig()

    def extract(self, document_path: Path, document_type: DocumentType) -> DocumentFeatureProfile:
        """Return the feature profile for *document_path* based on its *document_type*."""
        extractor = FORMAT_EXTRACTORS.get(document_type)
        if extractor is None:
            raise DocumentError(
                f"Feature extraction is not supported for {document_type.value!r}.",
                context={"path": str(document_path), "document_type": document_type.value},
            )
        return extractor(document_path, self._config)
