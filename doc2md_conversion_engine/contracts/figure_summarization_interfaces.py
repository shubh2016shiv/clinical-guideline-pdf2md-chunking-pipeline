"""
contracts/figure_summarization_interfaces.py
=============================================
Abstract interfaces every Stage 3 sub-component is built against.

Why interfaces here, not inside Stage 3?
----------------------------------------
Each interface defines a *contract* between the Stage 3 orchestrator and one
of its collaborators (vision client, dedup cache, summary store, work queue).
Putting them in ``contracts`` enforces three architectural properties:

1. **Replaceability** — switching from Ollama to a cloud VLM is a matter of
   writing a new ``AbstractVisionFigureClient`` implementation; no Stage 3
   orchestration code changes.
2. **Test isolation** — alternate implementations (in-memory store, recording
   client, fault-injection cache) can be substituted without monkey-patching.
3. **No leaking concretes** — Stage 4 and the rest of the pipeline never have
   to import Stage 3 modules to talk about a vision client or a summary store.

Each interface is intentionally small: one responsibility, a handful of
methods, and behaviour described in docstrings rather than implementation
detail.  The concrete classes in ``stage3_figure_summarization`` provide the
local-Ollama, JSON-on-disk implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .figure_summarization_types import FigureSummary
from .pipeline_domain_types import Figure


# ---------------------------------------------------------------------------
# Vision client — the model-facing adapter
# ---------------------------------------------------------------------------


class AbstractVisionFigureClient(ABC):
    """
    Adapter to a vision-language model that converts one image into a
    schema-valid :class:`FigureSummary`.

    Pure infrastructure: no knowledge of queues, dedup, persistence, or
    tokens.  Given an image path and a token, return a validated summary.
    The orchestrator owns concurrency, retries, and persistence.

    Implementations must:

    * Be **idempotent** for the same image bytes (deterministic prompts /
      sampling — temperature 0 by default).
    * Raise :class:`FigureSummarizationError` (or a subclass) on any
      unrecoverable failure so the worker pool can apply poison-pill logic
      without inspecting library-specific exception types.
    """

    @abstractmethod
    async def summarize(self, *, image_path: Path, token: str) -> FigureSummary:
        """
        Submit one image to the model and return a validated FigureSummary.

        Parameters
        ----------
        image_path:
            Absolute path to the figure's PNG, as written by Stage 2.
        token:
            The ``${FIG:...}`` placeholder this summary is for; attached to
            the returned ``FigureSummary`` so the orchestrator can persist
            by token without re-deriving it.

        Raises
        ------
        FigureSummarizationError
            For any model / image / validation failure that the caller
            should retry or poison-pill.
        """


# ---------------------------------------------------------------------------
# Deduplication cache — sha256 → FigureSummary
# ---------------------------------------------------------------------------


class AbstractFigureDedupCache(ABC):
    """
    Content-addressed cache of summaries keyed by the image's SHA-256.

    Clinical guidelines reuse the same diagram across sections.  This cache
    ensures the VLM is called **once** per unique image even when that image
    appears under many tokens, and survives across runs so resumed jobs are
    cheap.

    Implementations must be safe to read concurrently from multiple workers;
    a write race that produces the same value twice is acceptable (writes
    are idempotent), but the cache must never silently lose a write that
    appears to have succeeded.
    """

    @abstractmethod
    async def get(self, sha256: str) -> FigureSummary | None:
        """Return the cached summary for this image hash, or None."""

    @abstractmethod
    async def put(self, sha256: str, summary: FigureSummary) -> None:
        """Persist the summary under this image hash."""

    @abstractmethod
    async def contains(self, sha256: str) -> bool:
        """Cheap existence check.  May be implemented in terms of ``get``."""


# ---------------------------------------------------------------------------
# Summary store — token → FigureSummary (the association)
# ---------------------------------------------------------------------------


class AbstractFigureSummaryStore(ABC):
    """
    The deterministic association from figure token to its FigureSummary.

    This is the *load-bearing* store for Stage 4: every ``${FIG:...}``
    placeholder is resolved by looking it up here.  Persistence is required —
    if a worker writes a summary and the process dies, a resume must still
    find that summary by its token.

    Implementations should commit each entry durably (atomic write + fsync
    or equivalent) before returning from ``put``.  Stage 4 reads from this
    store and must see only fully-written entries.
    """

    @abstractmethod
    async def get(self, token: str) -> FigureSummary | None:
        """Return the persisted summary for the given token, or None."""

    @abstractmethod
    async def put(self, summary: FigureSummary) -> None:
        """Persist this summary keyed by its ``token`` field."""

    @abstractmethod
    async def contains(self, token: str) -> bool:
        """Cheap existence check for resume decisions."""

    @abstractmethod
    async def all_tokens(self) -> list[str]:
        """All tokens currently in the store.  Used by metrics / assembly."""


# ---------------------------------------------------------------------------
# Work queue — bounded, async, backpressure
# ---------------------------------------------------------------------------


class AbstractFigureWorkQueue(ABC):
    """
    Bounded async queue of :class:`Figure` items waiting to be summarised.

    The boundedness is the point — when the queue is full, ``put`` blocks
    the producer (the Stage 2 extraction stream) instead of buffering
    unboundedly in RAM.  That is the backpressure that keeps memory flat
    when summarization is slower than extraction (which it usually is on
    a local VLM with thinking enabled).

    Implementations must:

    * Be safe under multiple async consumers (workers) and one or more
      producers (extraction).
    * Provide a graceful close mechanism so workers can terminate after the
      producer signals "no more figures".
    """

    @abstractmethod
    async def put(self, figure: Figure) -> None:
        """Enqueue a figure; blocks when the queue is full (backpressure)."""

    @abstractmethod
    async def get(self) -> Figure | None:
        """
        Dequeue the next figure for a worker, or return ``None`` when the
        producer has closed the queue and no figures remain — the signal
        for workers to exit cleanly.
        """

    @abstractmethod
    async def close(self) -> None:
        """Mark the producer side as done.  Subsequent ``get`` calls drain."""

    @abstractmethod
    def qsize(self) -> int:
        """Current queue depth.  Approximate; for metrics only."""
