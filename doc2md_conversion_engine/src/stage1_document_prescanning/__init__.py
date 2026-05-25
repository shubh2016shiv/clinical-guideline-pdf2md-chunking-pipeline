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
   deterministically from the extracted structural requirements: it promotes to
   MinerU only on hard evidence (multi-column layout, complex tables, missing
   text layer) and otherwise confirms Docling.

Why deterministic routing instead of a model?
----------------------------------------------
Routing is decided entirely from structural facts extracted in Stage 1, so the
same document always routes the same way, the reason names the exact signal that
fired, and no patient data leaves the process for an inference call.  The
signals (XML structure, table geometry, text-block layout) are cheap to read in
the same pass that already extracts feature evidence.
"""

from .doc_feature_extraction import (
    CapabilityBasedEngineRouter,
    DocumentFeatureExtractionEntryPoint,
    DocumentFeatureProfile,
)
from .document_sha256_hasher import DocumentHashResult, DocumentSHA256Hasher

__all__ = [
    # Hasher
    "DocumentSHA256Hasher",
    "DocumentHashResult",
    # Feature extraction + deterministic routing
    "CapabilityBasedEngineRouter",
    "DocumentFeatureExtractionEntryPoint",
    "DocumentFeatureProfile",
]
