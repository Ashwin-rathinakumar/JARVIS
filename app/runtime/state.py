"""Observable lifecycle state for the persistent JARVIS runtime."""
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from time import time
from typing import Callable, List, Optional


class RuntimeState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class RuntimeTransition:
    previous: RuntimeState
    current: RuntimeState
    timestamp: float = field(default_factory=time)
    reason: Optional[str] = None


class RuntimeStateMachine:
    """Thread-safe state machine exposed to voice and desktop adapters."""

    _LEGAL = {
        RuntimeState.IDLE: {RuntimeState.LISTENING, RuntimeState.THINKING, RuntimeState.STOPPING, RuntimeState.ERROR},
        RuntimeState.LISTENING: {RuntimeState.TRANSCRIBING, RuntimeState.IDLE, RuntimeState.ERROR, RuntimeState.STOPPING},
        RuntimeState.TRANSCRIBING: {RuntimeState.THINKING, RuntimeState.IDLE, RuntimeState.ERROR, RuntimeState.STOPPING},
        RuntimeState.THINKING: {RuntimeState.EXECUTING, RuntimeState.SPEAKING, RuntimeState.IDLE, RuntimeState.ERROR, RuntimeState.STOPPING},
        RuntimeState.EXECUTING: {RuntimeState.SPEAKING, RuntimeState.IDLE, RuntimeState.ERROR, RuntimeState.STOPPING},
        RuntimeState.SPEAKING: {RuntimeState.IDLE, RuntimeState.ERROR, RuntimeState.STOPPING},
        RuntimeState.ERROR: {RuntimeState.IDLE, RuntimeState.STOPPING},
        RuntimeState.STOPPING: {RuntimeState.STOPPED},
        RuntimeState.STOPPED: set(),
    }

    def __init__(self) -> None:
        self._state = RuntimeState.IDLE
        self._lock = RLock()
        self._observers: List[Callable[[RuntimeTransition], None]] = []
        self.transitions: List[RuntimeTransition] = []

    @property
    def state(self) -> RuntimeState:
        with self._lock:
            return self._state

    def subscribe(self, observer: Callable[[RuntimeTransition], None]) -> None:
        with self._lock:
            self._observers.append(observer)

    def transition(self, target: RuntimeState, reason: Optional[str] = None) -> RuntimeTransition:
        with self._lock:
            if target == self._state:
                return RuntimeTransition(self._state, target, reason=reason)
            if target not in self._LEGAL[self._state]:
                raise ValueError(f"Illegal runtime transition: {self._state.value} -> {target.value}")
            transition = RuntimeTransition(self._state, target, reason=reason)
            self._state = target
            self.transitions.append(transition)
            observers = list(self._observers)
        for observer in observers:
            try:
                observer(transition)
            except Exception:
                # UI observers must never destabilize the core runtime.
                pass
        return transition
