"""Structured logger for D-085 (native AWS CloudWatch + X-Ray observability, no separate tool).

Mirrors heediq-shared/src/logger.ts's JSON shape and PII denylist — this worker is Python and
can't import the TS package, so the contract is hand-mirrored here the same way models.py already
hand-mirrors @heediq/shared's schemas (D-068). Correlation is by source_id (job.source_id), same
convention as the TS services.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

_REDACTED = "[REDACTED]"
_DENYLIST = ("transcript", "email", "audiourl", "password", "token", "secret", "authorization")


def _is_denylisted(key: str) -> bool:
    lower = key.lower()
    return any(denied in lower for denied in _DENYLIST)


def _redact(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, dict):
        return {k: (_REDACTED if _is_denylisted(k) else _redact(v)) for k, v in value.items()}
    return value


class StructuredLogger:
    def __init__(self, service: str) -> None:
        self._service = service

    def _write(self, level: str, message: str, **meta: Any) -> None:
        line = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "service": self._service,
            "message": message,
            **_redact(meta),
        }
        stream = sys.stderr if level in ("warn", "error") else sys.stdout
        print(json.dumps(line), file=stream)

    def info(self, message: str, **meta: Any) -> None:
        self._write("info", message, **meta)

    def warn(self, message: str, **meta: Any) -> None:
        self._write("warn", message, **meta)

    def error(self, message: str, **meta: Any) -> None:
        self._write("error", message, **meta)


def create_logger(service: str) -> StructuredLogger:
    return StructuredLogger(service)
