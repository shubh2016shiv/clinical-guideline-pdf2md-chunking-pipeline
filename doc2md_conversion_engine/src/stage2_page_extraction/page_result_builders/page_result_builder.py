"""
stage2_page_extraction/page_result_builders/page_result_builder.py
==================================================================
Stage 2 · assemble one engine-neutral ``RawPage`` into a canonical ``PageResult``.

This is the single front door the engines call to finish a page. It runs the three
shared steps in order — tidy the Markdown, swap figure markers for tokens (writing
the PNGs), flag any table fragments — and packages the result, the figures, and the
tables into the one ``PageResult`` the rest of the pipeline understands.

Because every engine funnels through this one function, Docling and MinerU emit
identically-shaped pages: same Markdown spacing, same token format, same figure
filenames and hashes. That consistency is the whole reason the page-result building
lives here rather than inside each engine.
"""

from __future__ import annotations

from pathlib import Path

from ...contracts.pipeline_domain_types import ExtractionEngine, PageResult
from .figure_token_injector import inject_figure_tokens
from .page_markdown_reader import normalize_markdown
from .raw_page_extraction import RawPage
from .table_token_injector import inject_table_tokens


def build_page_result(
    *,
    job_id: str,
    engine: ExtractionEngine,
    raw_page: RawPage,
    window_output_dir: Path,
    duration_ms: int,
    is_degraded: bool = False,
) -> PageResult:
    """
    Build the canonical ``PageResult`` for one extracted page.

    Steps, in order:
      1. normalise the page Markdown for consistent spacing,
      2. write each figure's PNG into ``window_output_dir`` and replace its marker
         with a ``${FIG:...}`` token,
      3. lift each table out of the Markdown, replacing it with a ``${TBL:...}``
         token and flagging any that may run onto the next page.

    The resulting ``markdown_with_tokens`` is the page as a template: prose plus
    ``${FIG:...}`` and ``${TBL:...}`` anchors that Stage 4 resolves. ``is_degraded``
    is set by the resilient engine when the fallback engine produced this page. Figure
    PNGs are written under ``window_output_dir`` so they live alongside that window's
    results and are covered by the same checkpoint.
    """
    normalized_markdown = normalize_markdown(raw_page.markdown)

    markdown_with_figure_tokens, figures = inject_figure_tokens(
        job_id=job_id,
        page_number=raw_page.page_number,
        page_markdown=normalized_markdown,
        raw_figures=raw_page.figures,
        figures_output_dir=window_output_dir,
    )

    markdown_with_tokens, tables = inject_table_tokens(
        job_id=job_id,
        page_number=raw_page.page_number,
        page_markdown=markdown_with_figure_tokens,
    )

    return PageResult(
        page_number=raw_page.page_number,
        engine_used=engine,
        is_degraded=is_degraded,
        markdown_with_tokens=markdown_with_tokens,
        figures=figures,
        tables=tables,
        duration_ms=duration_ms,
    )
