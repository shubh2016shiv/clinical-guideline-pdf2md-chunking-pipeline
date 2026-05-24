"""
doc_feature_extraction
======================
Deterministic evidence extraction for Stage 1 document routing.

This package reads a source document (PDF, DOCX, PPTX, HTML) and extracts
factual evidence: table counts, embedded images, vector drawing counts,
caption patterns, and format support flags.  It produces a
``DocumentFeatureProfile`` — a structured, serialisable summary of what the
document contains.

What this package does NOT do
------------------------------
It does not call any model or make any network request.  Engine selection
(the decision of which conversion engine to use) lives in the sibling package
``engine_decision_router``, which consumes the profile produced here.
"""

from .capability_router import CapabilityBasedEngineRouter
from .feature_extraction_entry_point import DocumentFeatureExtractionEntryPoint
from .models import (
    DocumentFeatureProfile,
    DocumentRequirements,
    EngineFormatSupport,
    FeatureDocumentType,
    OllamaVisualRoutingDecision,
    TableEvidence,
    TextEvidence,
    VisualCandidate,
    VisualCandidateKind,
    VisualEvidence,
)

__all__ = [
    "CapabilityBasedEngineRouter",
    "DocumentFeatureExtractionEntryPoint",
    "DocumentFeatureProfile",
    "DocumentRequirements",
    "EngineFormatSupport",
    "FeatureDocumentType",
    "OllamaVisualRoutingDecision",
    "TableEvidence",
    "TextEvidence",
    "VisualCandidate",
    "VisualCandidateKind",
    "VisualEvidence",
]
