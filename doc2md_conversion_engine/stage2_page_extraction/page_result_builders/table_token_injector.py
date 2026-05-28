"""
stage2_page_extraction/page_result_builders/table_token_injector.py
===================================================================
Stage 2 · lift tables out of a page's Markdown and leave a token in their place.

This is the table counterpart of ``figure_token_injector``. A table — like a figure —
is something a later stage may need to finish assembling: clinical-guideline tables
often run across a page break, and Stage 4 merges the pieces into one. For that to be
reliable, Stage 2 must leave a stable *anchor* where the table belongs, not just hope
Stage 4 can find the table's text again inside the page.

So each table found in the page Markdown is:

  1. recorded as a structured ``Table`` (its Markdown, the page it is on, whether it
     looks like it continues onto the next page), and
  2. replaced in the page Markdown with a ``${TBL:<job_id>:<page>:<index>}`` token.

Stage 4 later substitutes each token with the table's Markdown — merging fragments
across pages first. Because the position is anchored by a token, Stage 4 reassembles
by token lookup and never by fragile string-matching of table text.

Why scan the Markdown instead of asking the engine
---------------------------------------------------
Both engines render tables as GitHub-flavoured Markdown inline in the page text, so a
single scanner works identically for Docling and MinerU with no engine-specific table
API.

This module deliberately does NOT merge anything — see ``STAGE_2_PLAN.md`` §6 for the
boundary. It anchors and flags; Stage 4 merges.
"""

from __future__ import annotations

from ...contracts.pipeline_domain_types import Table


def inject_table_tokens(
    *,
    job_id: str,
    page_number: int,
    page_markdown: str,
) -> tuple[str, list[Table]]:
    """
    Replace each GFM table in the page with a token and return the structured tables.

    Returns the rewritten Markdown (tables swapped for ``${TBL:...}`` tokens) and one
    ``Table`` per table found, in reading order. The final table on the page is
    flagged ``is_fragment`` when nothing of substance follows it — the cheap "it
    reaches the bottom, it might continue" hint Stage 4 later confirms and merges.
    """
    table_blocks = _find_markdown_table_blocks(page_markdown)
    if not table_blocks:
        return page_markdown, []

    last_block_runs_to_page_end = _is_last_substantive_block(page_markdown, table_blocks[-1])

    updated_markdown = page_markdown
    tables: list[Table] = []
    for index, block in enumerate(table_blocks):
        is_last_block = index == len(table_blocks) - 1
        token = build_table_token(job_id=job_id, page_number=page_number, index_on_page=index)
        # Anchor the table's position with its token (replace this block once).
        updated_markdown = updated_markdown.replace(block, token, 1)
        tables.append(
            Table(
                token=token,
                page_number=page_number,
                markdown=block,
                is_fragment=is_last_block and last_block_runs_to_page_end,
                start_page=page_number,
            )
        )
    return updated_markdown, tables


def build_table_token(*, job_id: str, page_number: int, index_on_page: int) -> str:
    """
    Build the canonical table token ``${TBL:<job_id>:<page>:<index>}``.

    The page number is zero-padded to three digits so tokens sort naturally and read
    consistently — mirroring the figure token format. This is the single source of the
    table token format.
    """
    return f"${{TBL:{job_id}:{page_number:03d}:{index_on_page}}}"


# ----------------------------------------------------------------------
# GFM table scanning (engine-agnostic)
# ----------------------------------------------------------------------


def _find_markdown_table_blocks(markdown: str) -> list[str]:
    """
    Return each GFM table in ``markdown`` as its own block of text, in order.

    A GFM table is a run of consecutive lines that all look like table rows
    (contain a pipe) where the second line is a header separator such as
    ``|---|---|``. Lines are grouped into maximal contiguous runs; a run is a table
    only if it has the tell-tale separator row.
    """
    lines = markdown.splitlines()
    blocks: list[str] = []
    current_run: list[str] = []

    for line in lines:
        if "|" in line and line.strip():
            current_run.append(line)
            continue
        if current_run:
            _commit_table_run(current_run, blocks)
            current_run = []
    if current_run:
        _commit_table_run(current_run, blocks)

    return blocks


def _commit_table_run(run: list[str], blocks: list[str]) -> None:
    """Append ``run`` to ``blocks`` only if it is a real table (has a separator row)."""
    if len(run) >= 2 and _is_separator_row(run[1]):
        blocks.append("\n".join(run))


def _is_separator_row(line: str) -> bool:
    """Return whether a line is a GFM header separator like ``|---|:--:|``."""
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if not cells:
        return False
    return all(cell and set(cell) <= set("-: ") and "-" in cell for cell in cells)


def _is_last_substantive_block(markdown: str, last_block: str) -> bool:
    """Return whether ``last_block`` is the final non-empty content of the page."""
    remainder = markdown[markdown.rfind(last_block) + len(last_block):]
    return remainder.strip() == ""
