"""
file_upload_management/document_upload_intake.py
=================================================
Pre-pipeline gate: validate an uploaded document before any hashing, scanning,
or workspace creation begins.

Responsibility
--------------
Perform the cheapest possible checks at the boundary where a document enters
the system.  Every check uses only ``os.stat()`` or a 16-byte magic-byte read
— no streaming, no library parsing, no significant memory allocation.

A document that passes intake is guaranteed to:
  - Exist on disk as a regular file.
  - Be non-empty (at least 1 byte).
  - Fall within the configured file-size ceiling.
  - Have a recognised extension or magic-byte signature.

These checks complete in under 1 ms even for a 200 MB file, because no content
is streamed.  They catch obviously invalid inputs before the pipeline allocates
any state.

Callers
-------
Called directly by the API / CLI / file-picker as the preflight gate::

    intake = DocumentUploadIntake(config.document_constraints)

    # Validate — raises on failure:
    intake.validate(user_selected_path)

    # Or check without raising (useful for UI feedback):
    if intake.is_supported(user_selected_path):
        ...

Why validation happens here AND in DocumentSHA256Hasher
--------------------------------------------------------
The hasher streams the entire file to compute the SHA-256 fingerprint — a
100 ms–1.5 s operation depending on file size.  The intake is a < 1 ms gate
that rejects junk at the API boundary without touching file contents at all.
Both modules validate, but at different cost tiers:
  - Intake:  stat-only, runs at the upload boundary    (< 1 ms)
  - Hasher:  streaming, runs as the first step of Stage 1  (100 ms – 1.5 s)
"""

from __future__ import annotations

from pathlib import Path

from ..contracts.configurations.pipeline_config import DocumentConstraintsConfig
from ..contracts.document_format_constants import (
    MAGIC_READ_BYTES,
    MAGIC_SIGNATURES,
    SUPPORTED_EXTENSIONS,
)
from ..contracts.exceptions import DocumentError, DocumentTooLargeError


class DocumentUploadIntake:
    """
    Lightweight gate that rejects invalid documents before any pipeline work starts.

    Instantiate once with the document constraints from the pipeline config::

        intake = DocumentUploadIntake(config.document_constraints)
        intake.validate(Path("/path/to/document.<ext>"))
        # returns None on success
        # raises DocumentError or DocumentTooLargeError on invalid input
    """

    def __init__(self, constraints: DocumentConstraintsConfig) -> None:
        self._max_file_size = constraints.max_file_size_bytes

    # -- public API -------------------------------------------------------

    def validate(self, document_path: Path) -> None:
        """
        Assert the document is present, non-empty, within size limits, and of
        a recognised format.

        Checks run in order of increasing cost so the pipeline fails as cheaply
        as possible:
          1. File presence and type  (single ``os.stat()`` call)
          2. File size               (reuses the stat result)
          3. Format                  (extension lookup, or 16-byte magic read)

        Args:
            document_path: Path to the document on disk.

        Raises:
            DocumentError: File not found, not a regular file, unreadable,
                           empty (0 bytes), or of an unsupported format.
            DocumentTooLargeError: File exceeds ``max_file_size_bytes``.

        Returns:
            ``None`` — success means the document is eligible for ingestion.
        """
        self._check_path(document_path)
        self._check_size(document_path)
        self._check_format(document_path)

    def is_supported(self, document_path: Path) -> bool:
        """
        Return ``True`` if *document_path* passes all preflight checks.

        Convenience method for UI code that wants a boolean (e.g. to grey
        out an "Upload" button) rather than catching an exception.

        Args:
            document_path: Path selected by the user.

        Returns:
            ``True`` if the file exists, is a regular file, is non-empty,
            is within the size limit, and has a supported format.
            ``False`` for any preflight failure.
        """
        try:
            self.validate(document_path)
            return True
        except DocumentError:
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_path(self, path: Path) -> None:
        """Verify the file exists, is a regular file, and is non-empty."""
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
        if path.stat().st_size == 0:
            raise DocumentError(
                f"Document is empty (0 bytes): {path}",
                context={"path": str(path)},
            )

    def _check_size(self, path: Path) -> None:
        """Reject documents that exceed the configured file-size ceiling."""
        size = path.stat().st_size
        if size > self._max_file_size:
            raise DocumentTooLargeError(
                f"Document {path.name!r} is {size:,} bytes — exceeds the "
                f"configured limit of {self._max_file_size:,} bytes "
                f"({self._max_file_size // (1024**2)} MB).",
                context={
                    "path": str(path),
                    "file_size_bytes": size,
                    "limit_bytes": self._max_file_size,
                },
            )

    def _check_format(self, path: Path) -> None:
        """
        Confirm the file has a supported extension.  For extension-less or
        misnamed files, fall back to a 16-byte magic-byte inspection.

        Raises:
            DocumentError: Neither check identifies a supported document format.
        """
        suffix = path.suffix.lower()
        if suffix in SUPPORTED_EXTENSIONS:
            return

        # Extension not recognised — inspect the first bytes of the file.
        try:
            with path.open("rb") as fh:
                header = fh.read(MAGIC_READ_BYTES).lower()
        except PermissionError as exc:
            raise DocumentError(
                f"Permission denied reading document: {path}",
                context={"path": str(path)},
            ) from exc

        for magic, _ in MAGIC_SIGNATURES:
            if header.startswith(magic):
                return

        raise DocumentError(
            f"Unsupported document format: {path.name!r} "
            f"(extension {suffix!r} is not supported; "
            f"accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))})",
            context={"path": str(path), "extension": suffix},
        )
