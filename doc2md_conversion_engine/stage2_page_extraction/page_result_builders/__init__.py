"""
stage2_page_extraction/page_result_builders
============================================
Shared, engine-neutral helpers that turn an engine's raw page output into the
canonical ``PageResult``.

Both conversion engines funnel their output through here so Docling and MinerU
produce byte-for-byte consistent pages — same Markdown spacing, same figure tokens,
same PNG filenames and hashes. The engines speak the ``RawPage`` contract; the
builder does the rest.

    build_page_result   — the front door: RawPage → PageResult
    RawPage / RawFigure / RawTable + FIGURE_PLACEHOLDER_MARKER — the engine contract
"""

from .figure_token_injector import build_figure_token, inject_figure_tokens
from .page_markdown_reader import normalize_markdown, read_markdown_file
from .page_result_builder import build_page_result
from .raw_page_extraction import (
    FIGURE_PLACEHOLDER_MARKER,
    RawFigure,
    RawPage,
)
from .table_token_injector import build_table_token, inject_table_tokens

__all__ = [
    # The front door
    "build_page_result",
    # The engine ↔ builder contract
    "RawPage",
    "RawFigure",
    "FIGURE_PLACEHOLDER_MARKER",
    # Individual steps (engines may use directly when normalising their output)
    "normalize_markdown",
    "read_markdown_file",
    "inject_figure_tokens",
    "build_figure_token",
    "inject_table_tokens",
    "build_table_token",
]
