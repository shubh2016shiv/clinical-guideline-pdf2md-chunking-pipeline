"""
stage4_assembly_and_output/token_substitution_pipeline.py
==========================================================
Per-page substitution pipeline: figure resolver + table resolver + engine.

The pipeline collects replacements from every token resolver, then hands
them — as a single flat ``{token: text}`` map — to the policy-free
:class:`TokenSubstitutionEngine` for the actual string surgery.

Why a pipeline (rather than each resolver doing its own ``str.replace``)?
-------------------------------------------------------------------------
* **Single pass over the page Markdown.**  Multiple ``str.replace`` calls
  over a large page string is wasteful; one merged pass is enough.
* **Centralised drop-semantics.**  The "erase token + adjacent blank line"
  rule lives in one place (the engine), not duplicated across resolvers.
* **Token-family extensibility.**  Adding a future ``${EQN:...}`` family
  is one constructor argument away — the pipeline does not know which
  families exist.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ..contracts import AbstractTokenResolver, PageResult
from .token_substitution_engine import (
    ANY_PIPELINE_TOKEN_PATTERN,
    TokenSubstitutionEngine,
)

logger = logging.getLogger(__name__)


class TokenSubstitutionPipeline:
    """Apply every configured token resolver to one page, then substitute."""

    def __init__(
        self,
        *,
        token_resolvers: Iterable[AbstractTokenResolver],
        substitution_engine: TokenSubstitutionEngine,
    ) -> None:
        self._resolvers = list(token_resolvers)
        self._engine = substitution_engine

    async def resolve_and_substitute(self, page: PageResult) -> str:
        replacements: dict[str, str] = {}
        for resolver in self._resolvers:
            page_replacements = await resolver.resolve_page_tokens(page)
            # Resolvers own non-overlapping token families; a collision
            # means two resolvers claimed the same token, which is a wiring
            # bug.  Log and let the later resolver win deterministically.
            for token, replacement_text in page_replacements.items():
                if token in replacements and replacements[token] != replacement_text:
                    logger.error(
                        "token_resolver_collision",
                        extra={
                            "token": token,
                            "page_number": page.page_number,
                        },
                    )
                replacements[token] = replacement_text

        substituted = self._engine.substitute(
            page_markdown=page.markdown_with_tokens,
            replacements=replacements,
        )
        self._warn_on_orphan_tokens(page_number=page.page_number, markdown=substituted)
        return substituted

    @staticmethod
    def _warn_on_orphan_tokens(*, page_number: int, markdown: str) -> None:
        leftovers = ANY_PIPELINE_TOKEN_PATTERN.findall(markdown)
        if not leftovers:
            return
        logger.warning(
            "orphan_tokens_after_substitution",
            extra={
                "page_number": page_number,
                "orphan_tokens": leftovers,
            },
        )
