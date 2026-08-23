"""Centralized logging setup for the content pipeline.

Replaces silent `except Exception: pass` patterns with structured logging.
"""
import logging
import sys

from config.settings import DATA_DIR


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger with timestamped messages and a file handler."""
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)

    # File handler
    file_handler = logging.FileHandler(log_dir / "pipeline.log")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if setup_logging is called multiple times
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers):
        root.addHandler(console)
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a logger with the given dotted name."""
    return logging.getLogger(name)
