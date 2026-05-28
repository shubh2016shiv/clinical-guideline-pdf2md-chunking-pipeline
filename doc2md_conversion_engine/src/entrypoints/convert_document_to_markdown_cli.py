"""
convert_document_to_markdown_cli.py
====================================
Thin CLI entry point.  All orchestration lives in ``pipeline_orchestrator.py``.

Default behaviour is the **full pipeline** for each document: Stage 1
(prescan + routing) → Stage 2 (windowed page extraction) → Stage 3
(figure summarization through the local Ollama VLM).  Stage 4 (assembly)
is not yet wired into this CLI; the per-document outputs (page Markdown,
extracted figure images, ``${FIG:...}`` → ``FigureSummary`` map) are
written to the job's output directory and a future revision will splice
them into a single assembled Markdown file.

For the legacy diagnostic mode (Stage 1 only — what this CLI did
historically), pass ``--stage1-only``.

Requires the package to be installed (editable mode)::

    uv sync                      # one-time: install the package
    uv run doc2md_conversion_engine/src/entrypoints/convert_document_to_markdown_cli.py \\
        --doc-folder /home/user/Downloads/research_papers

Or via the registered entry point::

    uv run stage1-prescan --doc-folder /home/user/Downloads/research_papers
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from doc2md_conversion_engine.src.contracts.configurations.pipeline_config import (
    PipelineConfig,
)
from doc2md_conversion_engine.src.contracts.exceptions import PipelineError
from doc2md_conversion_engine.src.contracts.figure_summarization_types import (
    DocumentDomain,
)
from doc2md_conversion_engine.src.pipeline_orchestrator import (
    PipelineOrchestrator,
    Stage1Result,
)
from doc2md_conversion_engine.src.stage3_figure_summarization import (
    FigureSummarizationCounters,
)

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _bar(label: str, width: int = 70) -> None:
    print(f"\n{'─' * width}")
    print(f"  {label}")
    print(f"{'─' * width}")


def _status(icon: str, message: str) -> None:
    print(f"  {icon}  {message}")


def _print_result(result: Stage1Result) -> None:
    print(f"\n  📄  {result.document_name}")
    print(f"      {'Type:':<18s} {result.document_type.upper()}")
    print(f"      {'Size:':<18s} {result.file_size_bytes / (1024 * 1024):.1f} MB")
    print(f"      {'Job ID:':<18s} {result.job_id[:12]}...")
    print(f"      {'Pages:':<18s} {result.total_pages}")
    print(f"      {'Engine:':<18s} {result.engine}")
    if result.complexity_score:
        print(
            f"      {'Complexity:':<18s} {result.complexity_score:.2f}  "
            f"(confidence: {result.confidence:.0%})"
        )
    else:
        print(f"      {'Routing conf:':<18s} {result.confidence:.0%}")
    print(f"      {'Reason:':<18s} {result.reason}")
    print(f"      {'Features:':<18s} {result.feature_summary}")
    if result.inferred_requirements:
        print(f"      {'Requirements:':<18s} {'; '.join(result.inferred_requirements)}")
    print(f"      {'Time:':<18s} {result.elapsed_ms:.0f} ms")
    print(f"      {'Output:':<18s} {result.output_dir}")


def _print_stage3_counters(counters: FigureSummarizationCounters) -> None:
    print(
        f"      {'Figures:':<18s} "
        f"summarized={counters.figures_summarized}  "
        f"deduped={counters.figures_deduplicated}  "
        f"failed={counters.figures_failed}"
    )


def _print_summary(results: list[Stage1Result], total_elapsed: float) -> None:
    n = len(results)
    by_engine: dict[str, int] = {}
    total_pages = 0
    for r in results:
        by_engine[r.engine] = by_engine.get(r.engine, 0) + 1
        total_pages += r.total_pages

    _bar("SUMMARY")
    print(f"  Documents:  {n}")
    print(f"  Pages:      {total_pages}")
    print(f"  Time:       {total_elapsed:.2f} s")
    if n:
        print(f"  Per doc:    {(total_elapsed / n * 1000):.0f} ms")
    print()
    print("  Engine split:")
    for eng, count in sorted(by_engine.items(), key=lambda x: -x[1]):
        print(f"    {eng:<12s} {count:>3d}  ({count / n * 100:.0f}%)")
    print()


# ---------------------------------------------------------------------------
# Per-document conversion (full pipeline)
# ---------------------------------------------------------------------------


async def _run_full_pipeline(
    orchestrator: PipelineOrchestrator,
    doc_path: Path,
    *,
    document_domain: DocumentDomain,
) -> tuple[Stage1Result, FigureSummarizationCounters, int]:
    """
    Run Stage 1 → 2 → 3 for one document and return the flattened result,
    Stage 3 counters, and number of pages streamed.

    Uses ``PipelineOrchestrator.start_conversion`` — the Stage-3-wired
    entry point — and is careful to call ``finalize()`` even when the page
    loop raises, so Stage 3's worker tasks never leak past this call.
    """
    stream = orchestrator.start_conversion(doc_path, document_domain=document_domain)

    pages_streamed = 0
    try:
        async for page_result in stream.page_results:
            pages_streamed += 1
            print(
                f"      [page {page_result.page_number:>3}] "
                f"engine={page_result.engine_used.value} "
                f"figures={len(page_result.figures)} "
                f"tables={len(page_result.tables)} "
                f"ms={page_result.duration_ms}",
                flush=True,
            )
    finally:
        counters = await stream.finalize()

    # Flatten the live job into the Stage1Result the rest of the CLI expects.
    # ``run_stage1`` would re-do the prescan; we already paid that cost via
    # ``start_conversion``, so we build the same dataclass directly from the
    # ConversionJob / EngineClassification on the stream.
    stage1_result = Stage1Result(
        document_name=doc_path.name,
        document_path=doc_path,
        job_id=stream.job.job_id,
        document_type=stream.job.document_type.value,
        file_size_bytes=doc_path.stat().st_size,
        total_pages=stream.job.total_pages or pages_streamed,
        output_dir=stream.job.output_dir,
        engine=stream.classification.engine.value,
        complexity_score=stream.classification.complexity_score,
        confidence=stream.classification.confidence,
        reason=stream.classification.reason,
        feature_summary="",
        inferred_requirements=[],
        elapsed_ms=0.0,
    )
    return stage1_result, counters, pages_streamed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Document → Markdown conversion CLI.  Default: full pipeline "
            "(Stage 1 prescan + Stage 2 page extraction + Stage 3 figure "
            "summarization).  Use --stage1-only for the lightweight "
            "diagnostic mode."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--doc-folder",
        type=Path,
        required=True,
        help="Directory containing documents to convert.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        default=False,
        help="Recurse into subdirectories.",
    )
    parser.add_argument(
        "--stage1-only",
        action="store_true",
        default=False,
        help=(
            "Run Stage 1 (prescan + routing) only.  No GPU extraction, no "
            "figure summarization.  Useful for routing diagnostics across a "
            "large corpus."
        ),
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=DocumentDomain.AUTO.value,
        choices=[d.value for d in DocumentDomain],
        help=(
            "Document-domain hint for the Stage 3 prompt.  'auto' lets the "
            "VLM infer the domain from visual context."
        ),
    )
    args = parser.parse_args(argv)
    root = args.doc_folder.expanduser().resolve()
    document_domain = DocumentDomain(args.domain)

    orchestrator = PipelineOrchestrator(PipelineConfig())

    _status("🔍", f"Scanning: {root}")
    try:
        paths = orchestrator.collect_documents(root, recursive=args.recursive)
    except PipelineError as exc:
        print(f"\n  ✗  {exc}", file=sys.stderr)
        return 1

    if not paths:
        print(f"\n  ✗  No supported documents in {root}", file=sys.stderr)
        print("      .pdf, .docx, .pptx, .html, .htm", file=sys.stderr)
        return 1

    mode = "stage 1 only" if args.stage1_only else f"full pipeline (domain={document_domain.value})"
    _status("📋", f"Found {len(paths)} document(s) — mode: {mode}")

    results: list[Stage1Result] = []
    errors: list[tuple[str, str]] = []
    t_start = time.perf_counter()

    for i, doc_path in enumerate(paths, 1):
        _bar(f"[{i}/{len(paths)}]  {doc_path.name}")
        try:
            if args.stage1_only:
                result = orchestrator.run_stage1(doc_path)
                _print_result(result)
                results.append(result)
            else:
                # Full pipeline: ``asyncio.run`` per document is the right
                # shape here because the CLI processes documents serially
                # and we want each document's Stage 3 worker pool fully
                # drained before starting the next one (avoids GPU-lock
                # contention between consecutive jobs).
                result, counters, _ = asyncio.run(
                    _run_full_pipeline(
                        orchestrator, doc_path, document_domain=document_domain
                    )
                )
                _print_result(result)
                _print_stage3_counters(counters)
                results.append(result)
        except PipelineError as exc:
            # Broad domain safety net: a bad document, an unsupported forced-engine
            # /format combination (ConfigurationError), or any other pipeline failure
            # is reported per-document and the run continues with the rest.
            _status("⛔", str(exc))
            errors.append((doc_path.name, str(exc)))
            continue

    total_elapsed = time.perf_counter() - t_start

    if errors:
        _bar("ERRORS")
        for name, msg in errors:
            print(f"  ⛔  {name}: {msg}")

    if results:
        _print_summary(results, total_elapsed)

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
