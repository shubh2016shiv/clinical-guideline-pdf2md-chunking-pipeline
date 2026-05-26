"""
stage2_page_extraction/windowed_extraction
===========================================
The loop that moves a document through an engine, window by window.

Three collaborators:

    WindowedPageExtractionOrchestrator — the conductor: resume → plan → convert →
                                         checkpoint → stream PageResults
    plan_remaining_windows / PageWindow — pure logic: which page windows are left
    GpuWindowScheduler                 — one engine on the GPU at a time, per window

The orchestrator is the public entry point; the planner and scheduler are its
internal collaborators, exposed here for direct testing.
"""

from .gpu_window_scheduler import GpuWindowScheduler
from .page_window_planner import PageWindow, plan_remaining_windows
from .windowed_page_extraction_orchestrator import WindowedPageExtractionOrchestrator

__all__ = [
    "WindowedPageExtractionOrchestrator",
    "plan_remaining_windows",
    "PageWindow",
    "GpuWindowScheduler",
]
