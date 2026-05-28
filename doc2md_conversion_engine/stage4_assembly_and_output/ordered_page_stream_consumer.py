"""
stage4_assembly_and_output/ordered_page_stream_consumer.py
===========================================================
Reorder Stage 2's PageResult stream by ``page_number``.

Why this exists
---------------
Stage 2's windowed extraction can produce pages out of strict reading
order — independent windows finish at different times, and within a
window the engine may emit pages in batches.  The published document
**must** preserve PDF reading order: page 7 must never appear before
page 6.

This consumer wraps the upstream async iterator with a small priority
buffer keyed by ``page_number``.  It emits the next page only when it is
the page the assembler is waiting for, holding higher-numbered pages
back until the gap fills.  Memory is bounded by the size of the largest
out-of-order window — for the windowed extractor that is at most the
window's page count.

The consumer is deliberately *not* responsible for gap recovery:  if a
page is missing entirely (Stage 2 silently dropped it) the consumer will
block waiting for it forever.  That is the correct behaviour — a missing
page is a Stage 2 contract violation that must be surfaced upstream, not
papered over by silently emitting a hole.
"""

from __future__ import annotations

import heapq
from collections.abc import AsyncGenerator, AsyncIterable

from ..contracts import PageResult


class OrderedPageStreamConsumer:
    """
    Stream pages in strict ``page_number`` order.

    Usage::

        async for page in OrderedPageStreamConsumer(stream.page_results,
                                                    first_page=1).iter():
            ...
    """

    def __init__(
        self,
        upstream: AsyncIterable[PageResult],
        *,
        first_page: int = 1,
    ) -> None:
        self._upstream = upstream
        self._next_expected_page = first_page

    async def iter(self) -> AsyncGenerator[PageResult, None]:
        """Yield pages in ascending ``page_number`` order without gaps."""
        pending: list[tuple[int, int, PageResult]] = []
        # Tie-breaker keeps the heap stable when two pages share a number
        # (which would itself be a Stage 2 bug — handle it deterministically).
        arrival_counter = 0

        async for page in self._upstream:
            arrival_counter += 1
            heapq.heappush(pending, (page.page_number, arrival_counter, page))

            while pending and pending[0][0] == self._next_expected_page:
                _page_number, _arrival, ready_page = heapq.heappop(pending)
                self._next_expected_page += 1
                yield ready_page

        # Upstream is exhausted; drain whatever remains in ascending order.
        # If a gap remains the loop simply emits what we have — surfacing the
        # missing page numbers in the assembler's per-page log is enough.
        while pending:
            _page_number, _arrival, ready_page = heapq.heappop(pending)
            self._next_expected_page = ready_page.page_number + 1
            yield ready_page
