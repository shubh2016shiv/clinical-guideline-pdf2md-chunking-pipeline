"""
stage4_assembly_and_output/conversion_summary_builder.py
=========================================================
Build the final :class:`ConversionSummary` row.

Stage 4 is the only stage that emits a ConversionSummary; this builder
isolates the construction so the streaming assembler stays focused on
the produce-substitute-write loop.

Sources of each field
---------------------
* ``job_id``, ``output_markdown_path`` — known by the assembler.
* ``total_pages`` — counted as the stream is consumed.
* ``figures_summarized`` / ``figures_deduplicated`` / ``figures_failed`` —
  carried in from Stage 3's :class:`FigureSummarizationCounters`.  Stage 4
  owns no figure counters of its own (decorative drops are a routing
  decision, not a failure).
* ``engines_used`` — collected from each :class:`PageResult.engine_used`.
* ``total_duration_seconds`` — wall-clock between ``mark_started`` and
  ``build``.

Decoratives dropped vs. failed
------------------------------
A dropped decorative is *successful* summarisation that Stage 4 chose not
to publish — it is already counted under ``figures_summarized`` by
Stage 3.  Adding a Stage-4-side "dropped" counter would double-count.
The cleaner / log channel surfaces the drop for auditability instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts import (
    ConversionJob,
    ConversionSummary,
    ExtractionEngine,
)


@dataclass
class _StreamingAssemblyAccumulator:
    """Mutable state collected while pages stream through Stage 4."""

    total_pages: int = 0
    engines_seen: set[ExtractionEngine] = field(default_factory=set)
    started_monotonic_seconds: float | None = None

    def mark_started(self) -> None:
        self.started_monotonic_seconds = time.monotonic()

    def record_page(self, *, engine: ExtractionEngine) -> None:
        self.total_pages += 1
        self.engines_seen.add(engine)

    def elapsed_seconds(self) -> float:
        if self.started_monotonic_seconds is None:
            return 0.0
        return time.monotonic() - self.started_monotonic_seconds


class ConversionSummaryBuilder:
    """Collect per-page facts and emit the final :class:`ConversionSummary`."""

    def __init__(self) -> None:
        self._accumulator = _StreamingAssemblyAccumulator()

    def mark_started(self) -> None:
        self._accumulator.mark_started()

    def record_page(self, *, engine: ExtractionEngine) -> None:
        self._accumulator.record_page(engine=engine)

    def build(
        self,
        *,
        job: ConversionJob,
        output_markdown_path: Path,
        figures_summarized: int,
        figures_deduplicated: int,
        figures_failed: int,
    ) -> ConversionSummary:
        return ConversionSummary(
            job_id=job.job_id,
            output_markdown_path=output_markdown_path,
            total_pages=self._accumulator.total_pages,
            figures_summarized=figures_summarized,
            figures_deduplicated=figures_deduplicated,
            figures_failed=figures_failed,
            engines_used=sorted(self._accumulator.engines_seen, key=lambda e: e.value),
            total_duration_seconds=self._accumulator.elapsed_seconds(),
        )
