"""Logging utilities shared by GUI and backend."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from .config import CONFIG_PATH, SettingsStore


LOG_FILE = Path(CONFIG_PATH).with_name("app.log")


def configure_logging(log_path: Optional[Path] = None) -> Path:
    """Configure root logging with a rotating file handler.

    Returns the resolved path to the log file so that the GUI can surface it.
    """

    settings = SettingsStore()
    target = log_path or Path(settings.data.logs_dir) / "app.log"
    target.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger()
    if logger.handlers:
        return target

    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(target, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return target


__all__ = ["configure_logging", "LOG_FILE"]
