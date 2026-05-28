"""
stage2_page_extraction/conversion_engines
==========================================
The engines that turn a document into Markdown, and the machinery that runs them
dependably.

Two interchangeable engines implement ``AbstractConversionEngine``:

    DoclingInProcessEngine    — cheap, fast, runs in this process
    MinerUSubprocessEngine    — heavier, more capable, runs as a child process

They are never used directly. The factory builds the engine Stage 1 chose, wrapped in
the resilient fallback layer, and the rest of Stage 2 drives that single object:

    ConversionEngineFactory   — builds a ready, resilient engine from the job + choice
    ResilientConversionEngine — primary + Docling fallback behind one interface
                                (circuit breaker · retry · timeout)

Callers import ``ConversionEngineFactory`` and treat its product as one engine.
"""

from .conversion_engine_factory import ConversionEngineFactory
from .docling_inprocess_engine import DoclingInProcessEngine
from .mineru_subprocess_engine import MinerUSubprocessEngine
from .resilient_conversion_engine import ResilientConversionEngine

__all__ = [
    "ConversionEngineFactory",
    "ResilientConversionEngine",
    "DoclingInProcessEngine",
    "MinerUSubprocessEngine",
]
