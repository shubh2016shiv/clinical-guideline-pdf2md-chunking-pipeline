"""Prometheus-style metrics registry for pipeline instrumentation."""

from __future__ import annotations

import importlib
from typing import Any

from ..contracts import ObservabilityConfig


class PipelineMetricsRegistry:
    """Small wrapper around prometheus_client with no-op disabled mode."""

    def __init__(self, config: ObservabilityConfig) -> None:
        self._enabled = config.metrics_enabled
        self._metrics: dict[str, Any] = {}
        if self._enabled:
            self._create_metrics()

    def record_page_processed(self, *, engine: str, degraded: bool) -> None:
        self._counter("pages_processed_total").labels(
            engine=engine,
            degraded=str(degraded).lower(),
        ).inc()

    def record_page_failed(self, *, engine: str) -> None:
        self._counter("pages_failed_total").labels(engine=engine).inc()

    def record_figure_summarized(self, *, status: str) -> None:
        self._counter("figures_summarized_total").labels(status=status).inc()

    def observe_extraction_window_duration(self, *, engine: str, seconds: float) -> None:
        self._histogram("extraction_window_duration_seconds").labels(engine=engine).observe(
            seconds
        )

    def observe_llm_batch_duration(self, *, seconds: float) -> None:
        self._histogram("llm_batch_duration_seconds").observe(seconds)

    def set_circuit_breaker_state(self, *, engine: str, state: int | float) -> None:
        self._gauge("circuit_breaker_state").labels(engine=engine).set(state)

    def _create_metrics(self) -> None:
        prometheus_client = importlib.import_module("prometheus_client")
        counter = prometheus_client.Counter
        histogram = prometheus_client.Histogram
        gauge = prometheus_client.Gauge

        self._metrics = {
            "pages_processed_total": counter(
                "pages_processed_total",
                "Total pages successfully processed.",
                ["engine", "degraded"],
            ),
            "pages_failed_total": counter(
                "pages_failed_total",
                "Total pages that failed during extraction.",
                ["engine"],
            ),
            "figures_summarized_total": counter(
                "figures_summarized_total",
                "Total figure summarization outcomes.",
                ["status"],
            ),
            "extraction_window_duration_seconds": histogram(
                "extraction_window_duration_seconds",
                "Extraction window duration in seconds.",
                ["engine"],
            ),
            "llm_batch_duration_seconds": histogram(
                "llm_batch_duration_seconds",
                "Vision LLM batch duration in seconds.",
            ),
            "circuit_breaker_state": gauge(
                "circuit_breaker_state",
                "Circuit breaker state encoded by the caller.",
                ["engine"],
            ),
        }

    def _counter(self, name: str) -> Any:
        return self._metric(name)

    def _histogram(self, name: str) -> Any:
        return self._metric(name)

    def _gauge(self, name: str) -> Any:
        return self._metric(name)

    def _metric(self, name: str) -> Any:
        if not self._enabled:
            return _NoOpMetric()
        return self._metrics[name]


class _NoOpMetric:
    def labels(self, **labels: object) -> _NoOpMetric:
        return self

    def inc(self, amount: float = 1.0) -> None:
        return None

    def observe(self, amount: float) -> None:
        return None

    def set(self, value: float) -> None:
        return None
