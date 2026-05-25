"""
doc_feature_extraction/text_patterns.py
=======================================
Small text helpers shared by format extractors.
"""

from __future__ import annotations

import re

_FIGURE_CAPTION_RE = re.compile(r"\b(fig(?:ure)?|chart|diagram|flowchart)\s*[\.:]?\s*\d*", re.I)


def compact_text(value: str | None, *, limit: int = 240) -> str | None:
    """Collapse whitespace and trim a text snippet for routing evidence."""
    if not value:
        return None
    compacted = " ".join(value.split())
    if not compacted:
        return None
    return compacted[:limit]


def contains_figure_caption(text: str | None) -> bool:
    """Return True when text looks like a figure/chart/diagram caption."""
    return bool(text and _FIGURE_CAPTION_RE.search(text))


def count_figure_caption_lines(text: str) -> int:
    """Count lines that look like visual captions."""
    return sum(1 for line in text.splitlines() if contains_figure_caption(line))

