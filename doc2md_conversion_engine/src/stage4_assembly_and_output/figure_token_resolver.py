"""
stage4_assembly_and_output/figure_token_resolver.py
====================================================
Resolve every ``${FIG:...}`` token on a single page.

Policy (single source of truth — Stage 3 produces, Stage 4 routes)
------------------------------------------------------------------
* Token resolved AND ``is_informative=True``  →  substitute ``markdown_result``.
* Token resolved AND ``is_informative=False`` →  drop the token (decoratives
  carry no informational content of any kind — logos, stock photos,
  ornamental rules; pasting a placeholder paragraph would inject phantom
  prose that the source document does not contain, regardless of domain).
* Token unresolved within the wall-clock budget →  substitute the
  ``degraded_mode_placeholder`` from ``AssemblyConfig`` so the document
  still completes and the gap is auditable.

Why polling, not awaiting
-------------------------
Stage 3 owns its own concurrency and timeouts.  Stage 4 is the
consumer-side clock: if Stage 3 is wedged, the document must still
finish.  A polling loop guarded by ``AsyncOperationTimeoutGuard`` gives
the assembler a liveness guarantee that does not depend on Stage 3's
internal health.

For the smoke-test path (all summaries already persisted to disk before
Stage 4 runs) the very first poll succeeds, so the polling cost is
negligible.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from ..contracts import (
    AbstractFigureSummaryProvider,
    AbstractTokenResolver,
    AssemblyConfig,
    FaultToleranceConfig,
    Figure,
    FigureSummary,
    PageResult,
    TokenResolutionTimeoutError,
)
from ..fault_tolerance import AsyncOperationTimeoutGuard

logger = logging.getLogger(__name__)

# Poll cadence inside the wall-clock budget.  Tight enough that an
# already-persisted summary is picked up in the first tick; loose enough
# that a wedged Stage 3 does not burn CPU.
_FIGURE_RESOLUTION_POLL_INTERVAL_SECONDS: Final[float] = 0.1


class FigureTokenResolver(AbstractTokenResolver):
    """
    Resolve every ``${FIG:...}`` token on a page against a summary provider.
    """

    def __init__(
        self,
        *,
        figure_summary_provider: AbstractFigureSummaryProvider,
        assembly_config: AssemblyConfig,
        fault_tolerance_config: FaultToleranceConfig,
    ) -> None:
        self._provider = figure_summary_provider
        self._degraded_placeholder = assembly_config.degraded_mode_placeholder
        self._timeout_guard = AsyncOperationTimeoutGuard(
            fault_tolerance_config.timeouts
        )

    async def resolve_page_tokens(self, page: PageResult) -> dict[str, str]:
        replacements: dict[str, str] = {}
        for figure in page.figures:
            replacements[figure.token] = await self._resolve_one_figure(
                figure=figure, page_number=page.page_number
            )
        return replacements

    async def _resolve_one_figure(self, *, figure: Figure, page_number: int) -> str:
        try:
            summary = await self._await_summary_with_budget(
                token=figure.token, page_number=page_number
            )
        except TokenResolutionTimeoutError:
            logger.warning(
                "figure_token_resolution_timeout",
                extra={"token": figure.token, "page_number": page_number},
            )
            return self._degraded_placeholder

        if summary is None:
            logger.warning(
                "figure_token_unresolved_after_budget",
                extra={"token": figure.token, "page_number": page_number},
            )
            return self._degraded_placeholder

        if not summary.is_informative:
            logger.info(
                "figure_token_dropped_decorative",
                extra={"token": figure.token, "page_number": page_number},
            )
            return ""

        return summary.markdown_result

    async def _await_summary_with_budget(
        self,
        *,
        token: str,
        page_number: int,
    ) -> FigureSummary | None:
        # Fast path: the summary is already persisted (resume / smoke test).
        summary = await self._provider.get_summary(token)
        if summary is not None:
            return summary

        async with self._timeout_guard.figure_token_resolution(
            token=token, page_number=page_number
        ):
            while True:
                summary = await self._provider.get_summary(token)
                if summary is not None:
                    return summary
                await asyncio.sleep(_FIGURE_RESOLUTION_POLL_INTERVAL_SECONDS)
