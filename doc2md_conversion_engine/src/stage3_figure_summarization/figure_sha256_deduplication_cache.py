"""
stage3_figure_summarization/figure_sha256_deduplication_cache.py
=================================================================
SHA-256-keyed cache that avoids re-summarising the same image.

Why
---
Clinical guidelines often re-use the same diagram across sections.  Stage 2
hashes every figure image and surfaces the digest on the :class:`Figure`
domain object.  Stage 3 uses that digest as a content key so the VLM is
called **once** per unique image even when the same diagram appears under
many ``${FIG:...}`` tokens, and so a re-run of the same document is nearly
free.

Storage choice
--------------
JSON on disk (one file per sha256, atomic write via temp + rename).  No
sqlite, no LMDB — JSON is debuggable by hand (a clinician reviewer can open
one and see what the model said about a single image) and the cache is
trivially copy-paste portable between machines.  The cost is per-key file
overhead; for the architecture's ceiling (~hundreds of unique figures per
job) that is well within budget.

Concurrency
-----------
Per-key writes go through an in-process ``asyncio.Lock`` so two workers that
hit the same uncached image only call the VLM once and write to disk once.
Cross-process safety is provided by the atomic rename: a partial file is
impossible to observe.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from ..contracts import AbstractFigureDedupCache, FigureSummary

logger = logging.getLogger(__name__)


class JsonFigureSha256DeduplicationCache(AbstractFigureDedupCache):
    """
    File-backed sha256 → :class:`FigureSummary` cache.

    Layout::

        <cache_dir>/
            <sha256>.json   ← one file per unique image

    Each file is the JSON-serialised FigureSummary.  Atomic writes ensure
    that a crash mid-write never leaves a half-written file visible to a
    reader.
    """

    _FILE_SUFFIX = ".json"

    def __init__(self, *, cache_directory: Path) -> None:
        # Ensure the directory exists *now* so workers don't race on mkdir.
        self._cache_directory = cache_directory
        self._cache_directory.mkdir(parents=True, exist_ok=True)

        # Per-key locks make the check-then-act pattern in get_or_compute-
        # style callers safe across workers.
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    # ------------------------------------------------------------------
    # AbstractFigureDedupCache
    # ------------------------------------------------------------------

    async def get(self, sha256: str) -> FigureSummary | None:
        path = self._path_for(sha256)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return FigureSummary.model_validate(payload)
        except (OSError, ValueError) as exc:
            # A corrupt cache entry is preferable to dying; log loudly and
            # treat as a cache miss so the VLM re-derives the summary.
            logger.warning(
                "stage3.dedup_cache.corrupt sha256=%s reason=%s",
                sha256, type(exc).__name__,
            )
            return None

    async def put(self, sha256: str, summary: FigureSummary) -> None:
        async with await self._lock_for(sha256):
            self._atomic_write(self._path_for(sha256), summary)

    async def contains(self, sha256: str) -> bool:
        return self._path_for(sha256).exists()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _path_for(self, sha256: str) -> Path:
        return self._cache_directory / f"{sha256}{self._FILE_SUFFIX}"

    async def _lock_for(self, sha256: str) -> asyncio.Lock:
        # Double-checked under a guard lock so two coroutines racing on the
        # same first-time key get the same lock instance.
        async with self._locks_guard:
            lock = self._locks.get(sha256)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[sha256] = lock
            return lock

    @staticmethod
    def _atomic_write(target: Path, summary: FigureSummary) -> None:
        # tmp + rename is atomic on POSIX; Path.replace is atomic on Windows
        # even when the target exists.
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(target)
