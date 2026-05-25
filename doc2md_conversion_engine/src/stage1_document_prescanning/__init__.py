"""
stage1_document_prescanning
============================
Stage 1 of the doc2md conversion pipeline: low-cost document intelligence.

Runs once before any conversion engine is allocated.  It answers three
questions:

1. **What document is this?**
   ``DocumentSHA256Hasher`` streams the file in 1 MB chunks to compute a
   SHA-256 fingerprint and sniffs the document type from its extension or
   magic bytes.  The hex digest becomes the ``ConversionJob.job_id``.

2. **What structural evidence does the document contain?**
   ``DocumentFeatureExtractionEntryPoint`` collects deterministic evidence
   from the source format: text availability, tables, embedded images, vector
   graphics, captions, visual candidates, and hard engine format support.

3. **Which engine should process it?**
   ``CapabilityBasedEngineRouter`` chooses the cheapest sufficient engine
   from the extracted requirements.  For documents with meaningful visuals,
   ``EngineRoutingAgent`` asks a local Ollama model to adjudicate before the
   final decision is made.

Why no threshold-based complexity scoring?
------------------------------------------
Earlier versions used ``DocumentPageStructureScanner`` + ``DocumentComplexityClassifier``
to score documents against hand-tuned numeric thresholds.  This approach is
not scalable: thresholds that work for simple clinical guidelines break on
research papers, multi-column PDFs, or any document type outside the calibration
set.  A local VLM (``EngineRoutingAgent``) generalises across the full spectrum
of document complexity without requiring manual threshold maintenance.
"""

from .doc_feature_extraction import (
    CapabilityBasedEngineRouter,
    DocumentFeatureExtractionEntryPoint,
    DocumentFeatureProfile,
)
from .document_sha256_hasher import DocumentHashResult, DocumentSHA256Hasher
from .engine_decision_router import EngineRoutingAgent

__all__ = [
    # Hasher
    "DocumentSHA256Hasher",
    "DocumentHashResult",
    # Feature extraction
    "CapabilityBasedEngineRouter",
    "DocumentFeatureExtractionEntryPoint",
    "DocumentFeatureProfile",
    # Engine routing
    "EngineRoutingAgent",
]
