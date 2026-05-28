"""
file_upload_management/uploaded_document_staging_store.py
==========================================================
Provision and manage per-job workspace directories under ``doc_assets/``.

Responsibility
--------------
For every document that clears intake validation, create an isolated, named
directory on disk so all downstream pipeline stages have a dedicated location
to write into.

Workspace layout
----------------
::

    doc_assets/
    └── <job_id>/                   ← one directory per document (SHA-256 hex)
        └── output/                 ← Stage 2 page markdown + figure PNGs

The ``<job_id>/`` wrapper keeps the root uncluttered and leaves room for
sibling directories that future tooling may need (logs, debug artefacts, etc.)
without requiring a schema migration.

Why the job_id is the directory name
-------------------------------------
``job_id`` is the SHA-256 hex of the document's raw bytes, computed by
``DocumentSHA256Hasher``.  Using content-addressed naming means:

  - Two uploads of the same file map to the same workspace — pipeline can
    return a cached result without reprocessing.
  - Renaming the file on disk does not create a new workspace.
  - ``provision()`` is fully idempotent: a crash-and-resume re-provisions
    the same path without raising.
"""

from __future__ import annotations

from pathlib import Path

from ..contracts.configurations.pipeline_config import DocumentStorageConfig
from ..contracts.exceptions import DocumentError


class UploadedDocumentStagingStore:
    """
    Provisions the on-disk workspace for a conversion job.

    Instantiate once with the storage configuration::

        store = UploadedDocumentStagingStore(config.storage)
        output_dir = store.provision("e3b0c44298fc1c14...")
        # → /abs/path/to/doc_assets/e3b0c44298fc1c14.../output/
    """

    def __init__(self, storage_config: DocumentStorageConfig) -> None:
        # Resolve to an absolute path at construction time so every caller
        # receives the same absolute path regardless of cwd drift.
        self._doc_assets_root = Path(storage_config.doc_assets_dir).resolve()

    def provision(self, job_id: str) -> Path:
        """
        Create ``<doc_assets_root>/<job_id>/output/`` and return its path.

        Idempotent: calling with the same ``job_id`` twice returns the existing
        directory without error.  The orchestrator may call this on resume after
        a crash without needing to detect whether the workspace already exists.

        Args:
            job_id: SHA-256 hex digest of the source document, from
                    ``DocumentHashResult.sha256_hex``.

        Returns:
            Absolute ``Path`` to the ``output/`` subdirectory.  Guaranteed to
            exist on disk when this method returns.

        Raises:
            DocumentError: Workspace could not be created due to a filesystem
                           permission error.
        """
        output_dir = self._doc_assets_root / job_id / "output"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise DocumentError(
                f"Cannot create job workspace at {output_dir}: permission denied.",
                context={"output_dir": str(output_dir), "job_id": job_id},
            ) from exc
        return output_dir

    @property
    def doc_assets_root(self) -> Path:
        """Absolute path to the ``doc_assets`` root directory."""
        return self._doc_assets_root
