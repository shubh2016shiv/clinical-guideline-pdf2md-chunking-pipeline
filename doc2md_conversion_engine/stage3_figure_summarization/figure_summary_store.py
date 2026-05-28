"""
stage3_figure_summarization/figure_summary_store.py
====================================================
Persistent token → :class:`FigureSummary` association — the load-bearing
store for Stage 4.

This is the *only* place the substitution map lives.  Stage 4's
``figure_token_resolver`` reads it; Stage 3's worker pool writes to it.
Persisting per-token means:

* Resume safety — a re-run sees previously-completed tokens as already-done
  without any extra bookkeeping; the existence of the file *is* the
  completion record.
* Deterministic assembly — the same document always assembles identically
  regardless of the order workers finished in, because the map is a stable
  k/v store, not a streaming queue.
* Debuggability — each token's summary is a single small JSON file you can
  ``cat`` to inspect what was substituted into the document.

Layout::

    <summary_store_dir>/
        <token-safe-filename>.json   ← one file per ${FIG:...} token

A token like ``${FIG:abc:042:0}`` is filename-escaped to ``FIG__abc__042__0``
so it round-trips through filesystems that disallow ``$``, ``:``, ``{`` /
``}`` (e.g. Windows-mounted volumes used for inspection).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from ..contracts import AbstractFigureSummaryStore, FigureSummary

logger = logging.getLogger(__name__)


_TOKEN_FILENAME_PATTERN = re.compile(r"[^0-9A-Za-z_-]+")


def _token_to_filename(token: str) -> str:
    """
    Map a figure token to a deterministic, filesystem-safe filename.

    Example: ``${FIG:abcd:042:0}`` → ``FIG__abcd__042__0``.
    The transformation is lossless for our token grammar (alphanumerics +
    ``-``/``_`` survive verbatim; ``$``, ``{``, ``}``, ``:`` collapse to
    ``__``), so two distinct tokens cannot collide.
    """
    return _TOKEN_FILENAME_PATTERN.sub("__", token).strip("_")


class JsonFigureSummaryStore(AbstractFigureSummaryStore):
    """
    File-backed token → FigureSummary store.

    One file per token, atomic write, in-process per-token lock to prevent
    racing writes from a worker and a dedup-cache hit handler for the same
    token (which can happen when the producer enqueues two figures sharing
    a sha256 — both worker tasks resolve to the same image but distinct
    tokens, each requiring its own ``put``).
    """

    _FILE_SUFFIX = ".json"

    def __init__(self, *, store_directory: Path) -> None:
        self._store_directory = store_directory
        self._store_directory.mkdir(parents=True, exist_ok=True)

        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    # ------------------------------------------------------------------
    # AbstractFigureSummaryStore
    # ------------------------------------------------------------------

    async def get(self, token: str) -> FigureSummary | None:
        path = self._path_for(token)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return FigureSummary.model_validate(payload)
        except (OSError, ValueError) as exc:
            logger.warning(
                "stage3.summary_store.corrupt token=%s reason=%s",
                token, type(exc).__name__,
            )
            return None

    async def put(self, summary: FigureSummary) -> None:
        async with await self._lock_for(summary.token):
            self._atomic_write(self._path_for(summary.token), summary)
        logger.debug(
            "stage3.summary_store.put token=%s figure_type=%s",
            summary.token, summary.figure_type.value,
        )

    async def contains(self, token: str) -> bool:
        return self._path_for(token).exists()

    async def all_tokens(self) -> list[str]:
        # Build the inverse map by parsing each persisted file's JSON.  This
        # is rarely on a hot path (metrics/assembly use it once at end-of-job)
        # so the simple implementation is preferred over a side-index.
        tokens: list[str] = []
        for path in self._store_directory.glob(f"*{self._FILE_SUFFIX}"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                token = payload.get("token")
                if isinstance(token, str):
                    tokens.append(token)
            except (OSError, ValueError):
                # Skip unreadable entries here — ``get`` will log them when
                # callers actually try to use them.
                continue
        return tokens

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _path_for(self, token: str) -> Path:
        return self._store_directory / f"{_token_to_filename(token)}{self._FILE_SUFFIX}"

    async def _lock_for(self, token: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(token)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[token] = lock
            return lock

    @staticmethod
    def _atomic_write(target: Path, summary: FigureSummary) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(target)
