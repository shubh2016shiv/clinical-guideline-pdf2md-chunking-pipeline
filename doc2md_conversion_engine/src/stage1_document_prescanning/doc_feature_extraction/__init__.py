"""
doc_feature_extraction
======================
Deterministic evidence extraction for Stage 1 routing.

This package extracts facts such as table counts, embedded images, vector
objects, captions, and format support.  It does not perform semantic
classification by itself; optional local VLM routing receives only the compact
payload produced here.
"""

from .capability_router import CapabilityBasedEngineRouter
from .extractor import DocumentFeatureExtractor
from .models import (
    DocumentFeatureProfile,
    DocumentRequirements,
    EngineFormatSupport,
    FeatureDocumentType,
    OllamaVisualRoutingDecision,
    OllamaVisualRoutingPayload,
    TableEvidence,
    TextEvidence,
    VisualCandidate,
    VisualCandidateKind,
    VisualEvidence,
)
from .ollama_adjudicator import OllamaAdjudicatorConfig, OllamaVisualRoutingAdjudicator
from .ollama_payload import build_ollama_visual_routing_payload

__all__ = [
    "CapabilityBasedEngineRouter",
    "DocumentFeatureExtractor",
    "DocumentFeatureProfile",
    "DocumentRequirements",
    "EngineFormatSupport",
    "FeatureDocumentType",
    "OllamaAdjudicatorConfig",
    "OllamaVisualRoutingAdjudicator",
    "OllamaVisualRoutingDecision",
    "OllamaVisualRoutingPayload",
    "TableEvidence",
    "TextEvidence",
    "VisualCandidate",
    "VisualCandidateKind",
    "VisualEvidence",
    "build_ollama_visual_routing_payload",
]
