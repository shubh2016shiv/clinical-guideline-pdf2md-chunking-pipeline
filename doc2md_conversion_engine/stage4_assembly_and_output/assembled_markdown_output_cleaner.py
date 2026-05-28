"""
stage4_assembly_and_output/assembled_markdown_output_cleaner.py
================================================================
Post-substitution Markdown normalisation.

Pure-string transform — no I/O, no state.  Three responsibilities:

1. **Collapse 3+ blank lines to 2.**  Dropped-decorative tokens, mid-page
   table fragments and join boundaries between pages can all leave runs
   of blank lines.  Markdown only needs a single blank line for a
   paragraph break; more than two looks broken.
2. **Strip trailing whitespace** on every line.  Many Markdown renderers
   treat ``"  \n"`` as a hard line-break — leaving stray trailing
   whitespace causes subtle layout bugs in the final ``.md``.
3. **Sweep orphan tokens.**  Any ``${FIG:...}`` / ``${TBL:...}`` still in
   the text after every resolver has run is a contract violation
   (Stage 2 emitted a token nobody resolved).  Replacing it with the
   degraded placeholder ensures the published Markdown never exposes the
   pipeline's internal placeholder syntax to a reader.

The cleaner runs once per page **before** the flusher sees the text, so
the published document is always clean.
"""

from __future__ import annotations

import logging
import re
from typing import Final

from ..contracts import AbstractAssembledMarkdownCleaner, AssemblyConfig
from .token_substitution_engine import ANY_PIPELINE_TOKEN_PATTERN

logger = logging.getLogger(__name__)

# 3+ consecutive newlines (i.e. 2+ blank lines) collapse to exactly 2
# newlines (one blank line between paragraphs).
_MORE_THAN_TWO_NEWLINES_PATTERN: Final[re.Pattern[str]] = re.compile(r"\n{3,}")

# Trailing whitespace on a line (preserve the newline itself).
_TRAILING_LINE_WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[ \t]+\n")


class AssembledMarkdownOutputCleaner(AbstractAssembledMarkdownCleaner):
    """Normalise a fully-substituted page Markdown before it is flushed."""

    def __init__(self, *, assembly_config: AssemblyConfig) -> None:
        self._degraded_placeholder = assembly_config.degraded_mode_placeholder

    def clean_page(self, page_markdown: str) -> str:
        swept = self._sweep_orphan_tokens(page_markdown)
        no_trailing_ws = _TRAILING_LINE_WHITESPACE_PATTERN.sub("\n", swept)
        collapsed_blanks = _MORE_THAN_TWO_NEWLINES_PATTERN.sub("\n\n", no_trailing_ws)
        return collapsed_blanks.strip("\n") + "\n"

    def _sweep_orphan_tokens(self, page_markdown: str) -> str:
        leftovers = ANY_PIPELINE_TOKEN_PATTERN.findall(page_markdown)
        if not leftovers:
            return page_markdown
        logger.error(
            "cleaner_sweeping_orphan_tokens",
            extra={"orphan_tokens": leftovers},
        )
        return ANY_PIPELINE_TOKEN_PATTERN.sub(self._degraded_placeholder, page_markdown)
