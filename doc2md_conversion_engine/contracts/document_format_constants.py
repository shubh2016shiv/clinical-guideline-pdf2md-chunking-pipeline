"""
contracts/document_format_constants.py
======================================
Single source of truth for supported document extensions and magic-byte
signatures.  Imported by both ``DocumentUploadIntake`` (preflight validation)
and ``DocumentSHA256Hasher`` (type detection) so that adding a new format
requires editing only this file.
"""

from __future__ import annotations

from .pipeline_domain_types import DocumentType

# ---------------------------------------------------------------------------
# File extensions recognised by the pipeline (lowercase, including leading dot).
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".pptx", ".html", ".htm"})

# ---------------------------------------------------------------------------
# Extension → DocumentType mapping (used by the hasher for type detection).
# ---------------------------------------------------------------------------
EXTENSION_TO_TYPE: dict[str, DocumentType] = {
    ".pdf": DocumentType.PDF,
    ".docx": DocumentType.DOCX,
    ".pptx": DocumentType.PPTX,
    ".html": DocumentType.HTML,
    ".htm": DocumentType.HTML,
}

# ---------------------------------------------------------------------------
# Magic-byte signatures for files without a recognised extension.
# Each entry is (lowercase_prefix_bytes, DocumentType).
# ZIP magic (PK\x03\x04) covers both DOCX and PPTX; extension is authoritative
# for distinguishing those two — ZIP magic falls back to DOCX.
# ---------------------------------------------------------------------------
MAGIC_SIGNATURES: list[tuple[bytes, DocumentType]] = [
    (b"%pdf-", DocumentType.PDF),
    (b"pk\x03\x04", DocumentType.DOCX),
    (b"<!doctype html", DocumentType.HTML),
    (b"<html", DocumentType.HTML),
]

# Longest signature above is 14 bytes; read 16 for a small safety margin.
MAGIC_READ_BYTES: int = 16
