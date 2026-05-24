"""
doc_feature_extraction/engine_format_support.py
================================================
Declares which document formats each conversion engine supports.

``DOCLING_SUPPORTED_FORMATS`` is derived from the authoritative extension map
in ``document_format_constants.py`` — adding a new format there automatically
includes it here.  ``MINERU_SUPPORTED_FORMATS`` is declared explicitly because
it reflects an engine constraint (no HTML), not just a recognised extension.
"""

from __future__ import annotations

from ...contracts.document_format_constants import EXTENSION_TO_TYPE
from .models import EngineFormatSupport, FeatureDocumentType

# All formats Docling handles — derived from the authoritative extension map so
# that adding a new format to EXTENSION_TO_TYPE automatically adds it here.
DOCLING_SUPPORTED_FORMATS: frozenset[str] = frozenset(doc_type.value for doc_type in EXTENSION_TO_TYPE.values())

# MinerU does not support HTML; this is an explicit capability declaration and
# cannot be derived from EXTENSION_TO_TYPE — it reflects an engine constraint,
# not just the presence of a recognised extension.
MINERU_SUPPORTED_FORMATS: frozenset[str] = frozenset({"pdf", "docx", "pptx"})


def get_engine_format_support(file_type: FeatureDocumentType) -> EngineFormatSupport:
    """
    Return hard format support for the current in-repo engines.

    This is deliberately separate from quality/capability scoring.  Unsupported
    engines should be removed before any nuanced routing decision happens.
    """
    docling_supported_formats = file_type in DOCLING_SUPPORTED_FORMATS
    mineru_supported_formats = file_type in MINERU_SUPPORTED_FORMATS
    notes: list[str] = []
    if file_type == FeatureDocumentType.HTML:
        notes.append("HTML is routed through Docling; MinerU support is not declared here.")
    return EngineFormatSupport(
        docling_supported=docling_supported_formats,
        mineru_supported=mineru_supported_formats,
        notes=notes,
    )
