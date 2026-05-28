"""
engine_bootstrap
================
The untimed "get the engine ready" layer that sits before timed conversion work.

A timeout is only honest if it bounds *work*. This package pulls the slow, unbounded,
do-it-once activities — checking the engine's tools are installed, downloading model
weights, confirming the environment can run it — out of the engine lifecycle, so they
no longer hide inside a "startup timeout" and fire on a healthy-but-still-downloading
engine. Bootstrap runs first and untimed; only afterwards do ``start()`` (load cached
models) and ``convert_window()`` (extract pages) run under deadlines that finally mean
what they say.

Pieces:

    AbstractEngineBootstrap / EngineReadinessReport / EngineBootstrapError
        — the contract, its result, and its failure type.
    MinerUEngineBootstrap / DoclingEngineBootstrap
        — per-engine preparedness (tool checks + the right model download).
    EngineBootstrapSelector
        — the front door: engine choice → the bootstrap that prepares it.

NOTE: this package is intentionally NOT wired into the pipeline yet. It is a complete,
standalone preparedness layer ready to be invoked before the engine lifecycle once the
integration point is decided.
"""

from .docling_engine_bootstrap import DoclingEngineBootstrap
from .engine_bootstrap_interface import (
    AbstractEngineBootstrap,
    EngineBootstrapError,
    EngineReadinessReport,
)
from .engine_bootstrap_selector import EngineBootstrapSelector
from .mineru_backend_ladder import (
    configured_ladder,
    model_families_for_rungs,
    resolve_reachable_rungs,
    rung_model_family,
)
from .mineru_engine_bootstrap import MinerUEngineBootstrap

__all__ = [
    "AbstractEngineBootstrap",
    "EngineReadinessReport",
    "EngineBootstrapError",
    "MinerUEngineBootstrap",
    "DoclingEngineBootstrap",
    "EngineBootstrapSelector",
    # The shared backend-ladder resolver, used by the MinerU engine too.
    "configured_ladder",
    "resolve_reachable_rungs",
    "model_families_for_rungs",
    "rung_model_family",
]
