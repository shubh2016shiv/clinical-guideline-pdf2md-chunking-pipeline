"""
stage2_page_extraction
=======================
STAGE 2 of 4 in the doc2md conversion pipeline — "Do the conversion."

Stage 1 decided *which* engine to use. Stage 2 runs it: it converts the document to
per-page Markdown, streaming one ``PageResult`` per page to the later stages as each
page finishes. It is built to survive the real world — bounded memory, resumable
after a crash, and able to fall back to a second engine when the first one fails.

The three sub-packages map onto the three questions a developer debugging Stage 2
actually asks:

    conversion_engines    — "WHO converts, and did fallback work?"
                            The two engines (Docling in-process, MinerU subprocess)
                            and the resilient wrapper that runs the chosen one and
                            degrades to Docling on failure.

    windowed_extraction   — "HOW do pages flow through?"
                            The window loop: plan the remaining windows, hold the
                            GPU while the engine is alive, convert, checkpoint, and
                            stream results.

    page_result_builders  — "WHAT does each page become?"
                            Shared helpers that turn each engine's raw page output
                            into the canonical PageResult — same Markdown, same figure
                            tokens, same table flags — for both engines.

How it fits with neighbours:
    Stage 1 hands over a ConversionJob + EngineClassification; Stage 2 streams
    PageResult objects to Stage 3 (figure summaries) and Stage 4 (assembly). Progress
    is checkpointed via the ``checkpointing`` package so an interrupted run resumes
    from the last finished window — see ``checkpointing/CHECKPOINTING_DESIGN.md`` and
    ``STAGE_2_PLAN.md`` for the design.

This file re-exports the one class callers need; the rest is internal.
"""

from .windowed_extraction import WindowedPageExtractionOrchestrator

__all__ = [
    "WindowedPageExtractionOrchestrator",
]
