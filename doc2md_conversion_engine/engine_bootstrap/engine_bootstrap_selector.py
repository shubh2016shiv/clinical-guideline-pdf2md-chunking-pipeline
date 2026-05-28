"""
engine_bootstrap/engine_bootstrap_selector.py
==============================================
Pick the right bootstrap for the engine Stage 1 chose.

A tiny front door, mirroring the conversion-engine factory: hand it an engine choice
and it returns the bootstrap that knows how to prepare that engine. This is the one
place that maps an ``ExtractionEngine`` to its concrete bootstrap, so callers (and a
future wiring step) depend only on the ``AbstractEngineBootstrap`` interface.

Intended use, once wired: run the selected bootstrap's ``ensure_ready()`` — untimed —
before constructing and starting the engine, so the engine's timeouts cover only real
work.
"""

from __future__ import annotations

from ..contracts.configurations.pipeline_config import PipelineConfig
from ..contracts.exceptions import ConfigurationError
from ..contracts.pipeline_domain_types import ExtractionEngine
from .docling_engine_bootstrap import DoclingEngineBootstrap
from .engine_bootstrap_interface import AbstractEngineBootstrap
from .mineru_engine_bootstrap import MinerUEngineBootstrap


class EngineBootstrapSelector:
    """
    Build the bootstrap for a given engine from the pipeline configuration.

    Constructed once with the full ``PipelineConfig``::

        selector = EngineBootstrapSelector(config)
        bootstrap = selector.bootstrap_for(classification.engine)
        report = await bootstrap.ensure_ready()
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config

    def bootstrap_for(self, engine: ExtractionEngine) -> AbstractEngineBootstrap:
        """Return the bootstrap that prepares ``engine``."""
        if engine == ExtractionEngine.DOCLING:
            return DoclingEngineBootstrap(self._config.docling_engine, self._config.gpu)
        if engine == ExtractionEngine.MINERU:
            return MinerUEngineBootstrap(self._config.mineru_engine, self._config.gpu)
        raise ConfigurationError(
            f"No engine bootstrap is registered for {engine.value!r}.",
            context={"engine": engine.value},
        )
