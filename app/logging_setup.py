"""Strukturert JSON-logging til stdout.

Aldri rå telefonnummer, fulle meldinger eller hemmeligheter i loggen.
Pseudonym er HMAC(salt, identifikator) og logges bare som kort prefiks.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    _configured = True


def log(event: str, level: int = logging.INFO, **fields) -> None:
    logging.getLogger("ostfoldbussen").log(level, event, extra={"fields": fields})


def pseudonym_short(pseudonym: str) -> str:
    return (pseudonym or "")[:12]


def elapsed_ms(start: float) -> int:
    return int(round((time.perf_counter() - start) * 1000))
