"""
stage2_page_extraction/windowed_extraction/page_window_planner.py
=================================================================
Stage 2 · work out which windows of pages still need processing.

A long document is processed in fixed-size *windows* of pages (8 by default) rather
than all at once. This module answers one small, pure question: given a document of N
pages, a window size, and how far a previous run got, which windows are left to do?

It is deliberately free of GPU, async, and I/O — pure arithmetic over page numbers —
so the resume logic (which is exactly the kind of off-by-one code that is painful to
debug when entangled with the conversion loop) can be reasoned about and tested in
isolation.

Window indexing is global and stable: window 0 is always pages 1..size, window 1 the
next size pages, and so on, regardless of where a run resumes. That stability is what
keeps the plan aligned with the windows already recorded in the checkpoint — the
windows we skip here are exactly the ones already completed there.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageWindow:
    """
    One contiguous batch of pages to extract together.

    ``index`` is the global 0-based position of this window in the document (stable
    across runs). ``start_page`` and ``end_page`` are 1-based and inclusive.
    """

    index: int
    start_page: int
    end_page: int

    @property
    def page_numbers(self) -> list[int]:
        """The 1-based page numbers covered by this window, in order."""
        return list(range(self.start_page, self.end_page + 1))


def plan_remaining_windows(
    *,
    total_pages: int,
    window_size: int,
    last_completed_page: int,
) -> list[PageWindow]:
    """
    Return the windows still to process, in order, skipping completed ones.

    Walks the document in fixed ``window_size`` chunks from page 1, assigning each a
    stable global index, and keeps only those whose pages are not already fully done
    (``start_page > last_completed_page``). A window only partially covered by prior
    progress is re-run in full — safe because the checkpoint records whole windows, so
    ``last_completed_page`` normally lands on a window boundary anyway.
    """
    remaining: list[PageWindow] = []
    window_index = 0
    start_page = 1
    while start_page <= total_pages:
        end_page = min(start_page + window_size - 1, total_pages)
        if start_page > last_completed_page:
            remaining.append(PageWindow(index=window_index, start_page=start_page, end_page=end_page))
        start_page = end_page + 1
        window_index += 1
    return remaining
