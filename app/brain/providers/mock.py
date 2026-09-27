from typing import Any, Dict, List, Optional

from app.brain.providers.base import BaseLLMProvider


class MockProvider(BaseLLMProvider):
    def __init__(self, response: str = "Mock response") -> None:
        self.response = response
        self.requests: List[Dict[str, Any]] = []
        self.model = "mock"

    def ask(self, message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        self.requests.append({"message": message, "history": list(history or [])})
        return self.response

    def health_check(self) -> Dict[str, Any]:
        return {"connected": True, "model": self.model}
