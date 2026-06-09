"""Structured JSON logging for agent_platform."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False)


class StructuredLogger:
    """Wrap stdlib logger — supports extra_fields= and printf-style *args."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    @staticmethod
    def _format_msg(msg: str, args: tuple[Any, ...]) -> str:
        if not args:
            return msg
        try:
            return msg % args
        except (TypeError, ValueError):
            return f"{msg} {' '.join(str(a) for a in args)}"

    def _emit(
        self,
        level: int,
        msg: str,
        *args: Any,
        extra_fields: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._logger.log(
            level,
            self._format_msg(msg, args),
            extra={"extra_fields": extra_fields or {}},
            **kwargs,
        )

    def debug(self, msg: str, *args: Any, extra_fields: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._emit(logging.DEBUG, msg, *args, extra_fields=extra_fields, **kwargs)

    def info(self, msg: str, *args: Any, extra_fields: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._emit(logging.INFO, msg, *args, extra_fields=extra_fields, **kwargs)

    def warning(self, msg: str, *args: Any, extra_fields: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._emit(logging.WARNING, msg, *args, extra_fields=extra_fields, **kwargs)

    def error(self, msg: str, *args: Any, extra_fields: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self._emit(logging.ERROR, msg, *args, extra_fields=extra_fields, **kwargs)

    def exception(self, msg: str, *args: Any, extra_fields: dict[str, Any] | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("exc_info", True)
        self._emit(logging.ERROR, msg, *args, extra_fields=extra_fields, **kwargs)


def get_logger(name: str) -> StructuredLogger:
    """Return a logger configured with JSON formatter (idempotent)."""
    logger = logging.getLogger(f"agent_platform.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return StructuredLogger(logger)
