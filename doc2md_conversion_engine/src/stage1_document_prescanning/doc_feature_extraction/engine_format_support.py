"""
doc_feature_extraction/engine_format_support.py
================================================
Declares which document formats each conversion engine supports.

Both constants are intentionally explicit, independent declarations.  They
must NOT be derived from ``document_format_constants.EXTENSION_TO_TYPE``.

``EXTENSION_TO_TYPE`` answers: "which file extensions does the intake layer
recognise?"  That is a different question from "which formats can this engine
process?"  Deriving one from the other couples intake recognition to engine
capability — adding a new extension for intake purposes (e.g. to give a
cleaner rejection message for an unsupported format) would silently alter
engine routing without any engine actually gaining that capability.

Adding a new format here is a deliberate, separate act from adding it to the
intake layer.  Both should be updated consciously, but neither should imply
the other.
"""

from __future__ import annotations

from .models import EngineFormatSupport, FeatureDocumentType

# Docling supports all four formats accepted by this pipeline.
# Declared explicitly — not derived from EXTENSION_TO_TYPE — so that
# extending the intake layer does not silently change routing support.
DOCLING_SUPPORTED_FORMATS: frozenset[str] = frozenset({"pdf", "docx", "pptx", "html"})

# MinerU does not support HTML.  Declared explicitly for the same reason as
# above: engine capability is a separate concern from intake recognition.
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
