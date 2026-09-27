"""Vendor-neutral wake-word and voice-activity interfaces."""
from abc import ABC, abstractmethod
from collections import deque
from threading import Event
from typing import Deque


class WakeWordProvider(ABC):
    @abstractmethod
    def wait_for_wake(self, timeout: float) -> bool:
        """Wait up to timeout seconds and return whether a local wake event occurred."""

    def shutdown(self) -> None:
        pass


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
