"""Pipeline logging configuration and logger factory."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from ..contracts import ObservabilityConfig

_configured = False
_LOG_RECORD_FIELDS = set(
    logging.LogRecord(
        name="",
        level=0,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__
)


class _JSONLogFormatter(logging.Formatter):
    """Serialize log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _LOG_RECORD_FIELDS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_pipeline_logging(config: ObservabilityConfig) -> None:
    """Configure root logging once for the current process."""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    if config.structured_logging:
        handler.setFormatter(_JSONLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
        )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(config.log_level.value)
    _configured = True


def get_pipeline_logger(name: str) -> logging.Logger:
    """Return a logger after ensuring default pipeline logging is configured."""
    if not _configured:
        configure_pipeline_logging(ObservabilityConfig())
    return logging.getLogger(name)
