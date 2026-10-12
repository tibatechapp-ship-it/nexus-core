#!/usr/bin/env python3
"""
HiveLoop-X Log Redaction
========================
Prevent secrets from being written into logs.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

PATTERNS = [
    re.compile(r"bot[0-9]{6,}:[A-Za-z0-9_-]{20,}"),
    re.compile(r"gsk_[A-Za-z0-9_]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"mstrl_[A-Za-z0-9_]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

REPLACEMENT = "[REDACTED_SECRET]"

QUIET_LOGGERS = [
    "httpx",
    "httpcore",
    "telegram",
    "telegram.ext",
    "apscheduler",
]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True

        redacted = message
        for pattern in PATTERNS:
            redacted = pattern.sub(REPLACEMENT, redacted)

        if redacted != message:
            record.msg = redacted
            record.args = ()

        return True


_installed = False


def install(
    root_level: int = logging.INFO,
    quiet_loggers: Iterable[str] = QUIET_LOGGERS,
) -> None:
    global _installed

    if _installed:
        return

    root = logging.getLogger()
    root.setLevel(root_level)
    root.addFilter(RedactingFilter())

    for name in quiet_loggers:
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        logger.addFilter(RedactingFilter())

    _installed = True
