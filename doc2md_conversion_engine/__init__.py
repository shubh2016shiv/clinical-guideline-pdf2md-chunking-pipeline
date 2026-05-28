#!/usr/bin/env python3
"""
doc2md_conversion_engine
=========================
Format-agnostic document-to-Markdown conversion pipeline.

Layout (canonical Python package shape)
---------------------------------------
Modules live directly under this package — no ``src/`` wrapper.  Browsing
the top of the package shows the architecture at a glance::

    doc2md_conversion_engine/
    ├── pipeline_orchestrator.py          # composition root (the only entry point)
    ├── settings.yaml                     # operator-tunable config
    ├── entrypoints/                      # CLI(s) that drive the orchestrator
    ├── contracts/                        # interfaces, types, exceptions, config schema
    ├── engine_bootstrap/                 # engine readiness checks
    ├── fault_tolerance/                  # timeouts, retries, circuit breaker
    ├── file_upload_management/           # intake, staging, hashing
    ├── gpu_resource_management/          # GPU lock, VRAM monitor
    ├── observability/                    # metrics, structured logging
    ├── checkpointing/                    # windowed checkpoint store
    ├── stage1_document_prescanning/      # routing + feature extraction
    ├── stage2_page_extraction/           # windowed extraction (Docling / MinerU)
    ├── stage3_figure_summarization/      # VLM figure summarization
    └── stage4_assembly_and_output/       # token substitution + atomic publish

This module re-exports the surface most callers need so external code can
import from the package root without reaching into stage subpackages.
"""

from __future__ import annotations

__version__ = "2.0.0"

from .contracts.configurations.pipeline_config import PipelineConfig
from .contracts.exceptions import DocumentError, DocumentTooLargeError
from .pipeline_orchestrator import PipelineOrchestrator, Stage1Result

__all__ = [
    "PipelineConfig",
    "PipelineOrchestrator",
    "Stage1Result",
    "DocumentError",
    "DocumentTooLargeError",
]
