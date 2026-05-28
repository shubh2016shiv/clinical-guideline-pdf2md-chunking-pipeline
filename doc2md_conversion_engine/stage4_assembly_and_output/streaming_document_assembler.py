"""
stage4_assembly_and_output/streaming_document_assembler.py
===========================================================
Composition root for Stage 4 — the only place concretes are wired together.

Public surface
--------------
* :meth:`build` — factory that constructs every collaborator from
  configuration.  Direct ``__init__`` is reserved for tests / advanced
  callers that need to inject custom collaborators (in-memory sink,
  recording cleaner, fake summary provider).
* :meth:`assemble` — consume the page stream, substitute tokens, clean,
  flush, return a :class:`ConversionSummary`.

The assembler implements no policy beyond *ordering* — every behavioural
decision lives in a named collaborator:

* :class:`OrderedPageStreamConsumer` — re-orders pages by ``page_number``.
* :class:`TokenSubstitutionPipeline` — runs every token resolver and
  applies the engine.
* :class:`AssembledMarkdownOutputCleaner` — post-substitution clean-up.
* :class:`AbstractMarkdownOutputSink` — buffered + atomic publication.
* :class:`ConversionSummaryBuilder` — final metrics row.

Between-page joining
--------------------
Each cleaned page Markdown is appended with a trailing ``\n`` already, so
joining with one additional blank line (``"\n"``) gives a single visible
paragraph break between pages.  No page-header markers are inserted —
the source PDF rarely has a hard break at the page boundary and the
chunker downstream prefers prose without artificial markers.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Self

from ..contracts import (
    AbstractFigureSummaryProvider,
    AbstractMarkdownOutputSink,
    AssemblyConfig,
    ConversionJob,
    ConversionSummary,
    FaultToleranceConfig,
    PageResult,
)
from .assembled_markdown_output_cleaner import AssembledMarkdownOutputCleaner
from .atomic_markdown_output_flusher import AtomicMarkdownOutputFlusher
from .conversion_summary_builder import ConversionSummaryBuilder
from .figure_token_resolver import FigureTokenResolver
from .ordered_page_stream_consumer import OrderedPageStreamConsumer
from .table_fragment_buffer import TableFragmentBuffer
from .table_token_resolver import TableTokenResolver
from .token_substitution_engine import TokenSubstitutionEngine
from .token_substitution_pipeline import TokenSubstitutionPipeline

logger = logging.getLogger(__name__)

_STAGE4_COMPONENT_NAME = "stage4.assembly_and_output"
_PAGE_JOIN_SEPARATOR = "\n"


class StreamingDocumentAssembler:
    """
    The Stage 4 entry point.

    Build via :meth:`build`.  Drive via :meth:`assemble(stream)`.
    """

    def __init__(
        self,
        *,
        job: ConversionJob,
        figure_summary_provider: AbstractFigureSummaryProvider,
        substitution_pipeline: TokenSubstitutionPipeline,
        cleaner: AssembledMarkdownOutputCleaner,
        output_sink: AbstractMarkdownOutputSink,
        table_token_resolver: TableTokenResolver,
        summary_builder: ConversionSummaryBuilder,
        assembly_config: AssemblyConfig,
    ) -> None:
        self._job = job
        self._figure_summary_provider = figure_summary_provider
        self._substitution_pipeline = substitution_pipeline
        self._cleaner = cleaner
        self._output_sink = output_sink
        self._table_token_resolver = table_token_resolver
        self._summary_builder = summary_builder
        self._degraded_placeholder = assembly_config.degraded_mode_placeholder

    # ------------------------------------------------------------------
    # Factory — composition root
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        job: ConversionJob,
        assembly_config: AssemblyConfig,
        fault_tolerance_config: FaultToleranceConfig,
        figure_summary_provider: AbstractFigureSummaryProvider,
        output_markdown_path: Path | None = None,
    ) -> Self:
        resolved_output_path = (
            output_markdown_path
            if output_markdown_path is not None
            else job.output_dir / f"{job.job_id}.md"
        )

        figure_resolver = FigureTokenResolver(
            figure_summary_provider=figure_summary_provider,
            assembly_config=assembly_config,
            fault_tolerance_config=fault_tolerance_config,
        )
        table_fragment_buffer = TableFragmentBuffer()
        table_resolver = TableTokenResolver(
            table_fragment_buffer=table_fragment_buffer
        )
        substitution_pipeline = TokenSubstitutionPipeline(
            token_resolvers=[figure_resolver, table_resolver],
            substitution_engine=TokenSubstitutionEngine(),
        )
        cleaner = AssembledMarkdownOutputCleaner(assembly_config=assembly_config)
        output_sink = AtomicMarkdownOutputFlusher(
            output_markdown_path=resolved_output_path,
            assembly_config=assembly_config,
        )

        return cls(
            job=job,
            figure_summary_provider=figure_summary_provider,
            substitution_pipeline=substitution_pipeline,
            cleaner=cleaner,
            output_sink=output_sink,
            table_token_resolver=table_resolver,
            summary_builder=ConversionSummaryBuilder(),
            assembly_config=assembly_config,
        )

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def run(self, page_stream) -> Path:
        """
        Consume ``page_stream`` to completion and publish the assembled Markdown.

        Returns the on-disk path of the published ``.md``.  Figure-summary
        counters are *not* required here — they are folded in afterwards
        via :meth:`build_conversion_summary` so the caller can drive the
        Stage 3 ``drain_and_close`` between the two calls and keep the
        cause-effect ordering explicit.

        ``page_stream`` is anything async-iterable yielding
        :class:`PageResult` (the orchestrator's
        ``DocumentConversionStream.page_results`` satisfies this).
        """
        self._summary_builder.mark_started()
        ordered_pages = OrderedPageStreamConsumer(
            page_stream, first_page=1
        ).iter()

        is_first_page = True
        async for page in ordered_pages:
            cleaned = await self._process_one_page(page)
            if not is_first_page:
                await self._output_sink.append(_PAGE_JOIN_SEPARATOR)
            await self._output_sink.append(cleaned)
            is_first_page = False
            self._summary_builder.record_page(engine=page.engine_used)
            logger.info(
                "page_assembled",
                extra={
                    "page_number": page.page_number,
                    "engine_used": page.engine_used.value,
                    "is_degraded": page.is_degraded,
                },
            )

        await self._append_unclosed_table_fragments_footer()
        return await self._output_sink.finalize()

    def build_conversion_summary(
        self,
        *,
        output_markdown_path: Path,
        figures_summarized: int = 0,
        figures_deduplicated: int = 0,
        figures_failed: int = 0,
    ) -> ConversionSummary:
        """
        Build the final :class:`ConversionSummary`.

        Must be called *after* :meth:`run`.  Figure counters come from the
        Stage 3 :class:`FigureSummarizationCounters` returned by
        ``DocumentConversionStream.finalize``; pass zeros when Stage 3 is
        disabled or when assembling against a pre-baked summary store
        (standalone smoke tests).
        """
        return self._summary_builder.build(
            job=self._job,
            output_markdown_path=output_markdown_path,
            figures_summarized=figures_summarized,
            figures_deduplicated=figures_deduplicated,
            figures_failed=figures_failed,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _process_one_page(self, page: PageResult) -> str:
        substituted = await self._substitution_pipeline.resolve_and_substitute(page)
        return self._cleaner.clean_page(substituted)

    async def _append_unclosed_table_fragments_footer(self) -> None:
        # Tables that never closed are surfaced as a footer block so the
        # rows are not silently lost.  This is a visible, auditable
        # outcome — never a silent drop.
        unclosed = self._table_token_resolver.unclosed_fragment_summary_markdown(
            degraded_placeholder=self._degraded_placeholder
        )
        if not unclosed:
            return
        footer_lines = ["\n---\n\n## Unclosed Table Fragments\n"]
        for start_page in sorted(unclosed):
            footer_lines.append(
                f"\n### Table started on page {start_page}\n\n{unclosed[start_page]}\n"
            )
        for line in footer_lines:
            await self._output_sink.append(line)
        logger.warning(
            "unclosed_table_fragments_footer_emitted",
            extra={"start_pages": sorted(unclosed.keys())},
        )
