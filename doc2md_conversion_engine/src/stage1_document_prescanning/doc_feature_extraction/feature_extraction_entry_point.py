"""
doc_feature_extraction/feature_extraction_entry_point.py
=========================================================
Single public entry point for deterministic document feature extraction.

Callers hand in a document path and its type; this module hands back a
``DocumentFeatureProfile``.  The fact that PDF, DOCX, PPTX, and HTML each
have their own extractor module is an implementation detail hidden here.

Constraint enforcement
----------------------
Page-count enforcement lives here because this is the first — and only —
place the page count is known before Stage 2 work begins.  File-size
enforcement lives in ``DocumentSHA256Hasher`` for the same reason: enforce
at the earliest point the information is available.
"""

from __future__ import annotations

from pathlib import Path

from ...contracts.configurations.pipeline_config import (
    DocumentConstraintsConfig,
    DocumentFeatureExtractionConfig,
)
from ...contracts.exceptions import DocumentError, DocumentTooLargeError
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

    Accepts two config objects injected at construction:

    ``feature_config``
        Format-specific extraction thresholds from ``settings.yaml``.
        Forwarded to every per-format extractor so tuning a threshold takes
        effect for all formats without touching this class.

    ``constraints``
        Hard document limits from ``settings.yaml`` (``document_constraints``).
        The page-count ceiling is enforced here — the first point where the
        page count is known.  File-size enforcement happens earlier, in
        ``DocumentSHA256Hasher``.
    """

    def __init__(
        self,
        feature_config: DocumentFeatureExtractionConfig | None = None,
        constraints: DocumentConstraintsConfig | None = None,
    ) -> None:
        self._config = feature_config or DocumentFeatureExtractionConfig()
        self._constraints = constraints or DocumentConstraintsConfig()

    def extract(self, document_path: Path, document_type: DocumentType) -> DocumentFeatureProfile:
        """
        Return the feature profile for *document_path* based on its *document_type*.

        Raises:
            DocumentError: Unsupported format.
            DocumentTooLargeError: Page count exceeds ``constraints.max_pages``.
        """
        extractor = FORMAT_EXTRACTORS.get(document_type)
        if extractor is None:
            raise DocumentError(
                f"Feature extraction is not supported for {document_type.value!r}.",
                context={"path": str(document_path), "document_type": document_type.value},
            )

        profile = extractor(document_path, self._config)

        if profile.page_or_unit_count > self._constraints.max_pages:
            raise DocumentTooLargeError(
                f"Document has {profile.page_or_unit_count} pages, "
                f"which exceeds the configured limit of {self._constraints.max_pages}.",
                context={
                    "path": str(document_path),
                    "page_count": profile.page_or_unit_count,
                    "limit_pages": self._constraints.max_pages,
                },
            )

        return profile
