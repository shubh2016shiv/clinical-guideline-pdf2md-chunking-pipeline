"""
stage2_page_extraction/page_result_builders/raw_page_extraction.py
==================================================================
Stage 2 · the contract between an engine and the page-result builder.

A conversion engine (Docling, MinerU) knows how to read a document, but the two
read it in completely different ways and produce different raw output. So that the
rest of Stage 2 does not care which engine ran, every engine normalises its output
into the *same* small shape defined here — a ``RawPage`` per page — and hands it to
the shared builder, which turns it into the canonical ``PageResult``.

In other words: each engine speaks its own language internally, but they all agree
to say the same two things about a page before the builder takes over:

  * the page's text as Markdown, with a known placeholder marker wherever a figure
    sits (so the builder can swap each marker for a ``${FIG:...}`` token), and
  * the figures found on the page, in the same left-to-right / top-to-bottom order
    the markers appear.

Tables are not part of this contract on purpose. Both engines render tables as
GitHub-flavoured Markdown inline in the page text, so the builder derives structured
table records by scanning that Markdown (see ``table_fragment_detector``) rather than
asking each engine for a separate, engine-specific table structure. One scanner, one
behaviour, for both engines.

Keeping this contract tiny and engine-agnostic is what lets Docling and MinerU
produce byte-for-byte identical ``PageResult`` objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The single placeholder every engine must leave in its Markdown where a figure
# belongs. The builder replaces each occurrence, in order, with a figure token.
# Engines normalise their own image syntax (Docling's ``<!-- image -->``, MinerU's
# ``![](path)``) to this one marker so the builder only ever handles one form.
FIGURE_PLACEHOLDER_MARKER = "<!-- figure -->"


@dataclass(frozen=True)
class RawFigure:
    """
    One figure an engine lifted off a page, before it becomes a ``Figure``.

    Holds the raw PNG bytes (which the builder writes to disk and hashes) and an
    optional caption/alt-text the engine happened to find nearby. Position is
    implied by order: the i-th ``RawFigure`` corresponds to the i-th figure marker
    in the page Markdown.
    """

    image_png_bytes: bytes
    caption: str | None = None


@dataclass(frozen=True)
class RawPage:
    """
    Everything an engine extracted from a single page, in engine-neutral form.

    This is the unit an engine yields internally and the builder consumes to
    produce one ``PageResult``. Tables are intentionally absent — they live inline
    in ``markdown`` and the builder scans them out (see the module docstring).
    """

    page_number: int
    markdown: str
    figures: list[RawFigure] = field(default_factory=list)
