"""Structured logger for D-085 (native AWS CloudWatch + X-Ray observability, no separate tool).

Mirrors heediq-shared/src/logger.ts's JSON shape and PII denylist — this worker is Python and
can't import the TS package, so the contract is hand-mirrored here the same way models.py already
hand-mirrors @heediq/shared's schemas (D-068). Correlation is by source_id (job.source_id), same
convention as the TS services.

Level filtering (D-093): default threshold is "info" in every environment — "debug" is the only
level silent by default. Read from LOG_LEVEL on each write (this is a one-shot batch task, not a
long-lived process, so there's no cold-start caching benefit) so ops can flip the env var to
"debug" for a rerun without a code change.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

_REDACTED = "[REDACTED]"
_DENYLIST = ("transcript", "email", "audiourl", "password", "token", "secret", "authorization")
_LEVEL_ORDER = {"debug": 0, "info": 1, "warn": 2, "error": 3}


def _resolve_threshold() -> str:
    raw = os.environ.get("LOG_LEVEL", "").lower()
    return raw if raw in _LEVEL_ORDER else "info"


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
        if _LEVEL_ORDER[level] < _LEVEL_ORDER[_resolve_threshold()]:
            return
        line = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "service": self._service,
            "message": message,
            **_redact(meta),
        }
        stream = sys.stderr if level in ("warn", "error") else sys.stdout
        print(json.dumps(line), file=stream)

    def debug(self, message: str, **meta: Any) -> None:
        self._write("debug", message, **meta)

    def info(self, message: str, **meta: Any) -> None:
        self._write("info", message, **meta)

    def warn(self, message: str, **meta: Any) -> None:
        self._write("warn", message, **meta)

    def error(self, message: str, **meta: Any) -> None:
        self._write("error", message, **meta)


def create_logger(service: str) -> StructuredLogger:
    return StructuredLogger(service)
