"""Structured audit events for completed page conversions."""

from __future__ import annotations

from ..contracts import ConversionJob, PageResult
from .structured_pipeline_logger import get_pipeline_logger


class PerPageConversionEventLogger:
    """Emits one fixed-schema INFO event for each completed page."""

    def __init__(self, logger_name: str = "doc2md.pipeline.page_events") -> None:
        self._logger = get_pipeline_logger(logger_name)

    def log_page_completed(self, job: ConversionJob, page_result: PageResult) -> None:
        event = {
            "event": "page.converted",
            "job_id": job.job_id,
            "page_number": page_result.page_number,
            "engine_used": page_result.engine_used.value,
            "is_degraded": page_result.is_degraded,
            "figures_count": len(page_result.figures),
            "tables_count": len(page_result.tables),
            "duration_ms": page_result.duration_ms,
        }
        self._logger.info(
            (
                "page.converted job_id=%s page=%s engine=%s degraded=%s "
                "figures=%s tables=%s duration_ms=%s"
            ),
            event["job_id"],
            event["page_number"],
            event["engine_used"],
            event["is_degraded"],
            event["figures_count"],
            event["tables_count"],
            event["duration_ms"],
            extra=event,
        )
