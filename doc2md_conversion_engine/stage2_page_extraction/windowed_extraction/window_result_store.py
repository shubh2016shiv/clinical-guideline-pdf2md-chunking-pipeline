"""
stage2_page_extraction/windowed_extraction/window_result_store.py
=================================================================
Stage 2 · persist each window's extracted pages, and read them back on resume.

A ``PageResult`` is not only streamed downstream — it is also written to the window's
result folder on disk. Two reasons, both essential to a resumable pipeline:

  * **Resume needs the pages back.** When a run is interrupted and restarts, the pages
    from already-completed windows still have to reach Stage 4 (the assembler needs
    every page). They are not re-extracted — that would waste the GPU time the
    checkpoint exists to save — they are read back from here and re-emitted.
  * **The checkpoint points here.** Each ``WindowRecord`` records a ``result_dir``;
    these files are what that directory is pointing at, and what the resume loader
    checks for when validating that a completed window's results are really present.

One JSON file per page (``page_0007.json`` = the full ``PageResult``), zero-padded so
the files sort in page order. The figure PNGs already written alongside them are
referenced by absolute path inside each ``PageResult``.
"""

from __future__ import annotations

from pathlib import Path

from ...contracts.pipeline_domain_types import PageResult

_PAGE_FILE_PREFIX = "page_"
_PAGE_FILE_SUFFIX = ".json"


def persist_page_result(window_output_dir: Path, page_result: PageResult) -> None:
    """
    Write one ``PageResult`` to its window folder as JSON.

    Called as each page completes so a window's finished pages are durable before the
    window is checkpointed. The file name is page-numbered and zero-padded so the
    folder lists in reading order.
    """
    window_output_dir.mkdir(parents=True, exist_ok=True)
    page_file = window_output_dir / f"{_PAGE_FILE_PREFIX}{page_result.page_number:04d}{_PAGE_FILE_SUFFIX}"
    page_file.write_text(page_result.model_dump_json(), encoding="utf-8")


def load_window_page_results(window_output_dir: Path) -> list[PageResult]:
    """
    Read back all persisted ``PageResult`` objects for a window, in page order.

    Used on resume to replay already-completed windows downstream without
    re-extracting them. Returns an empty list when the folder holds no page files.
    """
    page_files = sorted(window_output_dir.glob(f"{_PAGE_FILE_PREFIX}*{_PAGE_FILE_SUFFIX}"))
    return [
        PageResult.model_validate_json(page_file.read_text(encoding="utf-8"))
        for page_file in page_files
    ]
