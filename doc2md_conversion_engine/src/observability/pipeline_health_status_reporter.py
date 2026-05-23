"""Mutable live health snapshot for a single pipeline run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ..contracts import ConversionJob, ObservabilityConfig


class PipelineStage(StrEnum):
    PRESCAN = "PRESCAN"
    CLASSIFY = "CLASSIFY"
    EXTRACTING = "EXTRACTING"
    SUMMARIZING = "SUMMARIZING"
    ASSEMBLING = "ASSEMBLING"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass
class PipelineHealthStatus:
    job_id: str
    stage: PipelineStage = PipelineStage.PRESCAN
    pages_done: int = 0
    pages_total: int | None = None
    figures_pending: int = 0
    circuit_breaker_open: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "stage": self.stage.value,
            "pages_done": self.pages_done,
            "pages_total": self.pages_total,
            "figures_pending": self.figures_pending,
            "circuit_breaker_open": self.circuit_breaker_open,
            "started_at": self.started_at.isoformat(),
            "last_updated_at": self.last_updated_at.isoformat(),
        }


class PipelineHealthStatusReporter:
    """Maintains a live health snapshot for orchestration or health endpoints."""

    def __init__(self, config: ObservabilityConfig, job: ConversionJob) -> None:
        self._enabled = config.health_check_enabled
        self._status = PipelineHealthStatus(
            job_id=job.job_id,
            pages_total=job.total_pages,
        )

    def update(
        self,
        *,
        stage: PipelineStage | str | None = None,
        pages_done: int | None = None,
        pages_total: int | None = None,
        figures_pending: int | None = None,
        circuit_breaker_open: bool | None = None,
    ) -> None:
        if not self._enabled:
            return

        if stage is not None:
            self._status.stage = PipelineStage(stage)
        if pages_done is not None:
            self._status.pages_done = pages_done
        if pages_total is not None:
            self._status.pages_total = pages_total
        if figures_pending is not None:
            self._status.figures_pending = figures_pending
        if circuit_breaker_open is not None:
            self._status.circuit_breaker_open = circuit_breaker_open
        self._status.last_updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return self._status.to_dict()
