"""
stage4_assembly_and_output/table_fragment_buffer.py
====================================================
Cross-page table assembly state.

Clinical PDFs frequently have tables that begin on page N (header + first
body rows) and continue on page N+1, N+2, … with header-less continuation
rows.  Stage 2 emits each piece as a ``Table`` with ``is_fragment=True``
and a shared ``start_page``; the *final* piece arrives with
``is_fragment=False`` carrying ``start_page`` pointing at the original
header page.

Stage 4 must merge them before substitution.  The buffer here owns the
"open table" state — keyed by ``start_page`` so multiple distinct tables
in flight at once never collide.

Anchoring choice (and why)
--------------------------
The merged Markdown is anchored on the **closing-page token** — the
``${TBL:...}`` token attached to the non-fragment piece that closed the
table.  Reasons:

1. **Streaming-friendly:** earlier pages have already been written and
   cannot be edited.  Anchoring on a future page (the start page) would
   require buffering every page until the table closes.
2. **Predictable reading order:** the reader meets the table where the
   PDF rendered the *last* row, which is also where the natural
   "continued from page N" caption usually sits.
3. **Earlier-page tokens are erased** — replaced by the empty string so
   the table's split appearance does not survive into the final
   Markdown.  The dropped-token whitespace handling in
   :class:`TokenSubstitutionEngine` collapses the residual gap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..contracts import Table

logger = logging.getLogger(__name__)


@dataclass
class _OpenTableFragmentChain:
    """All the pieces of one in-flight multi-page table, ordered by arrival."""

    start_page: int
    pieces: list[Table] = field(default_factory=list)

    def append(self, fragment: Table) -> None:
        self.pieces.append(fragment)

    def merge_into_markdown(self, closing_piece: Table) -> str:
        # Concatenate header + continuation rows.  Each ``Table.markdown``
        # already contains GFM-formatted rows; we join with a single newline
        # so adjacent fragments do not introduce a blank row inside the
        # table.  The closing piece is appended last regardless of arrival
        # order so the final renderer sees a well-formed table.
        parts = [piece.markdown for piece in self.pieces]
        parts.append(closing_piece.markdown)
        return "\n".join(part.rstrip("\n") for part in parts)

    def all_fragment_tokens(self) -> list[str]:
        return [piece.token for piece in self.pieces]


class TableFragmentBuffer:
    """
    Open-fragment state for cross-page table merging.

    Workflow per page::

        for table in page.tables:
            if table.is_fragment:
                buffer.append_open_fragment(table)
            else:
                merged = buffer.close_and_merge(closing_piece=table)
                # merged is the substitution text for table.token;
                # buffer.last_closed_dropped_tokens() gives the earlier-page
                # tokens that should be erased.
    """

    def __init__(self) -> None:
        self._open_chains: dict[int, _OpenTableFragmentChain] = {}
        self._last_closed_dropped_tokens: list[str] = []

    def append_open_fragment(self, fragment: Table) -> None:
        if not fragment.is_fragment:
            raise ValueError(
                f"append_open_fragment expected a fragment, got "
                f"is_fragment=False for token {fragment.token!r}."
            )
        chain = self._open_chains.setdefault(
            fragment.start_page, _OpenTableFragmentChain(start_page=fragment.start_page)
        )
        chain.append(fragment)

    def close_and_merge(self, *, closing_piece: Table) -> str:
        chain = self._open_chains.pop(closing_piece.start_page, None)
        self._last_closed_dropped_tokens = (
            chain.all_fragment_tokens() if chain is not None else []
        )
        if chain is None:
            # Closing piece arrived without prior fragments — a standalone
            # single-page table.  Nothing to merge.
            return closing_piece.markdown
        return chain.merge_into_markdown(closing_piece)

    def last_closed_dropped_tokens(self) -> list[str]:
        """Tokens (from earlier fragment pages) the resolver must erase."""
        return list(self._last_closed_dropped_tokens)

    def open_fragment_tokens(self) -> list[str]:
        """Tokens still belonging to never-closed fragments (for orphan reporting)."""
        return [
            token
            for chain in self._open_chains.values()
            for token in chain.all_fragment_tokens()
        ]

    def drain_unclosed_chains(self) -> dict[int, str]:
        """
        Surface every unclosed chain on shutdown.

        Returns a ``{start_page: merged_markdown_so_far}`` mapping so the
        assembler can emit a degraded-mode notice at the start-page token
        of each abandoned table rather than silently losing the rows.
        """
        if not self._open_chains:
            return {}
        logger.warning(
            "table_fragment_buffer_unclosed_chains",
            extra={"unclosed_start_pages": sorted(self._open_chains.keys())},
        )
        drained = {
            start_page: "\n".join(p.markdown.rstrip("\n") for p in chain.pieces)
            for start_page, chain in self._open_chains.items()
        }
        self._open_chains.clear()
        return drained
