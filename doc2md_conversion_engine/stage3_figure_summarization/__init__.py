"""
stage3_figure_summarization/
============================
Public interface for Stage 3 — figure summarization.

Stage 3 takes the :class:`Figure` items produced by Stage 2 (one per
extracted figure, each carrying a ``${FIG:...}`` token, an image path, a
sha256, and its page coordinates) and, for each one, asks a local Ollama
vision-language model for a faithful, insertion-ready Markdown rendering.
The result is persisted under the token so Stage 4 can substitute it
deterministically.

What to import from here
------------------------
* :class:`FigureSummarizationOrchestrator` — the entry point.  The pipeline
  orchestrator constructs one of these per job via
  :meth:`FigureSummarizationOrchestrator.build` and feeds figures into it.
* :class:`FigureSummarizationCounters` — small data object surfaced at
  ``drain_and_close`` time so the pipeline can populate
  :class:`ConversionSummary` without inspecting Stage 3 internals.

All sub-components (vision client, queue, cache, store, worker pool,
limiter, prompt builder) are deliberately *not* re-exported here.  Callers
that need to swap one out should depend on the abstract interfaces in
``contracts`` and inject the concrete via the orchestrator's ``__init__``;
they should not import the concrete class names from this package.

See ``STAGE_3_PLAN.md`` (co-located) for the architecture and rationale.
"""

from .figure_summarization_orchestrator import FigureSummarizationOrchestrator
from .figure_summarization_worker_pool import FigureSummarizationCounters

__all__ = [
    "FigureSummarizationOrchestrator",
    "FigureSummarizationCounters",
]
