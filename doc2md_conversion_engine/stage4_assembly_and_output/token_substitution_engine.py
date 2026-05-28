"""
stage4_assembly_and_output/token_substitution_engine.py
========================================================
Pure, policy-free token substitution.

This module is the mechanical low-level routine every resolver shares.  It
takes a page Markdown plus a flat ``{token: replacement_text}`` mapping and
returns the page Markdown with every token replaced verbatim.  No I/O, no
network calls, no policy decisions — *which* tokens to replace and *what*
to put in their place is the resolvers' responsibility.

Keeping this isolated buys two things:

1. **One place to evolve the substitution rules** (e.g. should we also
   collapse the trailing newline when a token is dropped?  That rule lives
   here, not duplicated across resolvers).
2. **Token-family-agnostic.** A future ``${EQN:...}`` resolver can reuse
   the same engine without any change to this file.
"""

from __future__ import annotations

import re
from typing import Final

# Matches *any* ``${...}`` token. Used only by the orphan-sweep helper —
# resolvers identify tokens by their full literal string, not by regex.
ANY_PIPELINE_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\$\{(?:FIG|TBL):[^}]+\}"
)

# When a token's replacement is the empty string, we also swallow up to one
# adjacent blank line so the dropped figure does not leave a visible gap.
_DROPPED_TOKEN_WITH_TRAILING_BLANK_LINE: Final[str] = "{token}\n\n"
_DROPPED_TOKEN_WITH_LEADING_BLANK_LINE: Final[str] = "\n\n{token}"


class TokenSubstitutionEngine:
    """
    Mechanical replace-all for pipeline tokens.

    Stateless.  A module-level singleton is sufficient — but instantiated
    via a class so callers depend on a type they can substitute in tests
    if they ever need to instrument substitutions.
    """

    def substitute(
        self,
        *,
        page_markdown: str,
        replacements: dict[str, str],
    ) -> str:
        """
        Replace every key in ``replacements`` with its value inside
        ``page_markdown``.

        Drop semantics: when ``replacements[token] == ""``, the token *and*
        one immediately adjacent blank line (trailing preferred, then
        leading) are removed so the dropped figure leaves no visible hole.
        """
        result = page_markdown
        for token, replacement_text in replacements.items():
            if replacement_text == "":
                result = self._erase_token_and_adjacent_blank_line(result, token)
            else:
                result = result.replace(token, replacement_text)
        return result

    @staticmethod
    def _erase_token_and_adjacent_blank_line(markdown: str, token: str) -> str:
        # Prefer collapsing a trailing blank line so the next prose moves up;
        # fall back to a leading blank line when the token sits at the end of
        # a section. Final fallback: plain string deletion.
        with_trailing = _DROPPED_TOKEN_WITH_TRAILING_BLANK_LINE.format(token=token)
        if with_trailing in markdown:
            return markdown.replace(with_trailing, "", 1)
        with_leading = _DROPPED_TOKEN_WITH_LEADING_BLANK_LINE.format(token=token)
        if with_leading in markdown:
            return markdown.replace(with_leading, "", 1)
        return markdown.replace(token, "", 1)
