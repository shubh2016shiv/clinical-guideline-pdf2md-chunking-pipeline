"""
stage4_assembly_and_output/atomic_markdown_output_flusher.py
=============================================================
Buffered, atomically-published Markdown writer.

Invariants
----------
* The reader-visible ``<job_id>.md`` is either **fully written** or
  **does not exist** — never half-written.  Achieved via the standard
  ``tmp + fsync + os.replace + fsync(dir)`` discipline.
* RAM stays flat regardless of document length.  The in-memory buffer
  flushes to the ``.tmp`` file when it reaches the threshold from
  ``AssemblyConfig.output_flush_threshold_bytes``.
* ``finalize`` is idempotent — calling twice does not republish or raise.

Why the disk I/O is wrapped in ``asyncio.to_thread``
----------------------------------------------------
Stage 4 lives on the asyncio event loop alongside the Stage 3 polling
loop.  Blocking the loop on synchronous ``write`` / ``fsync`` would
serialise figure-summary polling behind disk I/O.  Off-loading to a
worker thread keeps the loop responsive without introducing any
concurrency hazard — the flusher is single-writer by contract (one
streaming assembler owns one flusher).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from ..contracts import AbstractMarkdownOutputSink, AssemblyConfig

logger = logging.getLogger(__name__)


class AtomicMarkdownOutputFlusher(AbstractMarkdownOutputSink):
    """Buffered + atomic Markdown file writer."""

    def __init__(
        self,
        *,
        output_markdown_path: Path,
        assembly_config: AssemblyConfig,
    ) -> None:
        self._final_path = output_markdown_path
        self._tmp_path = output_markdown_path.with_suffix(
            output_markdown_path.suffix + ".tmp"
        )
        self._flush_threshold_bytes = assembly_config.output_flush_threshold_bytes
        self._buffer: bytearray = bytearray()
        self._tmp_initialised = False
        self._finalized = False

    async def append(self, text: str) -> None:
        if self._finalized:
            raise RuntimeError(
                "AtomicMarkdownOutputFlusher.append called after finalize()."
            )
        self._buffer.extend(text.encode("utf-8"))
        if len(self._buffer) >= self._flush_threshold_bytes:
            await self._flush_buffer_to_tmp()

    async def finalize(self) -> Path:
        if self._finalized:
            return self._final_path
        await self._flush_buffer_to_tmp()
        await asyncio.to_thread(self._publish_atomically)
        self._finalized = True
        logger.info(
            "assembled_markdown_published",
            extra={"output_path": str(self._final_path)},
        )
        return self._final_path

    async def _flush_buffer_to_tmp(self) -> None:
        if not self._buffer:
            # Still need to create the tmp file on the first call so that
            # finalize() always has something to rename, even for an empty
            # document.
            if not self._tmp_initialised:
                await asyncio.to_thread(self._initialise_tmp)
            return
        chunk = bytes(self._buffer)
        self._buffer.clear()
        await asyncio.to_thread(self._append_chunk_and_fsync, chunk)

    def _initialise_tmp(self) -> None:
        self._tmp_path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate any leftover from a previous crashed run.
        with open(self._tmp_path, "wb") as fp:
            fp.flush()
            os.fsync(fp.fileno())
        self._tmp_initialised = True

    def _append_chunk_and_fsync(self, chunk: bytes) -> None:
        if not self._tmp_initialised:
            self._initialise_tmp()
        with open(self._tmp_path, "ab") as fp:
            fp.write(chunk)
            fp.flush()
            os.fsync(fp.fileno())

    def _publish_atomically(self) -> None:
        if not self._tmp_initialised:
            # Edge case: finalize called before any append.  Create an empty
            # published file so downstream consumers always see the artefact.
            self._initialise_tmp()
        os.replace(self._tmp_path, self._final_path)
        parent_fd = os.open(str(self._final_path.parent), os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
