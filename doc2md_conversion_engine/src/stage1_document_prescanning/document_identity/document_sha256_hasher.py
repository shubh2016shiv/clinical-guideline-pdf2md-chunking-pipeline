"""
stage1_document_prescanning/document_identity/document_sha256_hasher.py
=======================================================================
Stage 1 · Step 1 of 3 — fingerprint the document and work out its type.

This is the very first thing that happens to a document. Before we look inside
it or decide anything, we give it a stable name and confirm we can handle it.

Responsibilities
----------------
1. Validate the document (exists, readable, non-empty, within size limit).
2. Detect the document type from the file extension (primary) or magic bytes
   (fallback for extension-less or misnamed files).
3. Stream the file in 1 MB chunks to compute a SHA-256 digest without ever
   loading more than ~1 MB into RAM — even for a 200 MB PPTX.

The returned ``DocumentHashResult.sha256_hex`` becomes ``ConversionJob.job_id``,
which is the primary key for the whole pipeline run:
  - checkpoint filename on disk:  ``{job_id}.json``
  - figure token doc_id segment:  ``${FIG:<job_id>:<page>:<index>}``
  - deduplication cache lookup key

Why SHA-256 and not UUID?
    Content-addressed identity means two uploads of the same file produce the
    same job_id.  The pipeline can return a cached result without reprocessing,
    and renaming the file on disk does not create a new job.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ...contracts.configurations.pipeline_config import DocumentConstraintsConfig
from ...contracts.document_format_constants import (
    EXTENSION_TO_TYPE,
    MAGIC_READ_BYTES,
    MAGIC_SIGNATURES,
)
from ...contracts.exceptions import DocumentError, DocumentTooLargeError
from ...contracts.pipeline_domain_types import DocumentType

# Read the file in 1 MB chunks so peak RAM stays bounded at ~1 MB regardless
# of how large the source document is (200 MB PPTX, 50 MB image-heavy PDF, etc.)
_CHUNK_SIZE_BYTES: int = 1 * 1024 * 1024


@dataclass(frozen=True)
class DocumentHashResult:
    """
    Output produced by ``DocumentSHA256Hasher.compute()``.

    All three values flow into ``ConversionJob`` at pipeline startup:
      - ``sha256_hex``      → ``ConversionJob.job_id``
      - ``document_type``   → ``ConversionJob.document_type``
      - ``file_size_bytes`` → logged in the pipeline start event
    """

    sha256_hex: str
    """64-character lowercase hexadecimal SHA-256 digest of the file's raw bytes."""

    document_type: DocumentType
    """Format detected from the file extension or magic bytes."""

    file_size_bytes: int
    """Size of the source file in bytes at the time of hashing."""


class DocumentSHA256Hasher:
    """
    Validates a source document, sniffs its type, and computes its SHA-256 hash.

    Instantiate once per pipeline run with the configured constraints::

        hasher = DocumentSHA256Hasher(config.document_constraints)
        result = hasher.compute(Path("/uploads/Headache.pdf"))
        # result.sha256_hex  → "e3b0c44298fc1c14..."
        # result.document_type → DocumentType.PDF
    """

    def __init__(self, constraints: DocumentConstraintsConfig) -> None:
        self._max_file_size = constraints.max_file_size_bytes

    def compute(self, document_path: Path) -> DocumentHashResult:
        """
        Validate the document, detect its type, and return its SHA-256 hash.

        The file is read exactly once (streaming, 1 MB at a time) for hashing.
        Validation checks are performed before the full read to fail as cheaply
        as possible.

        Args:
            document_path: Absolute path to the source document.

        Returns:
            ``DocumentHashResult`` containing the hex digest, type, and size.

        Raises:
            DocumentError: File not found, not a regular file, unreadable,
                empty (0 bytes), or of an unrecognised format.
            DocumentTooLargeError: File size exceeds ``max_file_size_bytes``.
        """
        self._validate(document_path)
        document_type = self._detect_type(document_path)
        sha256_hex = self._hash_chunked(document_path)
        return DocumentHashResult(
            sha256_hex=sha256_hex,
            document_type=document_type,
            file_size_bytes=document_path.stat().st_size,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate(self, path: Path) -> None:
        """Run all pre-hash checks; raise on the first failure."""
        if not path.exists():
            raise DocumentError(
                f"Document not found: {path}",
                context={"path": str(path)},
            )
        if not path.is_file():
            raise DocumentError(
                f"Path is not a regular file: {path}",
                context={"path": str(path)},
            )

        # Read the first byte to confirm read permission before the full hash pass.
        try:
            with path.open("rb") as fh:
                first_byte = fh.read(1)
        except PermissionError as exc:
            raise DocumentError(
                f"Permission denied reading document: {path}",
                context={"path": str(path)},
            ) from exc

        if not first_byte:
            raise DocumentError(
                f"Document is empty (0 bytes): {path}",
                context={"path": str(path)},
            )

        size = path.stat().st_size
        if size > self._max_file_size:
            raise DocumentTooLargeError(
                f"Document size {size:,} bytes exceeds the configured limit "
                f"of {self._max_file_size:,} bytes ({self._max_file_size // (1024**2)} MB)",
                context={
                    "path": str(path),
                    "file_size_bytes": size,
                    "limit_bytes": self._max_file_size,
                },
            )

    def _detect_type(self, path: Path) -> DocumentType:
        """
        Identify the document type.

        Extension is checked first because it is cheap and usually correct.
        Magic bytes are used as a fallback for files with missing or non-standard
        extensions (e.g., a PDF served without a ``.pdf`` suffix).
        """
        suffix = path.suffix.lower()
        if suffix in EXTENSION_TO_TYPE:
            return EXTENSION_TO_TYPE[suffix]

        # Extension not recognised — inspect the first bytes of the file.
        with path.open("rb") as fh:
            header = fh.read(MAGIC_READ_BYTES)

        # Case-insensitive match for HTML headers which may be mixed-case.
        header_lower = header.lower()
        for magic, doc_type in MAGIC_SIGNATURES:
            if header_lower.startswith(magic.lower()):
                return doc_type

        raise DocumentError(
            f"Unrecognised document format: {path.name!r} "
            f"(extension {suffix!r} is not supported; "
            f"supported: .pdf, .docx, .pptx, .html, .htm)",
            context={"path": str(path), "extension": suffix},
        )

    def _hash_chunked(self, path: Path) -> str:
        """
        Stream the file through SHA-256 in 1 MB chunks.

        Peak RAM at any moment: ~1 MB (the current chunk) regardless of file size.
        The walrus operator ``chunk := fh.read(...)`` reads until EOF returns b"".
        """
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            while chunk := fh.read(_CHUNK_SIZE_BYTES):
                digest.update(chunk)
        return digest.hexdigest()
