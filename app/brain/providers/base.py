from abc import ABC, abstractmethod
from threading import Event
from typing import Iterator, List, Dict, Optional, Any


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class BaseLLMProvider(ABC):
    """Abstract base class for all JARVIS LLM providers."""

    @abstractmethod
    def ask(self, message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        """Send a message to the provider with optional conversation history."""
        pass

    def generate(self, prompt: str) -> str:
        """Generate text from a single prompt."""
        return self.ask(prompt)

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Chat with a list of message objects."""
        if not messages:
            return ""
        last_msg = messages[-1].get("content", "")
        history = messages[:-1]
        return self.ask(last_msg, history=history)

    def stream(self, message: str, history: Optional[List[Dict[str, str]]] = None,
               cancellation: Optional[CancellationToken] = None) -> Iterator[str]:
        """Optional UI streaming seam; voice continues to use complete responses."""
        if cancellation and cancellation.cancelled:
            return
        yield self.ask(message, history=history)

    def close(self) -> None:
        """Release provider resources when an implementation owns any."""
        return None

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Check provider connectivity and status."""
        pass
