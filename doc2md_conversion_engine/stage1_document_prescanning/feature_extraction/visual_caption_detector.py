"""
stage1_document_prescanning/feature_extraction/visual_caption_detector.py
==========================================================================
Stage 1 · Step 2 of 3 — recognise figure/chart captions in text.

A small, shared helper used by the format readers. When a reader finds a chunk
of text near an image, it asks this module: "does this text look like a figure
caption?" (for example "Figure 3: blood pressure over time" or "Chart 2"). That
hint helps decide whether a picture is a meaningful figure worth flagging for a
later stage, versus decoration like a logo.

It is pure text matching — no document is opened here — which is why all four
format readers can share it.
"""

from __future__ import annotations

import re

# Matches the words documents use to label visuals ("figure", "fig", "chart",
# "diagram", "flowchart"), optionally followed by a number like "Figure 3".
_FIGURE_CAPTION_RE = re.compile(r"\b(fig(?:ure)?|chart|diagram|flowchart)\s*[\.:]?\s*\d*", re.I)


def compact_text(value: str | None, *, limit: int = 240) -> str | None:
    """
    Tidy a text snippet so it is safe and short to store as evidence.

    Squashes runs of whitespace/newlines into single spaces and cuts the result
    to a sane length. Returns ``None`` for empty or whitespace-only input, so
    callers can treat "no usable text" uniformly.
    """
    if not value:
        return None
    compacted = " ".join(value.split())
    if not compacted:
        return None
    return compacted[:limit]


def contains_figure_caption(text: str | None) -> bool:
    """Say whether a piece of text reads like a figure/chart caption."""
    return bool(text and _FIGURE_CAPTION_RE.search(text))


def count_figure_caption_lines(text: str) -> int:
    """
    Count how many lines in a block of text look like captions.

    Used as a cheap "how figure-heavy is this page?" signal: more caption-like
    lines suggests more real figures rather than incidental images.
    """
    return sum(1 for line in text.splitlines() if contains_figure_caption(line))

