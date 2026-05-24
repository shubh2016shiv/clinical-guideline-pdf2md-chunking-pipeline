"""
stage1_document_prescanning
============================
Stage 1 of the doc2md conversion pipeline: zero-cost document intelligence.

Runs once, entirely on CPU, before any GPU is allocated.  In under 2 seconds
for a 500-page document it answers three questions:

1. **What document is this?**
   ``DocumentSHA256Hasher`` streams the file in 1 MB chunks to compute a
   SHA-256 fingerprint and sniffs the document type from its extension or
   magic bytes.  The hex digest becomes the ``ConversionJob.job_id``.

2. **What is on each page?**
   ``DocumentPageStructureScanner`` walks every page with a lightweight,
   format-specific library (pypdfium2 for PDF, python-docx for DOCX,
   python-pptx for PPTX, stdlib html.parser for HTML) and produces a
   ``PageProfile`` per page: five layout numbers that describe the page
   without ever rendering a bitmap or calling a model.

3. **Which engine should process it?**
   ``DocumentComplexityClassifier`` applies a configurable weighted formula
   over all ``PageProfile`` objects to produce an ``EngineClassification``
   that routes the document to Docling (simple), MinerU pipeline (moderate),
   or MinerU VLM (complex).

What this package does NOT do
------------------------------
- It does **not** validate that the file is a supported document type before
  scanning.  That is ``doc_upload.py`` (preflight gate) and
  ``file_upload_management/`` (intake validation).
- It does **not** wire the three modules together into a pipeline sequence.
  That is the orchestrator's responsibility — it calls hasher → scanner →
  classifier in order.
- It does **not** provision workspace directories.  That is
  ``file_upload_management/uploaded_document_staging_store.py``.

The three classes here are pure, independent building blocks.  The orchestrator
composes them.

Public API
----------
The three classes and their result types are the only exports a caller needs::

    from doc2md_conversion_engine.src.stage1_document_prescanning import (
        DocumentSHA256Hasher,
        DocumentHashResult,
        DocumentPageStructureScanner,
        DocumentStructureScanResult,
        DocumentComplexityClassifier,
    )
"""

from .document_complexity_classifier import DocumentComplexityClassifier
from .document_page_structure_scanner import (
    DocumentPageStructureScanner,
    DocumentStructureScanResult,
)
from .document_sha256_hasher import DocumentHashResult, DocumentSHA256Hasher

__all__ = [
    # Hasher
    "DocumentSHA256Hasher",
    "DocumentHashResult",
    # Scanner
    "DocumentPageStructureScanner",
    "DocumentStructureScanResult",
    # Classifier
    "DocumentComplexityClassifier",
]
