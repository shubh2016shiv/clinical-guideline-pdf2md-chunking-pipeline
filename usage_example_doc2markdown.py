"""Usage example: convert a single document to assembled Markdown.

The pipeline is format- and domain-agnostic. The set of supported file
formats is whatever is registered under
``doc2md_conversion_engine/stage1_document_prescanning/feature_extraction/format_extractors/``
— at the time of writing: PDF, DOCX, PPTX, HTML. Stage 1 inspects the
file's bytes, picks the matching feature extractor, and routes the
document to the extraction engine best suited for its complexity. Stages
2-4 do not know or care which format the document came from.

The ``--domain`` flag is a *content* hint passed only to the Stage 3
figure-summarisation prompt; the rest of the pipeline ignores it. The
allowed values are exactly the members of ``DocumentDomain`` — leave it
at ``auto`` unless you know the corpus a priori.

Usage
-----
::

    python usage_example_doc2markdown.py /path/to/document.<ext>
    python usage_example_doc2markdown.py /path/to/document.<ext> --domain auto
    python usage_example_doc2markdown.py /path/to/document.<ext> --domain <one_of_DocumentDomain>

Where the artefacts land
------------------------
``PipelineOrchestrator.convert_to_markdown`` writes everything under the
job's ``output_dir`` (a hash-keyed directory inside the configured storage
root).  After a successful run::

    <output_dir>/<job_id>.md                  # final assembled Markdown
    <output_dir>/window_*/page_*.json         # per-page Stage 2 outputs
    <output_dir>/window_*/figure_*.png        # extracted figure images
    <output_dir>/.figure_summaries/*.json     # per-token Stage 3 results
    <output_dir>/.figure_cache/*.json         # sha256 dedup cache

The script prints the final path so the caller does not have to guess.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
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
from doc2md_conversion_engine.pipeline_orchestrator import PipelineOrchestrator


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="usage_example_doc2markdown",
        description=(
            "Run the full Stage 1 → 4 pipeline on a single document and "
            "print the resulting ConversionSummary.  Supported formats are "
            "discovered from the format_extractors package: PDF, DOCX, "
            "PPTX, HTML."
        ),
    )
    parser.add_argument(
        "document_path",
        type=Path,
        help="Absolute or relative path to the source document.",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=DocumentDomain.AUTO.value,
        choices=[d.value for d in DocumentDomain],
        help=(
            "Document-domain hint passed to the Stage 3 figure-summarisation "
            "prompt.  'auto' lets the VLM infer the domain from visual "
            "context — the correct choice for mixed or unknown corpora.  "
            "Pass any other DocumentDomain member to bias the prompt when "
            "the corpus is known a priori."
        ),
    )
    return parser.parse_args(argv)


def _print_conversion_summary(summary: ConversionSummary) -> None:
    print(f"[done] job_id={summary.job_id[:12]}...", flush=True)
    print(f"[done] pages={summary.total_pages}", flush=True)
    print(
        f"[done] figures: summarized={summary.figures_summarized} "
        f"deduped={summary.figures_deduplicated} "
        f"failed={summary.figures_failed}",
        flush=True,
    )
    print(
        f"[done] engines={[e.value for e in summary.engines_used]} "
        f"duration={summary.total_duration_seconds:.2f}s",
        flush=True,
    )
    print(f"[done] final markdown -> {summary.output_markdown_path}", flush=True)


async def _run(document_path: Path, document_domain: DocumentDomain) -> int:
    orchestrator = PipelineOrchestrator(PipelineConfig())
    print(
        f"[run] convert_to_markdown: {document_path.name} "
        f"(domain={document_domain.value})",
        flush=True,
    )
    summary = await orchestrator.convert_to_markdown(
        document_path, document_domain=document_domain
    )
    _print_conversion_summary(summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    document_path = args.document_path.expanduser().resolve()
    document_domain = DocumentDomain(args.domain)

    if not document_path.is_file():
        print(f"[error] not a file: {document_path}", file=sys.stderr)
        return 2

    try:
        return asyncio.run(_run(document_path, document_domain))
    except PipelineError as exc:
        # Bubble pipeline-domain failures (unsupported format, oversized
        # file, engine startup, …) as a non-zero exit so scripted callers
        # can react.  Stack traces stay suppressed because PipelineError
        # subclasses already carry the operator-readable message.
        print(f"[error] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
