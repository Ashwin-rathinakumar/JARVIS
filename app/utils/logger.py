import logging
import os
import re
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "jarvis.log"


def redact_secrets(value):
    text = str(value)
    text = re.sub(r"(?i)(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)\bBearer\s+[^\s,'\"}]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\b(?:sk-|ghp_|github_pat_|hf_)[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|password|token|secret)[\w-]*[\"']?\s*[:=]\s*[\"']?)[^\s,\"'}]+", r"\1[REDACTED]", text)
    return text


class SecretFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


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
        file_handler.addFilter(SecretFilter())
        logger.addHandler(file_handler)

    return logger


logger = get_logger()
