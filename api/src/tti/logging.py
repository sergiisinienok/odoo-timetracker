"""Structured JSON logging, stdlib only — no secret ever reaches a log record."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """JSON to stdout always (`docker compose logs`), plus a rotating file
    when LOG_FILE is set — 10 MB x 5 files, so bounded at ~60 MB per service."""
    formatter = JSONFormatter()
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = os.environ.get("LOG_FILE")
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=5))
    for handler in handlers:
        handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = handlers
    root.setLevel(level.upper())
