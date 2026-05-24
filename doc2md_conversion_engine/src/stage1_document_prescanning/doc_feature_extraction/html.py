"""
HTML feature extraction for engine routing.

This module does not try to understand the clinical meaning of an HTML document.
It only collects factual evidence that is cheap to inspect:

1. Is there native text?
2. Are there <table> elements?
3. Are there <img> tags (raster images)?
4. Are there inline <svg> elements (vector graphics)?
5. Are there <figure> elements (semantic image/diagram wrappers)?
6. Are there <figcaption> tags or caption-like text patterns?

Thresholds come from ``settings.yaml`` via ``DocumentFeatureExtractionConfig``.

-----

How HTML parsing works here (plain English)
-------------------------------------------
The standard approach to reading HTML is to parse it "event-driven" — instead
of loading the entire document into memory as a navigable tree, the parser reads
the HTML character by character and calls a method on your class each time it
hits something meaningful:

  - Opening tag  (<img src="...">)  → handle_starttag() is called
  - Closing tag  (</table>)         → handle_endtag() is called
  - Plain text   (Hello world)      → handle_data() is called

Think of it like someone reading the HTML aloud and calling out each element as
they encounter it.  ``HtmlDocumentScanner`` listens to those call-outs and keeps
running counts of images, tables, SVGs, etc.

IMPORTANT: handle_starttag, handle_endtag, and handle_data are NOT names we
chose — they are the exact method names Python's HTMLParser base class expects.
Renaming them would silently break the interface.

Why estimate pages?
-------------------
An HTML file has no concept of pages — it is a continuous document.  Like DOCX,
we estimate from character count via ``average_characters_per_page`` in
``settings.yaml``.

Why can't we tell if an image is "large"?
-----------------------------------------
HTML <img> tags may carry width/height attributes, but they are unreliable: they
can be overridden by CSS, set to percentages, or omitted entirely.  Without
rendering the page in a browser we cannot know the actual display size of any
image.  We therefore report large_embedded_image_count as 0 and let downstream
rendering decisions rely on total image count instead.
"""

from __future__ import annotations

import logging
import math
from html.parser import HTMLParser
from pathlib import Path

from ...contracts.configurations.pipeline_config import (
    DocumentFeatureExtractionConfig,
    HtmlFeatureExtractionConfig,
)
from ...contracts.exceptions import DocumentError
from .engine_format_support import get_engine_format_support
from .engine_needs_evaluator import infer_requirements
from .models import (
    DocumentFeatureProfile,
    FeatureDocumentType,
    TableEvidence,
    TextEvidence,
    VisualCandidate,
    VisualCandidateKind,
    VisualEvidence,
)
from .text_patterns import compact_text, contains_figure_caption, count_figure_caption_lines

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def extract_html_features(
    path: Path,
    config: DocumentFeatureExtractionConfig | None = None,
) -> DocumentFeatureProfile:
    """
    Extract deterministic feature evidence from one HTML document.

    The flow is intentionally linear:
    read the source, walk every tag, derive page count and caption count, then
    build the final ``DocumentFeatureProfile`` consumed by the capability router.

    Step 1: Read the raw HTML source from disk.
    Step 2: Run it through HtmlDocumentScanner to count images, tables, SVGs,
            figures, and text as the parser walks tag by tag.
    Step 3: Estimate page count from total character count.
    Step 4: Count figure captions via both the tag-level counter and text patterns.
    Step 5: Assemble and return the feature profile.
    """
    html_settings = (config or DocumentFeatureExtractionConfig()).html

    html_source = read_html_source(path)                          # Step 1
    scanner = scan_html_document(html_source)                     # Step 2

    all_text = "\n".join(scanner.text_collected)
    total_characters = len(all_text)
    estimated_pages = estimate_page_count(total_characters, html_settings)  # Step 3
    total_captioned_figures = count_total_figure_captions(scanner, all_text)  # Step 4

    logger.debug(
        "HTML extraction complete: path=%s estimated_pages=%d chars=%d "
        "images=%d tables=%d svgs=%d figures=%d captions=%d",
        path.name,
        estimated_pages,
        total_characters,
        scanner.image_count,
        scanner.table_count,
        scanner.svg_count,
        scanner.figure_count,
        total_captioned_figures,
    )

    return build_html_feature_profile(                            # Step 5
        scanner=scanner,
        total_characters=total_characters,
        estimated_pages=estimated_pages,
        total_captioned_figures=total_captioned_figures,
        settings=html_settings,
    )


# ---------------------------------------------------------------------------
# Step implementations — called in entry-point order
# ---------------------------------------------------------------------------


def read_html_source(path: Path) -> str:
    """
    Step 1: Read the entire HTML file as a string.

    We ignore encoding errors rather than failing — real-world clinical HTML
    often contains non-UTF-8 characters from copy-pasted content or legacy tools.
    """
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        raise DocumentError(
            f"Could not read HTML file for feature extraction: {path.name}",
            context={"path": str(path)},
        ) from exc


def scan_html_document(html_source: str) -> HtmlDocumentScanner:
    """
    Step 2: Walk the HTML source tag by tag and accumulate feature counts.

    Returns the scanner in its final state — all counters and visual candidates
    are populated and ready for the profile-assembly step.
    """
    scanner = HtmlDocumentScanner()
    scanner.feed(html_source)
    return scanner


def estimate_page_count(
    total_characters: int,
    settings: HtmlFeatureExtractionConfig,
) -> int:
    """
    Step 3: Estimate page count from character count.

    ``settings.average_characters_per_page`` comes from
    ``document_feature_extraction.html.average_characters_per_page`` in
    ``settings.yaml``.  HTML has no real pages — this produces a normalised unit
    that makes HTML feature profiles comparable to PDF and DOCX profiles.
    """
    return max(1, math.ceil(total_characters / settings.average_characters_per_page))


def count_total_figure_captions(
    scanner: HtmlDocumentScanner,
    all_text: str,
) -> int:
    """
    Step 4: Count figure captions via two independent methods, then combine.

    Method A — tag-level: ``scanner.figure_caption_count`` counts every
    <figcaption> tag found during parsing.

    Method B — text patterns: ``count_figure_caption_lines`` scans the collected
    plain text for caption-like patterns (e.g. "Figure 3:", "Fig. 2 —") that
    appear outside of any <figcaption> tag.

    Double-count risk: text inside a <figcaption> also ends up in
    ``scanner.text_collected``, so the same caption can be counted by both
    methods.  We accept this small over-count — it errs toward flagging more
    captions, which is the safer direction for downstream rendering decisions.
    """
    return scanner.figure_caption_count + count_figure_caption_lines(all_text)


# ---------------------------------------------------------------------------
# Step 5: Profile assembly
# ---------------------------------------------------------------------------


def build_html_feature_profile(
    *,
    scanner: HtmlDocumentScanner,
    total_characters: int,
    estimated_pages: int,
    total_captioned_figures: int,
    settings: HtmlFeatureExtractionConfig,
) -> DocumentFeatureProfile:
    """
    Translate scanner counts into the structured profile consumed by the
    capability router downstream.

    ``DocumentFeatureProfile`` is the single object that leaves this module.
    Everything else here is an intermediate view of the same raw numbers,
    shaped into the three distinct contracts the router expects:

    - *evidence* objects (TextEvidence, TableEvidence, VisualEvidence) — aggregate
      statistics (counts, page-equivalent flags).  The router reads these to
      decide *whether* a capability is needed.

    - *visual_candidates* — a ranked short-list of specific elements (<img>,
      <svg>, <figure>, <table>) worth showing to a vision model for a second
      opinion.  HTML candidates carry no area ratio (display size is unknowable
      without rendering), so they are ranked by label presence (alt text or
      nearby caption) rather than size.  Capped by ``settings.max_visual_candidates``
      so the downstream payload stays bounded.

    - *requirements* — inferred capability flags (e.g. needs_ocr, needs_vlm)
      derived from the evidence above.  The router uses these to filter the
      engine candidates it will score.
    """
    # Aggregate statistics — one object per feature dimension.
    text_evidence = build_text_evidence(total_characters, estimated_pages)
    table_evidence = build_table_evidence(scanner, estimated_pages)
    visual_evidence = build_visual_evidence(scanner, estimated_pages, total_captioned_figures)

    # Representative examples — ranked by label presence (no area available for HTML),
    # capped so the downstream router is not overwhelmed by a tag-heavy document.
    visual_candidates = choose_visual_candidates_for_routing(
        scanner.visual_candidates,
        max_candidates_to_keep=settings.max_visual_candidates,
    )

    # Capability flags — derived from evidence, not raw scanner counts.
    # infer_requirements encodes the routing heuristics so this function stays
    # focused on assembly.
    requirements = infer_requirements(
        text=text_evidence,
        tables=table_evidence,
        visuals=visual_evidence,
        visual_candidates=visual_candidates,
    )

    return DocumentFeatureProfile(
        file_type=FeatureDocumentType.HTML,
        page_or_unit_count=estimated_pages,
        text=text_evidence,
        tables=table_evidence,
        visuals=visual_evidence,
        visual_candidates=visual_candidates,
        format_support=get_engine_format_support(FeatureDocumentType.HTML),
        requirements=requirements,
    )


def build_text_evidence(total_characters: int, estimated_pages: int) -> TextEvidence:
    """Summarize native text evidence across the HTML document."""
    return TextEvidence(
        total_characters=total_characters,
        pages_or_units_with_text=estimated_pages if total_characters else 0,
        estimated_text_density=total_characters / max(estimated_pages, 1),
        native_text_available=total_characters > 0,
    )


def build_table_evidence(
    scanner: HtmlDocumentScanner,
    estimated_pages: int,
) -> TableEvidence:
    """Summarize table evidence across the HTML document."""
    return TableEvidence(
        count=scanner.table_count,
        pages_or_units_with_tables=min(scanner.table_count, estimated_pages),
        # HTML provides no reliable size information for tables without rendering.
        # We cannot distinguish a large data table from a small inline one.
        large_count=0,
    )


def build_visual_evidence(
    scanner: HtmlDocumentScanner,
    estimated_pages: int,
    total_captioned_figures: int,
) -> VisualEvidence:
    """Summarize image, SVG, figure, and caption evidence across the HTML document."""
    return VisualEvidence(
        embedded_image_count=scanner.image_count,
        # HTML image sizes are unreliable without rendering — see module docstring.
        large_embedded_image_count=0,
        # HTML has no vector-drawing primitives outside of SVG, which is counted separately.
        vector_graphics_count=0,
        # HTML has no native chart objects; charts appear as images or SVGs (counted above).
        chart_count=0,
        svg_count=scanner.svg_count,
        pages_or_units_with_visuals=min(
            scanner.image_count + scanner.svg_count + scanner.figure_count,
            estimated_pages,
        ),
        captioned_visual_count=total_captioned_figures,
    )


def choose_visual_candidates_for_routing(
    visual_candidates: list[VisualCandidate],
    *,
    max_candidates_to_keep: int,
) -> list[VisualCandidate]:
    """
    Keep the visual elements most useful for engine routing.

    Scoring logic (higher = more important):
    - +1 if the candidate has alt text or a nearby caption (confirms intentional labelling)
    - +N for each additional piece of detection evidence (more signals = more confidence)

    HTML candidates carry no area ratio (display size is unknowable without rendering),
    so there is no size-based tiebreaker here unlike in the PDF and PPTX extractors.
    """
    ranked = sorted(visual_candidates, key=_candidate_routing_priority, reverse=True)
    return ranked[:max_candidates_to_keep]


def _candidate_routing_priority(candidate: VisualCandidate) -> int:
    """Score an HTML visual candidate for routing relevance."""
    has_label = bool(candidate.caption_or_alt_text or candidate.nearby_text)
    return (1 if has_label else 0) + len(candidate.evidence)


# ---------------------------------------------------------------------------
# HTML scanner — event-driven tag walker
# ---------------------------------------------------------------------------


class HtmlDocumentScanner(HTMLParser):
    """
    Walks an HTML document tag by tag, keeping running counts of structural
    elements as they are encountered.

    How to read this class
    ----------------------
    Python's HTMLParser calls three methods on this class as it reads the HTML:

        handle_starttag  — called when an opening tag is found, e.g. <img src="...">
        handle_endtag    — called when a closing tag is found, e.g. </table>
        handle_data      — called for plain text between tags, e.g. "Hello world"

    These method names are required by the HTMLParser interface — they cannot be
    renamed.  Everything else (state flags, counters, collected data) uses plain
    descriptive names.

    State flags
    -----------
    currently_inside_script_or_style_block:
        True while we are between <script>...</script> or <style>...</style>.
        Text inside these blocks is JavaScript or CSS code — not human-readable
        content — so we skip it in handle_data.

    currently_inside_a_figure_caption:
        True while we are between <figcaption>...</figcaption>.
        Any text we see in this state is a figure caption, so we increment
        the caption counter in handle_data without running the text through
        the pattern matcher.
    """

    def __init__(self) -> None:
        super().__init__()

        # State flags — track where in the document we currently are
        self.currently_inside_script_or_style_block: bool = False
        self.currently_inside_a_figure_caption: bool = False

        # Accumulated text from all readable parts of the document
        self.text_collected: list[str] = []

        # Running counts of structural elements
        self.image_count: int = 0
        self.table_count: int = 0
        self.figure_count: int = 0
        self.figure_caption_count: int = 0
        self.svg_count: int = 0

        # Visual candidates for downstream review
        self.visual_candidates: list[VisualCandidate] = []

    # ------------------------------------------------------------------
    # Required HTMLParser interface methods — names cannot be changed
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Called by HTMLParser each time an opening tag is encountered."""
        tag_name = tag.lower()
        attributes = {name.lower(): value for name, value in attrs}

        if tag_name in {"script", "style"}:
            self.currently_inside_script_or_style_block = True
            return

        if tag_name == "figcaption":
            self.currently_inside_a_figure_caption = True
            return

        if tag_name == "table":
            self.table_count += 1
            self.visual_candidates.append(
                VisualCandidate(
                    kind=VisualCandidateKind.TABLE,
                    location_label="html <table> element",
                    evidence=["<table> tag found in HTML source"],
                )
            )
            return

        if tag_name == "figure":
            # <figure> is a semantic HTML5 element that wraps an image, diagram,
            # or code listing — typically paired with a <figcaption> below it.
            self.figure_count += 1
            self.visual_candidates.append(
                VisualCandidate(
                    kind=VisualCandidateKind.FIGURE_ELEMENT,
                    location_label="html <figure> element",
                    evidence=["<figure> tag found in HTML source"],
                )
            )
            return

        if tag_name == "img":
            self.image_count += 1
            # alt text is the accessible description an author writes for an image.
            # It is the closest we can get to a caption at extraction time.
            alt_text = compact_text(attributes.get("alt"))
            image_src = compact_text(attributes.get("src"), limit=120)
            self.visual_candidates.append(
                VisualCandidate(
                    kind=VisualCandidateKind.EMBEDDED_IMAGE,
                    location_label=image_src,
                    caption_or_alt_text=alt_text,
                    evidence=["<img> tag found in HTML source"],
                )
            )
            return

        if tag_name == "svg":
            # <svg> is an inline vector graphic drawn directly in the HTML source
            # using markup — not a separate file, unlike <img>.
            self.svg_count += 1
            self.visual_candidates.append(
                VisualCandidate(
                    kind=VisualCandidateKind.SVG,
                    location_label="inline <svg> element",
                    evidence=["<svg> tag found in HTML source"],
                )
            )

    def handle_endtag(self, tag: str) -> None:
        """Called by HTMLParser each time a closing tag is encountered."""
        tag_name = tag.lower()
        if tag_name in {"script", "style"}:
            self.currently_inside_script_or_style_block = False
        elif tag_name == "figcaption":
            self.currently_inside_a_figure_caption = False

    def handle_data(self, data: str) -> None:
        """Called by HTMLParser for each block of plain text between tags."""
        if self.currently_inside_script_or_style_block:
            return  # Skip JavaScript and CSS code

        readable_text = compact_text(data)
        if not readable_text:
            return

        self.text_collected.append(readable_text)

        # Text inside <figcaption> is definitively a caption; otherwise check
        # for caption-like patterns (e.g. "Figure 3:" or "Fig. 2 —").
        if self.currently_inside_a_figure_caption or contains_figure_caption(readable_text):
            self.figure_caption_count += 1
