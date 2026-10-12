"""
Secure Logging Setup
====================
Provides a logging filter that automatically masks secrets.

Usage:
    from novamind.security.masking import setup_secure_logging
    setup_secure_logging()  # Call once at app startup
    
    # Now any logger.info("Key: AIza...") will be auto-masked
"""

from __future__ import annotations

import logging
import re


SECRET_REGEX = re.compile(
    r"(AIza[0-9A-Za-z_-]{35}"
    r"|sk-[0-9A-Za-z]{20,}"
    r"|gsk_[0-9A-Za-z]{20,}"
    r"|sk-ant-[0-9A-Za-z_-]{20,}"
    r"|sk-or-[0-9A-Za-z_-]{20,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)


def _mask_match(match):
    """Replace a matched secret with a masked version."""
    s = match.group(0)
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-4:]}"


class SecretMaskingFilter(logging.Filter):
    """
    Logging filter that replaces secret patterns in log records.
    
    Applied to all log records before they are written.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Mask the message
        if isinstance(record.msg, str):
            record.msg = SECRET_REGEX.sub(_mask_match, record.msg)
        
        # Mask args (used in %-formatting)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    SECRET_REGEX.sub(_mask_match, str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: SECRET_REGEX.sub(_mask_match, str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
        
        return True


_installed = False


def setup_secure_logging(level: int = logging.INFO) -> None:
    """
    Install the secret-masking filter on the root logger.
    
    Call this once at the start of your application.
    Safe to call multiple times.
    
    Args:
        level: Root logger level (default INFO)
    """
    global _installed
    if _installed:
        return
    
    root = logging.getLogger()
    root.setLevel(level)
    
    # Add filter to all existing handlers
    for handler in root.handlers:
        handler.addFilter(SecretMaskingFilter())
    
    # Add a default handler if none exists
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(SecretMaskingFilter())
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        root.addHandler(handler)
    
    _installed = True


__all__ = ["setup_secure_logging", "SecretMaskingFilter"]
