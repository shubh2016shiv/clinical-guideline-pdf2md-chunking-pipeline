"""One-off runner: drive the full pipeline Stage 1 → 2 → 3 on one PDF.

Uses ``PipelineOrchestrator.start_conversion`` (the Stage-3-wired entry point)
so every figure on every page is enqueued into the local Ollama VLM and a
``${FIG:...}`` token → ``FigureSummary`` map is written under the job's
output directory.  The legacy ``convert_document`` method exists too but
deliberately skips Stage 3 — use it only when you want a Stage 1+2
diagnostic run with no figure summarization.

After the stream finishes look at:

* ``<job_output_dir>/.figure_summaries/*.json`` — one file per token, what
  Stage 4 will splice into the assembled Markdown.
* ``<job_output_dir>/.figure_cache/*.json`` — sha256-keyed cache of unique
  figure summaries (cheap re-runs).
"""
import asyncio
import sys
from pathlib import Path

from doc2md_conversion_engine.src.contracts.configurations.pipeline_config import PipelineConfig
from doc2md_conversion_engine.src.contracts.figure_summarization_types import DocumentDomain
from doc2md_conversion_engine.src.pipeline_orchestrator import PipelineOrchestrator

DOC = Path("/home/shubham_singh/Projects/docs/research_papers/DeepSeek Multi-Head Latent Attention in Any Transformer-based LLMs.pdf")


async def main() -> int:
    config = PipelineConfig()
    orchestrator = PipelineOrchestrator(config)
    print(f"[run] start_conversion: {DOC.name}", flush=True)

    # ``document_domain`` is a hint passed into the Stage 3 prompt.
    # ``AUTO`` lets the VLM infer the domain from visual context — use a
    # concrete value (e.g. ``DocumentDomain.CLINICAL``) when the corpus is
    # known a priori.
    stream = orchestrator.start_conversion(DOC, document_domain=DocumentDomain.AUTO)
    print(
        f"[stage3] job_id={stream.job.job_id[:12]}... "
        f"output_dir={stream.job.output_dir}",
        flush=True,
    )

    pages = 0
    try:
        async for page_result in stream.page_results:
            pages += 1
            print(
                f"[page] {page_result.page_number:>3} "
                f"engine={page_result.engine_used.value} "
                f"degraded={page_result.is_degraded} "
                f"figures={len(page_result.figures)} tables={len(page_result.tables)} "
                f"md_chars={len(page_result.markdown_with_tokens)} "
                f"ms={page_result.duration_ms}",
                flush=True,
            )
    finally:
        # ``finalize`` is the explicit Stage 3 commit point: it closes the
        # bounded figure queue and waits for every worker to drain.  Must
        # run exactly once, even if the page loop raised — otherwise the
        # worker tasks (and the Ollama call they may be in the middle of)
        # would leak past process shutdown.
        counters = await stream.finalize()
        print(
            f"[stage3] summarized={counters.figures_summarized} "
            f"deduped={counters.figures_deduplicated} "
            f"failed={counters.figures_failed}",
            flush=True,
        )

    print(f"[done] streamed {pages} page(s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
