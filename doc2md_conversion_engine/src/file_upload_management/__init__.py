"""
file_upload_management
======================
Pre-pipeline document upload management layer.

Runs BEFORE ``stage1_document_prescanning`` (layout scanning + complexity
classification).  This layer has two modules:

1. **Preflight validation** — ``DocumentUploadIntake``
   Stat-only gate (< 1 ms) that confirms a file exists, is non-empty,
   is within the size limit, and has a supported extension or magic bytes.
   Called directly by the API / CLI / file-picker as the entry-point gate.
   Rejects .jpg, .txt, folders, and other non-document inputs.

2. **Workspace provisioning** — ``UploadedDocumentStagingStore``
   Creates ``doc_assets/<job_id>/output/`` on disk once the SHA-256
   job_id is known.  Idempotent — safe to call on resume after a crash.

Neither module does any streaming, model loading, or external I/O beyond
a single ``os.stat()`` and one ``mkdir -p``.

What this layer does NOT do
----------------------------
- It does **not** copy the source file into ``doc_assets/``.
- It does **not** scan pages or classify complexity.
  That is ``stage1_document_prescanning/``'s responsibility.
- It does **not** perform SHA-256 hashing.
  The hasher lives in ``stage1_document_prescanning/`` and is called
  by the ingest-orchestrator, not by this layer.
"""

from .document_upload_intake import DocumentUploadIntake
from .uploaded_document_staging_store import UploadedDocumentStagingStore

__all__ = [
    "DocumentUploadIntake",
    "UploadedDocumentStagingStore",
]
