"""
stage2_page_extraction/page_result_builders/page_markdown_reader.py
===================================================================
Stage 2 · turn an engine's raw page Markdown into clean, consistent Markdown.

Different engines emit slightly messy Markdown — stray runs of blank lines, leading
or trailing whitespace, Windows line endings. Before that text becomes the canonical
page output, this small helper tidies it so every page reads consistently regardless
of which engine produced it. It is intentionally conservative: it normalises spacing
only and never rewrites or drops content.

It also offers a helper for the subprocess case: MinerU writes its result to a
Markdown file on disk, so ``read_markdown_file`` loads it. Docling produces Markdown
in memory and skips the file step entirely.
"""

from __future__ import annotations

import re
from pathlib import Path

# Collapse three-or-more consecutive newlines down to the standard paragraph break
# of exactly one blank line. Keeps single blank lines (paragraph separators) intact.
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_markdown(raw_markdown: str) -> str:
    """
    Return ``raw_markdown`` with consistent line endings and blank-line spacing.

    Normalises CRLF/CR to LF, collapses runs of blank lines to a single blank line,
    and strips leading/trailing whitespace. Content is never altered — only spacing.
    """
    unified_newlines = raw_markdown.replace("\r\n", "\n").replace("\r", "\n")
    collapsed = _EXCESS_BLANK_LINES.sub("\n\n", unified_newlines)
    return collapsed.strip()


def read_markdown_file(markdown_path: Path) -> str:
    """
    Read and normalise a Markdown file an engine wrote to disk (the MinerU case).

    Returns an empty string when the file is missing, treating "no output for this
    page" as empty content rather than an error — a page legitimately may carry no
    text (a full-page figure, for example).
    """
    if not markdown_path.is_file():
        return ""
    return normalize_markdown(markdown_path.read_text(encoding="utf-8"))
