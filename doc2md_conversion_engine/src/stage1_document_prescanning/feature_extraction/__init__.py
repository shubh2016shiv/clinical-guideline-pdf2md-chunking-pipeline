"""
feature_extraction
===================
Stage 1 · Step 2 of 3 — "What is actually inside this document?"

Once a document has been identified, this sub-package opens it and gathers plain,
factual evidence about its structure WITHOUT trying to convert it yet. Think of
it as a quick X-ray, not surgery: how many pages or slides, is there real
selectable text or only scanned images, how many tables and how complicated are
they, is the page laid out in multiple columns, are there figures and charts.

Every piece of that evidence is recorded in a single ``DocumentFeatureProfile``
object — a structured, serialisable summary that the next step reads to make its
decision. No model is called and no network request is made here; everything is
read directly from the file format.

How the pieces fit together:

    document_feature_extractor.py   The single front door. You hand it any
                                    supported document and it hands back one
                                    DocumentFeatureProfile. Internally it picks
                                    the right reader for the file's format.

    format_extractors/              One reader per format (PDF, DOCX, PPTX,
                                    HTML). Each knows the quirks of its own
                                    format and nothing about the others.

    feature_evidence_models.py      The vocabulary: the data shapes used to
                                    record the evidence (tables, text, layout,
                                    visuals) and the final profile.

    visual_caption_detector.py      A small shared helper that recognises figure
                                    and chart captions in text, used by the
                                    readers to flag meaningful visuals.

The next step, ``engine_routing``, reads the profile produced here and decides
which conversion engine should process the document.
"""

# The evidence models are pure data with no dependencies, so importing them here
# is always safe. They are imported eagerly because the sibling ``engine_routing``
# package depends on them — keeping this import light is what lets the two
# packages reference each other without an import deadlock.
from .feature_evidence_models import (
    DocumentFeatureProfile,
    DocumentRequirements,
    EngineFormatSupport,
    FeatureDocumentType,
    LayoutEvidence,
    TableEvidence,
    TextEvidence,
    VisualCandidate,
    VisualCandidateKind,
    VisualEvidence,
)

__all__ = [
    "DocumentFeatureExtractor",
    "DocumentFeatureProfile",
    "DocumentRequirements",
    "EngineFormatSupport",
    "FeatureDocumentType",
    "LayoutEvidence",
    "TableEvidence",
    "TextEvidence",
    "VisualCandidate",
    "VisualCandidateKind",
    "VisualEvidence",
]


def __getattr__(name: str):
    """
    Expose ``DocumentFeatureExtractor`` on the package, but load it lazily.

    Why this is not a plain top-level import:
    The dispatcher pulls in the per-format readers, and those readers call into
    the ``engine_routing`` package to fill in each document's routing
    requirements. ``engine_routing`` in turn imports the evidence models from
    THIS package. If we imported the dispatcher eagerly at the top of this file,
    those two packages would chase each other in a circle while neither has
    finished loading, and Python would raise an ImportError.

    Loading it on first access instead means both packages are fully initialised
    by the time anyone actually asks for ``DocumentFeatureExtractor``, so the
    circle never forms. Callers still simply write
    ``from ...feature_extraction import DocumentFeatureExtractor`` — the laziness
    is invisible to them.
    """
    if name == "DocumentFeatureExtractor":
        from .document_feature_extractor import DocumentFeatureExtractor

        return DocumentFeatureExtractor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
