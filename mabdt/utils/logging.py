"""Logger helpers for mabdt components.

A thin wrapper around the standard library `logging` module so all engine
components emit through a consistent root logger. Deployments can configure
the root logger (handlers, formatters, level) once at start-up; this module
provides a sensible default if nothing else is configured.
"""

from __future__ import annotations

import logging
import sys

DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_logging_configured = False


def configure_logging(
    level: int = logging.INFO,
    format_string: str | None = None,
    date_format: str | None = None,
    stream: object | None = None,
) -> None:
    """Install a default root-logger handler if none exists.

    Idempotent: safe to call from multiple modules. The first call wins;
    subsequent calls are no-ops as long as the root logger already has a
    handler installed.

    Args:
        level: Root logger level.
        format_string: Log format. Defaults to DEFAULT_FORMAT.
        date_format: Date format. Defaults to DEFAULT_DATE_FORMAT.
        stream: Output stream. Defaults to sys.stdout.
    """
    global _logging_configured

    if _logging_configured:
        return

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler(stream or sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt=format_string or DEFAULT_FORMAT,
                datefmt=date_format or DEFAULT_DATE_FORMAT,
            )
        )
        root_logger.addHandler(handler)
        root_logger.setLevel(level)

    _logging_configured = True


def get_logger(name: str, level: int | None = None) -> logging.Logger:
    """Return a named logger; ensure default root config is in place.

    Args:
        name: Logger name, typically `__name__` of the calling module.
        level: Optional explicit level. If None, inherit from ancestors.

    Returns:
        A standard `logging.Logger` instance.
    """
    configure_logging()
    logger = logging.getLogger(name)
    if level is not None:
        logger.setLevel(level)
    return logger
