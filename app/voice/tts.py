from abc import ABC, abstractmethod
from typing import List
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from app.config.settings import (
    JARVIS_TTS_ENABLED,
    JARVIS_TTS_RATE,
    JARVIS_TTS_VOLUME,
)
from app.utils.logger import logger

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except Exception as _tts_err:
    PYTTSX3_AVAILABLE = False
    logger.warning(f"pyttsx3 library unavailable: {_tts_err}")


class BaseTTS(ABC):
    """Abstract interface for Text-to-Speech engines."""

    @abstractmethod
    def speak(self, text: str) -> bool:
        """Speak the given text. Returns True if spoken successfully."""
        pass


class Pyttsx3TTS(BaseTTS):
    """
    Local Windows Text-to-Speech provider using pyttsx3 / Windows SAPI.
    Runs 100% offline without external network or API keys.
    """

    def __init__(
        self,
        enabled: bool = JARVIS_TTS_ENABLED,
        rate: int = JARVIS_TTS_RATE,
        volume: float = JARVIS_TTS_VOLUME,
    ):
        self.enabled = enabled
        self.rate = rate
        self.volume = volume
        self.timeout = 90

    # SAPI/pyttsx3's completed callback can end the driver loop before the
    # queued engine.endLoop is drained. A fresh process avoids that stale queue
    # and COM ownership/cache state, and lets us bound a hung native driver.
    _playback_lock = threading.Lock()

    def speak(self, text: str) -> bool:
        """Synthesize and speak text via Windows SAPI."""
        clean_text = (text or "").strip()
        if not clean_text or not self.enabled:
            return False

        with self._playback_lock:
            try:
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).with_name("tts_worker.py"))],
                    input=json.dumps({"text": clean_text, "rate": self.rate, "volume": self.volume}),
                    text=True, encoding="utf-8", capture_output=True,
                    timeout=self.timeout, shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                )
                if result.returncode != 0 or result.stdout.strip() != "TTS_COMPLETED":
                    raise RuntimeError(result.stderr.strip() or "Missing speech completion acknowledgement")
                logger.info("TTS backend=pyttsx3 operation=speak completed=true")
                return True
            except Exception as error:
                # subprocess.run kills and reaps a timed-out worker before
                # releasing the playback lock. Never retry partially spoken text.
                logger.error("[TTS ERROR] backend=pyttsx3 operation=speak error=%s recovery=fresh_worker_next_utterance", error)
                return False


class MockTTS(BaseTTS):
    """Mock TTS engine for unit tests and headless environments."""

    def __init__(self):
        self.spoken_messages: List[str] = []

    def speak(self, text: str) -> bool:
        clean_text = (text or "").strip()
        if clean_text:
            self.spoken_messages.append(clean_text)
            logger.info(f"[MockTTS] Spoke: '{clean_text}'")
            return True
        return False

    def clear(self):
        self.spoken_messages.clear()


def create_tts_provider(enabled: bool = JARVIS_TTS_ENABLED) -> BaseTTS:
    """Factory helper to instantiate TTS provider."""
    return Pyttsx3TTS(enabled=enabled)
