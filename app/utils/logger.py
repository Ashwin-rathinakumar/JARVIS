import logging
import os
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "jarvis.log"


def get_logger(name: str = "JARVIS") -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(getattr(logging, os.environ.get("JARVIS_LOG_LEVEL", "INFO").upper(), logging.INFO))

        # File handler
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


logger = get_logger()
