"""Vendor-neutral wake-word and voice-activity interfaces."""
from abc import ABC, abstractmethod
from collections import deque
import re
from threading import Event
from typing import Deque


class WakeWordDetector:
    """Match a wake phrase at the start of an STT transcript, preserving a command."""

    def __init__(self, phrases=("hey jarvis", "okay jarvis", "jarvis")):
        normalized = [r"[\s,.:;!?-]+".join(re.escape(part) for part in phrase.lower().split())
                      for phrase in phrases if phrase.strip()]
        if not normalized:
            raise ValueError("At least one wake phrase is required")
        self._pattern = re.compile(r"^\s*(?:" + "|".join(sorted(normalized, key=len, reverse=True)) +
                                   r")\b[\s,.:;!?-]*(.*)$", re.IGNORECASE)

    def extract_command(self, transcript: str):
        match = self._pattern.match(transcript or "")
        return match.group(1).strip() if match else None

class WakeWordProvider(ABC):
    @abstractmethod
    def wait_for_wake(self, timeout: float) -> bool:
        """Wait up to timeout seconds and return whether a local wake event occurred."""

    def shutdown(self) -> None:
        pass


class TranscriptWakeWordProvider(WakeWordProvider):
    """CPU/STT based wake adapter; records short windows without keyboard input."""

    continuous = True

    def __init__(self, microphone, stt, phrases, window_seconds: float = 2.0):
        self.microphone = microphone
        self.stt = stt
        self.detector = WakeWordDetector(phrases)
        self.window_seconds = window_seconds
        self._command = None
        self._closed = False

    def wait_for_wake(self, timeout: float) -> bool:
        if self._closed:
            return False
        audio = self.microphone.capture_push_to_talk(duration=min(self.window_seconds, max(timeout, 0.1)))
        if audio is None or self._closed:
            return False
        command = self.detector.extract_command(self.stt.transcribe(audio).text)
        if command is None:
            return False
        self._command = command
        return True

    def take_command(self):
        command, self._command = self._command, None
        return command

    def shutdown(self) -> None:
        self._closed = True


class DisabledWakeWordProvider(WakeWordProvider):
    def __init__(self) -> None:
        self._stop = Event()

    def wait_for_wake(self, timeout: float) -> bool:
        self._stop.wait(timeout)
        return False

    def shutdown(self) -> None:
        self._stop.set()


class MockWakeWordProvider(WakeWordProvider):
    """Deterministic wake provider for tests and future local adapters."""

    def __init__(self) -> None:
        self._events: Deque[bool] = deque()
        self._signal = Event()
        self.closed = False

    def trigger(self) -> None:
        if not self.closed:
            self._events.append(True)
            self._signal.set()

    def wait_for_wake(self, timeout: float) -> bool:
        self._signal.wait(timeout)
        if self._events:
            self._events.popleft()
            if not self._events:
                self._signal.clear()
            return True
        return False

    def shutdown(self) -> None:
        self.closed = True
        self._signal.set()


class VoiceActivityDetector(ABC):
    """Optional VAD seam; capture remains push-to-talk until a local provider is added."""

    @abstractmethod
    def should_stop(self, speech_detected: bool, silence_seconds: float) -> bool:
        pass


class SilenceThresholdVAD(VoiceActivityDetector):
    def __init__(self, silence_threshold_seconds: float = 1.2) -> None:
        self.silence_threshold_seconds = silence_threshold_seconds

    def should_stop(self, speech_detected: bool, silence_seconds: float) -> bool:
        return speech_detected and silence_seconds >= self.silence_threshold_seconds
