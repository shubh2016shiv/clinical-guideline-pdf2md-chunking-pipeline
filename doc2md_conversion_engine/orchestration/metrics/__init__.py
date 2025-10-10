#!/usr/bin/env python3
"""
Metrics Package

This package contains performance tracking and metrics collection
components for monitoring document processing operations.

Exported Classes:
    - PerformanceTracker: Tracks and reports performance metrics
    - PerformanceMetrics: Container for raw metrics data

Usage:
    from doc2md_conversion_engine.orchestration.metrics import (
        PerformanceTracker,
        PerformanceMetrics
    )
    
    tracker = PerformanceTracker()
    tracker.record_task_completion(success=True, duration=5.2)
    summary = tracker.get_summary()
"""

from .performance_tracker import PerformanceTracker, PerformanceMetrics

__all__ = [
    "PerformanceTracker",
    "PerformanceMetrics",
]




