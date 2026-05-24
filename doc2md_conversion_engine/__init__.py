#!/usr/bin/env python3
"""
doc2md_conversion_engine
=========================
Clinical guideline PDF → Markdown conversion pipeline.

The active codebase lives under ``src/``.  This top-level package exports
only the components that entrypoints need for Stage 1 prescanning.
"""

from __future__ import annotations

__version__ = "2.0.0"

from .src.contracts.configurations.pipeline_config import PipelineConfig
from .src.contracts.exceptions import DocumentError, DocumentTooLargeError
from .src.pipeline_orchestrator import PipelineOrchestrator, Stage1Result

__all__ = [
    "PipelineConfig",
    "PipelineOrchestrator",
    "Stage1Result",
    "DocumentError",
    "DocumentTooLargeError",
]
