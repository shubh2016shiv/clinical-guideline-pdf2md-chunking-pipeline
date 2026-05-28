"""
stage1_document_prescanning/feature_extraction/document_feature_extractor.py
============================================================================
Stage 1 · Step 2 of 3 — the single front door to feature extraction.

This is the one place the rest of the pipeline calls to learn what is inside a
document. You hand it a file and its type; it hands back one
``DocumentFeatureProfile``. The fact that PDFs, Word files, PowerPoint, and HTML
each need a completely different reader is hidden behind this door — callers
never have to know which reader ran.

How it works is simple: it keeps a small lookup table from document type to the
matching reader function, picks the right one, runs it, and returns the result.
Adding a new format later means adding one reader and one entry in that table.

Where document limits are enforced
----------------------------------
The page-count limit is checked here because this is the first moment in the
whole pipeline where we actually know how many pages a document has. (The
file-size limit is checked even earlier, while fingerprinting the file, for the
same reason — enforce each limit at the first point its information exists.)
"""

from __future__ import annotations

from pathlib import Path

from ...contracts.configurations.pipeline_config import (
    DocumentConstraintsConfig,
    DocumentFeatureExtractionConfig,
)
from ...contracts.exceptions import DocumentError, DocumentTooLargeError
from ...contracts.pipeline_domain_types import DocumentType
from .feature_evidence_models import DocumentFeatureProfile
from .format_extractors.docx_feature_extractor import extract_docx_features
from .format_extractors.html_feature_extractor import extract_html_features
from .format_extractors.pdf_feature_extractor import extract_pdf_features
from .format_extractors.pptx_feature_extractor import extract_pptx_features

# Maps each accepted document type to the function that extracts its features.
# All extractor functions share the same signature:
#   (path: Path, config: DocumentFeatureExtractionConfig | None) -> DocumentFeatureProfile
FORMAT_EXTRACTORS = {
    DocumentType.PDF: extract_pdf_features,
    DocumentType.DOCX: extract_docx_features,
    DocumentType.PPTX: extract_pptx_features,
    DocumentType.HTML: extract_html_features,
}


class DocumentFeatureExtractor:
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
        Look inside one document and return everything we measured about it.

        Three steps: pick the reader that matches the document's type, run it to
        get the feature profile, then check the document is not larger than the
        configured page limit before letting it continue into expensive Stage 2
        work.

        Raises:
            DocumentError: the format has no reader (we cannot process it).
            DocumentTooLargeError: it has more pages than ``constraints.max_pages``.
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
