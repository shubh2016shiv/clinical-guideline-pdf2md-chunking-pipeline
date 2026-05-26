"""
stage2_page_extraction/conversion_engines/conversion_engine_factory.py
======================================================================
Stage 2 · build the engine to run from Stage 1's decision, ready and resilient.

The orchestrator should not know that Docling runs in-process while MinerU runs as a
subprocess, nor how to wire a circuit breaker. This factory is the one place that
does. Hand it the job and Stage 1's engine choice, and it returns a single
``AbstractConversionEngine`` — already wrapped in the resilient fallback layer — that
the orchestrator simply uses.

Keeping construction here (and nowhere else) means the concrete engine classes are
imported in exactly one module. Everything else in Stage 2 depends only on the engine
interface, so adding a third engine later touches only this file.

The fallback choice
--------------------
Docling is always the fallback because it is the cheap, dependable engine. When
Stage 1 already chose Docling, there is no different engine to fall back to, so the
resilient wrapper is built with no fallback — a Docling failure then surfaces as an
error rather than silently retrying the same engine.
"""

from __future__ import annotations

from ...contracts.configurations.pipeline_config import PipelineConfig
from ...contracts.conversion_engine_interface import AbstractConversionEngine
from ...contracts.exceptions import ConfigurationError
from ...contracts.pipeline_domain_types import (
    ConversionJob,
    EngineClassification,
    ExtractionEngine,
)
from ...fault_tolerance import (
    AsyncOperationTimeoutGuard,
    EngineCircuitBreaker,
    ExponentialBackoffRetry,
)
from .docling_inprocess_engine import DoclingInProcessEngine
from .mineru_subprocess_engine import MinerUSubprocessEngine
from .resilient_conversion_engine import ResilientConversionEngine


class ConversionEngineFactory:
    """
    Construct ready-to-run, resilient conversion engines from configuration.

    Built once per pipeline run with the full ``PipelineConfig``::

        factory = ConversionEngineFactory(config)
        engine = factory.build_engine(job, classification)
        async with engine:
            ...
    """

    def __init__(self, config: PipelineConfig) -> None:
        self._config = config

    def build_engine(
        self,
        job: ConversionJob,
        classification: EngineClassification,
    ) -> AbstractConversionEngine:
        """
        Build the resilient engine for this job: Stage 1's choice plus a fallback.

        The primary is the engine Stage 1 selected; the fallback is Docling (or none,
        when the primary is already Docling). Both are wrapped with the fault-tolerance
        primitives so the orchestrator drives one resilient engine.
        """
        primary = self._build_concrete_engine(classification.engine, job.job_id)
        fallback = (
            None
            if classification.engine == ExtractionEngine.DOCLING
            else self._build_concrete_engine(ExtractionEngine.DOCLING, job.job_id)
        )

        circuit_breaker = EngineCircuitBreaker(
            self._config.fault_tolerance.circuit_breaker,
            component_name=f"stage2.engine.{classification.engine.value}",
        )
        retry = ExponentialBackoffRetry(self._config.fault_tolerance.retry)
        timeout_guard = AsyncOperationTimeoutGuard(self._config.fault_tolerance.timeouts)

        return ResilientConversionEngine(
            primary=primary,
            fallback=fallback,
            circuit_breaker=circuit_breaker,
            retry=retry,
            timeout_guard=timeout_guard,
        )

    def _build_concrete_engine(
        self,
        engine: ExtractionEngine,
        job_id: str,
    ) -> AbstractConversionEngine:
        """Instantiate one concrete engine adapter for the given engine type."""
        if engine == ExtractionEngine.DOCLING:
            return DoclingInProcessEngine(self._config.docling_engine, self._config.gpu, job_id)
        if engine == ExtractionEngine.MINERU:
            return MinerUSubprocessEngine(self._config.mineru_engine, job_id)
        raise ConfigurationError(
            f"No conversion engine adapter is registered for {engine.value!r}.",
            context={"engine": engine.value},
        )
