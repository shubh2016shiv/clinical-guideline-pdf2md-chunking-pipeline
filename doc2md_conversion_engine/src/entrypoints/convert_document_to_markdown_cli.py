"""
convert_document_to_markdown_cli.py
====================================
Thin CLI entry point.  All orchestration lives in ``pipeline_orchestrator.py``.

Requires the package to be installed (editable mode)::

    uv sync                      # one-time: install the package
    uv run doc2md_conversion_engine/src/entrypoints/convert_document_to_markdown_cli.py \\
        --doc_folder /home/user/Downloads/research_papers

Or via the registered entry point::

    uv run stage1-prescan --doc_folder /home/user/Downloads/research_papers
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from doc2md_conversion_engine.src.contracts.configurations.pipeline_config import (
    PipelineConfig,
)
from doc2md_conversion_engine.src.contracts.exceptions import DocumentError
from doc2md_conversion_engine.src.pipeline_orchestrator import (
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
    if result.ollama_payload:
        candidates = result.ollama_payload.get("visual_candidates_requiring_explanation") or []
        candidate_count = len(candidates) if isinstance(candidates, list) else 0
        engine_rec = result.ollama_payload.get("recommended_structure_engine", "—")
        confidence = result.ollama_payload.get("confidence", 0.0)
        print(f"      {'Ollama decision:':<18s} {engine_rec}  (confidence: {confidence:.0%},  {candidate_count} candidate(s) flagged)")
    print(f"      {'Time:':<18s} {result.elapsed_ms:.0f} ms")
    print(f"      {'Output:':<18s} {result.output_dir}")


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
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight + Stage 1 prescan for doc2md pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--doc-folder",
        type=Path,
        required=True,
        help="Directory containing documents to prescan.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        default=False,
        help="Recurse into subdirectories.",
    )
    args = parser.parse_args(argv)
    root = args.doc_folder.expanduser().resolve()

    orchestrator = PipelineOrchestrator(PipelineConfig())

    _status("🔍", f"Scanning: {root}")
    try:
        paths = orchestrator.collect_documents(root, recursive=args.recursive)
    except DocumentError as exc:
        print(f"\n  ✗  {exc}", file=sys.stderr)
        return 1

    if not paths:
        print(f"\n  ✗  No supported documents in {root}", file=sys.stderr)
        print("      .pdf, .docx, .pptx, .html, .htm", file=sys.stderr)
        return 1

    _status("📋", f"Found {len(paths)} document(s)")

    results: list[Stage1Result] = []
    errors: list[tuple[str, str]] = []
    t_start = time.perf_counter()

    for i, doc_path in enumerate(paths, 1):
        _bar(f"[{i}/{len(paths)}]  {doc_path.name}")
        try:
            result = orchestrator.run_stage1(doc_path)
        except DocumentError as exc:
            _status("⛔", str(exc))
            errors.append((doc_path.name, str(exc)))
            continue
        results.append(result)
        _print_result(result)

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
