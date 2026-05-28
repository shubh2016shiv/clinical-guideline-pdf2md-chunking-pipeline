"""
convert_document_to_markdown_cli.py
====================================
Thin CLI entry point.  All orchestration lives in ``pipeline_orchestrator.py``.

Default behaviour is the **full pipeline** for each document: Stage 1
(prescan + routing) → Stage 2 (windowed page extraction) → Stage 3
(figure summarization through the local Ollama VLM) → Stage 4 (token
substitution + atomic publication).  The final ``<job_id>.md`` is
written under the job's ``output_dir``; the per-page JSON, extracted
figure PNGs, and ``${FIG:...}`` → ``FigureSummary`` files remain on disk
as the auditable, resumable intermediates.

For the lightweight diagnostic mode (Stage 1 prescan + routing only —
no GPU extraction, no figure summarization, no assembly), pass
``--stage1-only``.

Requires the package to be installed (editable mode)::

    uv sync                      # one-time: install the package

Then invoke via the registered entry point::

    uv run doc2md --doc-folder /path/to/documents
    uv run doc2md --doc-folder /path/to/documents --stage1-only
    uv run doc2md --doc-folder /path/to/documents --recursive

The pipeline is format-agnostic — every file in ``--doc-folder`` whose
extension matches one of the registered ``format_extractors`` (PDF,
DOCX, PPTX, HTML at the time of writing) is converted in turn.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from doc2md_conversion_engine.contracts.configurations.pipeline_config import (
    PipelineConfig,
)
from doc2md_conversion_engine.contracts.exceptions import PipelineError
from doc2md_conversion_engine.contracts.figure_summarization_types import (
    DocumentDomain,
)
from doc2md_conversion_engine.contracts.pipeline_domain_types import (
    ConversionSummary,
)
from doc2md_conversion_engine.pipeline_orchestrator import (
    PipelineOrchestrator,
    Stage1Result,
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


def _print_conversion_summary(summary: ConversionSummary) -> None:
    print(
        f"      {'Figures:':<18s} "
        f"summarized={summary.figures_summarized}  "
        f"deduped={summary.figures_deduplicated}  "
        f"failed={summary.figures_failed}"
    )
    print(f"      {'Assembled MD:':<18s} {summary.output_markdown_path}")
    print(
        f"      {'Stage 4 wall:':<18s} {summary.total_duration_seconds * 1000:.0f} ms"
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
) -> tuple[Stage1Result, ConversionSummary]:
    """
    Run Stage 1 → 2 → 3 → 4 for one document and return the flattened
    Stage 1 result plus the final :class:`ConversionSummary`.

    Delegates to :meth:`PipelineOrchestrator.convert_to_markdown`, which
    owns the full Stage 3 lifecycle (start, drain, finalize) and the
    Stage 4 assembly (token substitution, atomic publish).  The CLI just
    reports what came back.
    """
    summary = await orchestrator.convert_to_markdown(
        doc_path, document_domain=document_domain
    )

    # The CLI surface still uses Stage1Result for display; the orchestrator
    # exposes the resolved job + classification only through the summary, so
    # we shape a Stage1Result purely from public summary fields here.  No
    # re-prescan: ``convert_to_markdown`` already paid that cost.
    stage1_result = Stage1Result(
        document_name=doc_path.name,
        document_path=doc_path,
        job_id=summary.job_id,
        document_type=doc_path.suffix.lstrip(".").lower(),
        file_size_bytes=doc_path.stat().st_size,
        total_pages=summary.total_pages,
        output_dir=summary.output_markdown_path.parent,
        engine=summary.engines_used[0].value if summary.engines_used else "",
        complexity_score=0.0,
        confidence=0.0,
        reason="",
        feature_summary="",
        inferred_requirements=[],
        elapsed_ms=summary.total_duration_seconds * 1000,
    )
    return stage1_result, summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doc2md",
        description=(
            "Document → Markdown conversion CLI.  Default: full pipeline "
            "(Stage 1 prescan + routing → Stage 2 windowed page extraction → "
            "Stage 3 figure summarization → Stage 4 token substitution and "
            "atomic Markdown publication).  Use --stage1-only for the "
            "lightweight routing-diagnostic mode."
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
                result, summary = asyncio.run(
                    _run_full_pipeline(
                        orchestrator, doc_path, document_domain=document_domain
                    )
                )
                _print_result(result)
                _print_conversion_summary(summary)
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
