"""
stage4_assembly_and_output/table_token_resolver.py
===================================================
Resolve every ``${TBL:...}`` token on a single page.

Two cases:

* **Self-contained table** (``is_fragment=False`` and no buffered chain for
  its ``start_page``) — substitute ``table.markdown`` verbatim.
* **Multi-page table** — accumulate fragments in :class:`TableFragmentBuffer`
  and, when the closing piece arrives, anchor the merged Markdown on the
  closing-piece token while erasing the earlier-page fragment tokens.

Open fragments on a page are deferred: their tokens are erased from the
current page (the table will appear on the closing page), so the page
still publishes immediately and streaming is preserved.

Cross-page coordination
-----------------------
The buffer's state outlives a single page.  This resolver therefore must
be instantiated *once* per document and reused across every page —
constructing a fresh resolver per page would erase the open-fragment
state and silently break multi-page tables.  The streaming assembler
honours that lifecycle.
"""

from __future__ import annotations

import logging

from ..contracts import AbstractTokenResolver, PageResult, Table
from .table_fragment_buffer import TableFragmentBuffer

logger = logging.getLogger(__name__)


class TableTokenResolver(AbstractTokenResolver):
    """Resolve ``${TBL:...}`` tokens, including cross-page fragment merges."""

    def __init__(self, *, table_fragment_buffer: TableFragmentBuffer) -> None:
        self._buffer = table_fragment_buffer

    async def resolve_page_tokens(self, page: PageResult) -> dict[str, str]:
        replacements: dict[str, str] = {}
        for table in page.tables:
            if table.is_fragment:
                self._buffer.append_open_fragment(table)
                # Erase the fragment's token on this page — the merged table
                # will publish on the closing-piece token's page.
                replacements[table.token] = ""
            else:
                replacements[table.token] = self._merge_or_use_standalone(table)
                for dropped_token in self._buffer.last_closed_dropped_tokens():
                    # These earlier-page tokens have already been written
                    # erased; their entries here are defensive — if any
                    # appears on the *current* page (out-of-order shipping)
                    # erase it so it does not leak into the output.
                    replacements.setdefault(dropped_token, "")
        return replacements

    def _merge_or_use_standalone(self, closing_piece: Table) -> str:
        return self._buffer.close_and_merge(closing_piece=closing_piece)

    def unclosed_fragment_summary_markdown(
        self,
        *,
        degraded_placeholder: str,
    ) -> dict[int, str]:
        """
        Surface every unclosed chain after the page stream is exhausted.

        Returns ``{start_page: emit_text}`` where ``emit_text`` is the
        accumulated fragment Markdown plus a degraded-mode banner naming
        the missing close.  The streaming assembler can use this to attach
        a footer to the published document instead of silently losing
        the rows.
        """
        drained = self._buffer.drain_unclosed_chains()
        if not drained:
            return {}
        return {
            start_page: (
                f"{markdown_so_far}\n\n"
                f"{degraded_placeholder}\n"
                f"<!-- table starting on page {start_page} had no closing fragment -->"
            )
            for start_page, markdown_so_far in drained.items()
        }
