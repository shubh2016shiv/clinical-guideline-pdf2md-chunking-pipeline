"""
document_identity
=================
Stage 1 · Step 1 of 3 — "What document is this?"

Before the pipeline spends any money or GPU time on a document, it first needs
a stable way to *name* the document and confirm it is a type we can handle.
That is all this sub-package does.

It computes a SHA-256 fingerprint of the file's bytes (streamed in small chunks
so a huge file never has to sit in memory all at once). That fingerprint becomes
the document's permanent job identifier for the rest of the pipeline: the same
file always produces the same id, so re-processing is detectable and outputs are
traceable back to an exact input. It also sniffs the document type (PDF, DOCX,
PPTX, HTML) and rejects files that are too large to process.

The next step, ``feature_extraction``, takes the identified document and looks
inside it to see what it actually contains.
"""

from .document_sha256_hasher import DocumentHashResult, DocumentSHA256Hasher

__all__ = [
    "DocumentSHA256Hasher",
    "DocumentHashResult",
]
