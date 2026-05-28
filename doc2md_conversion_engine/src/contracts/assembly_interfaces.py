"""
contracts/assembly_interfaces.py
=================================
Abstract interfaces every Stage 4 sub-component is built against.

Why interfaces here, not inside Stage 4?
----------------------------------------
Each interface defines a *contract* between the Stage 4 streaming assembler
and one of its collaborators (figure-summary provider, token resolver,
markdown cleaner, output sink). Putting them in ``contracts`` enforces:

1. **Replaceability** — substituting the on-disk flusher for an S3 sink, or
   the polling-based figure provider for an in-memory fake, requires only a
   new implementation of the relevant interface.
2. **Test isolation** — Stage 4 can be exercised end-to-end with pure
   in-memory fakes without importing Stage 3 or touching the filesystem.
3. **Read-side decoupling from Stage 3** — Stage 4 needs *only* the
   read-side of Stage 3 (``get_summary(token)``). Encoding that as an
   abstract interface means Stage 4 cannot accidentally depend on Stage 3's
   producer-side methods.

Each interface is intentionally small: one responsibility, a handful of
methods, behaviour described in docstrings rather than implementation
detail.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .figure_summarization_types import FigureSummary
from .pipeline_domain_types import PageResult


# ---------------------------------------------------------------------------
# Figure summary provider — the read-side view of Stage 3
# ---------------------------------------------------------------------------


class AbstractFigureSummaryProvider(ABC):
    """
    Lookup-only view of the figure summary store.

    Stage 4 uses this to resolve ``${FIG:...}`` tokens. The Stage 3
    orchestrator is the canonical implementation: its ``get_summary`` method
    satisfies this shape exactly.

    Implementations must:

    * Be safe to call concurrently from multiple coroutines.
    * Return ``None`` when the token is not yet resolved (Stage 4 polls).
    * Never block indefinitely — Stage 4 enforces a wall-clock timeout
      around the polling loop, not around a single call.
    """

    @abstractmethod
    async def get_summary(self, token: str) -> FigureSummary | None:
        """Return the summary for ``token`` if available, else ``None``."""


# ---------------------------------------------------------------------------
# Token resolver — per-page substitution policy
# ---------------------------------------------------------------------------


class AbstractTokenResolver(ABC):
    """
    Resolve every token of a specific kind on a single page.

    A resolver owns the *policy* for one token family (figures, tables, …):
    where the replacement text comes from, what to do on miss/timeout, how
    decoratives are handled. The output is a flat mapping the substitution
    engine can apply mechanically.

    A returned ``""`` replacement means "drop the token" — surrounding
    whitespace is collapsed by the cleaner.
    """

    @abstractmethod
    async def resolve_page_tokens(self, page: PageResult) -> dict[str, str]:
        """
        Return ``{token: replacement_text}`` for every token of this kind
        on the given page.

        The returned mapping includes one entry per token *occurrence* the
        resolver decided to handle. Tokens this resolver does not own (e.g.
        ``${TBL:...}`` for a figure resolver) must not appear in the map.
        """


# ---------------------------------------------------------------------------
# Markdown cleaner — post-substitution normalisation
# ---------------------------------------------------------------------------


class AbstractAssembledMarkdownCleaner(ABC):
    """
    Pure-string transform applied after all tokens on a page are substituted.

    No I/O, no state. The cleaner is responsible for cosmetic clean-up
    (collapsing blank-line runs, trimming trailing whitespace) and for
    sweeping any *orphan* tokens the resolvers did not handle so a broken
    upstream contract never leaks into the published document.
    """

    @abstractmethod
    def clean_page(self, page_markdown: str) -> str:
        """Return ``page_markdown`` after normalisation."""


# ---------------------------------------------------------------------------
# Output sink — the only Stage 4 component that touches durable storage
# ---------------------------------------------------------------------------


class AbstractMarkdownOutputSink(ABC):
    """
    Buffered, atomically-published Markdown writer.

    Implementations must guarantee that the reader-visible artefact (the
    final ``.md`` file, an object in object storage, …) is either *complete*
    or *absent* — never half-written. A crash before ``finalize`` must not
    publish a partial document.
    """

    @abstractmethod
    async def append(self, text: str) -> None:
        """Append ``text`` to the in-flight buffer. May flush internally."""

    @abstractmethod
    async def finalize(self) -> Path:
        """
        Flush remaining buffer, publish atomically, and return the path
        (or path-like identifier) of the published artefact.

        Idempotent: calling twice on the same instance must not republish.
        """
