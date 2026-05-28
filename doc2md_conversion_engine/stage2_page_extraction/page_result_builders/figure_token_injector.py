"""
stage2_page_extraction/page_result_builders/figure_token_injector.py
====================================================================
Stage 2 · replace figure markers in page Markdown with resolvable tokens.

When an engine finds a figure on a page it leaves a plain marker in the Markdown
(``FIGURE_PLACEHOLDER_MARKER``) and hands over the raw image. This module does the
three things that turn that into something the later stages can use:

  1. writes the figure's PNG to disk in the window's output folder,
  2. fingerprints the image bytes with SHA-256 (so Stage 3 can skip re-summarising
     a figure it has already described), and
  3. swaps the marker for a ``${FIG:<job_id>:<page>:<index>}`` token that Stage 4
     later replaces with the figure's written summary.

Why a token instead of waiting for the summary now
---------------------------------------------------
Describing a figure means a vision-model call, which is slow. Blocking page
extraction on it would idle the GPU. Writing a token immediately lets extraction run
at full speed while Stage 3 summarises figures in the background; Stage 4 substitutes
the real text once it is ready.

This logic lives here, shared, precisely so Docling and MinerU produce identical
tokens, identical filenames, and identical hashes for the same figure — the property
Stage 3's deduplication and Stage 4's resolution both rely on.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ...contracts.pipeline_domain_types import Figure
from .raw_page_extraction import FIGURE_PLACEHOLDER_MARKER, RawFigure

logger = logging.getLogger(__name__)


def inject_figure_tokens(
    *,
    job_id: str,
    page_number: int,
    page_markdown: str,
    raw_figures: list[RawFigure],
    figures_output_dir: Path,
) -> tuple[str, list[Figure]]:
    """
    Persist each figure, swap its marker for a token, and return the updated page.

    Markers and figures are paired by order: the first marker in the Markdown maps to
    the first ``RawFigure``, and so on. Returns the rewritten Markdown plus the list
    of ``Figure`` records (token, on-disk PNG path, SHA-256) for the ``PageResult``.

    A mismatch between marker count and figure count is handled honestly rather than
    by crashing: only the pairs that line up are tokenised, any leftover markers are
    cleared so no raw marker leaks into the output, and the discrepancy is logged.
    """
    marker_count = page_markdown.count(FIGURE_PLACEHOLDER_MARKER)
    if marker_count != len(raw_figures):
        logger.warning(
            "figure.marker_mismatch job_id=%s page=%s markers=%s figures=%s",
            job_id,
            page_number,
            marker_count,
            len(raw_figures),
        )

    figures_output_dir.mkdir(parents=True, exist_ok=True)

    updated_markdown = page_markdown
    figures: list[Figure] = []
    for index, raw_figure in enumerate(raw_figures):
        if FIGURE_PLACEHOLDER_MARKER not in updated_markdown:
            # More figures than markers: the remaining figures have nowhere to anchor
            # in the text, so stop rather than append orphan tokens out of position.
            logger.warning(
                "figure.no_marker_for_figure job_id=%s page=%s figure_index=%s",
                job_id,
                page_number,
                index,
            )
            break

        figure = _persist_one_figure(
            job_id=job_id,
            page_number=page_number,
            index_on_page=index,
            raw_figure=raw_figure,
            figures_output_dir=figures_output_dir,
        )
        # Replace only this figure's marker (the first remaining one), left to right.
        updated_markdown = updated_markdown.replace(FIGURE_PLACEHOLDER_MARKER, figure.token, 1)
        figures.append(figure)

    # Clear any markers left unpaired (fewer figures than markers) so the output
    # never contains a bare placeholder.
    if FIGURE_PLACEHOLDER_MARKER in updated_markdown:
        updated_markdown = updated_markdown.replace(FIGURE_PLACEHOLDER_MARKER, "")

    return updated_markdown, figures


def _persist_one_figure(
    *,
    job_id: str,
    page_number: int,
    index_on_page: int,
    raw_figure: RawFigure,
    figures_output_dir: Path,
) -> Figure:
    """Write one figure's PNG, hash it, and build its ``Figure`` record + token."""
    sha256_hex = hashlib.sha256(raw_figure.image_png_bytes).hexdigest()
    image_path = figures_output_dir / f"figure_p{page_number:03d}_{index_on_page}.png"
    image_path.write_bytes(raw_figure.image_png_bytes)

    token = build_figure_token(job_id=job_id, page_number=page_number, index_on_page=index_on_page)
    return Figure(
        token=token,
        page_number=page_number,
        index_on_page=index_on_page,
        image_path=image_path,
        sha256=sha256_hex,
    )


def build_figure_token(*, job_id: str, page_number: int, index_on_page: int) -> str:
    """
    Build the canonical figure token ``${FIG:<job_id>:<page>:<index>}``.

    The page number is zero-padded to three digits so tokens sort naturally and read
    consistently. This is the single source of the token format — engines never
    construct tokens themselves.
    """
    return f"${{FIG:{job_id}:{page_number:03d}:{index_on_page}}}"
