"""
stage1_document_prescanning/engine_routing/engine_format_compatibility.py
=========================================================================
Stage 1 · Step 3 of 3 (part 2) — which engines can even open this format.

Before deciding WHICH engine is best, the routing policy first needs the hard
facts about which engines can open the file format at all. This file is that
lookup table: Docling can read all four formats we accept; MinerU can read
everything except HTML.

Why these lists are written out by hand instead of derived
----------------------------------------------------------
There is another list elsewhere (``EXTENSION_TO_TYPE``) that answers a DIFFERENT
question: "which file extensions does the intake layer recognise?" That is about
what we will accept from a user, not about what an engine can process. It is
tempting to reuse it here, but doing so would tie the two together: someone
adding a new extension just to give a nicer rejection message would silently and
accidentally change engine routing. So engine capability is declared separately
and on purpose. Adding a format here is a deliberate decision, made on its own.
"""

from __future__ import annotations

from ..feature_extraction.feature_evidence_models import EngineFormatSupport, FeatureDocumentType

# Docling supports all four formats accepted by this pipeline.
# Declared explicitly — not derived from EXTENSION_TO_TYPE — so that
# extending the intake layer does not silently change routing support.
DOCLING_SUPPORTED_FORMATS: frozenset[str] = frozenset({"pdf", "docx", "pptx", "html"})

# MinerU does not support HTML.  Declared explicitly for the same reason as
# above: engine capability is a separate concern from intake recognition.
MINERU_SUPPORTED_FORMATS: frozenset[str] = frozenset({"pdf", "docx", "pptx"})


def get_engine_format_compatibility(file_type: FeatureDocumentType) -> EngineFormatSupport:
    """
    Report which engines can open this document's format.

    Returns a small object with two yes/no answers (can Docling open it? can
    MinerU open it?) plus any notes worth logging. The routing policy calls this
    first and drops any engine that cannot open the format, so the later "which
    is best?" reasoning never has to second-guess basic compatibility.
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
