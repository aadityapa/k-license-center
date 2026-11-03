"""Structured (one JSON object per line) logging, like the previous pino setup."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from .config import config

_LEVELS = {
    "fatal": logging.CRITICAL, "error": logging.ERROR, "warn": logging.WARNING,
    "info": logging.INFO, "debug": logging.DEBUG, "trace": logging.DEBUG, "silent": logging.CRITICAL + 10,
}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "level": record.levelname.lower(),
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            out.update(extra)
        if record.exc_info:
            out["err"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class _PrettyFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        t = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        extra = getattr(record, "fields", None)
        tail = ""
        if isinstance(extra, dict) and extra:
            tail = " " + " ".join(f"{k}={v}" for k, v in extra.items())
        s = f"[{t}] {record.levelname:<5} {record.getMessage()}{tail}"
        if record.exc_info:
            s += "\n" + self.formatException(record.exc_info)
        return s


_log = logging.getLogger("klicense")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_PrettyFormatter() if config.env == "development" else _JsonFormatter())
_log.addHandler(_handler)
_log.propagate = False
_log.setLevel(_LEVELS["silent"] if config.env == "test" else _LEVELS.get(config.log_level, logging.INFO))


class _Logger:
    """logger.info('message', key=value, ...) — fields are logged alongside the message."""

    def _do(self, level: int, msg: str, exc: bool, fields: dict) -> None:
        if _log.isEnabledFor(level):
            _log.log(level, msg, exc_info=exc, extra={"fields": fields})

    def debug(self, msg: str, **f) -> None: self._do(logging.DEBUG, msg, False, f)
    def info(self, msg: str, **f) -> None: self._do(logging.INFO, msg, False, f)
    def warn(self, msg: str, **f) -> None: self._do(logging.WARNING, msg, False, f)
    warning = warn
    def error(self, msg: str, exc: bool = False, **f) -> None: self._do(logging.ERROR, msg, exc, f)


logger = _Logger()
