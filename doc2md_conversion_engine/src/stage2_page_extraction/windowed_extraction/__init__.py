"""
stage2_page_extraction/windowed_extraction
===========================================
The loop that moves a document through an engine, window by window.

Three collaborators:

    WindowedPageExtractionOrchestrator — the conductor: resume → plan → convert →
                                         checkpoint → stream PageResults
    plan_remaining_windows / PageWindow — pure logic: which page windows are left
    GpuEngineResourceCoordinator       — one live engine owns the GPU at a time

The orchestrator is the public entry point; the planner and scheduler are its
internal collaborators, exposed here for direct testing.
"""

from .gpu_engine_resource_coordinator import GpuEngineResourceCoordinator
from .page_window_planner import PageWindow, plan_remaining_windows
from .windowed_page_extraction_orchestrator import WindowedPageExtractionOrchestrator

__all__ = [
    "WindowedPageExtractionOrchestrator",
    "plan_remaining_windows",
    "PageWindow",
    "GpuEngineResourceCoordinator",
]
