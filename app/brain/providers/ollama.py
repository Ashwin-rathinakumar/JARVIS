import requests
from typing import List, Dict, Optional, Any

from app.brain.providers.base import BaseLLMProvider
from app.config.settings import (
    OLLAMA_MODEL,
    OLLAMA_URL,
    OLLAMA_TIMEOUT,
)
from app.brain.prompts import SYSTEM_PROMPT
from app.utils.logger import logger


class OllamaProvider(BaseLLMProvider):
    """Local Ollama LLM provider."""

    def __init__(self):
        self.model = OLLAMA_MODEL
        self.url = OLLAMA_URL.rstrip("/")
        self.timeout = OLLAMA_TIMEOUT

    def health_check(self) -> Dict[str, Any]:
        """Check if Ollama is running and whether the target model is available."""
        try:
            resp = requests.get(f"{self.url}/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", [])]
                has_model = any(self.model in m for m in models)
                return {
                    "connected": True,
                    "model": self.model,
                    "model_available": has_model,
                    "url": self.url,
                    "available_models": models,
                }
            return {
                "connected": False,
                "error": f"HTTP {resp.status_code}",
                "model": self.model,
            }
        except Exception as e:
            return {
                "connected": False,
                "error": str(e),
                "model": self.model,
            }

    def ask(self, message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        """Query Ollama with chat messages."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        if history:
            for turn in history[-6:]:  # Bounded history
                messages.append({
                    "role": turn.get("role", "user"),
                    "content": turn.get("content", "")
                })

        messages.append({"role": "user", "content": message})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        try:
            response = requests.post(
                f"{self.url}/api/chat",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            return data["message"]["content"].strip()

        except requests.exceptions.Timeout:
            logger.error(f"Ollama timed out after {self.timeout}s")
            raise RuntimeError(f"Ollama timed out after {self.timeout} seconds.")

        except requests.exceptions.ConnectionError:
            logger.error("Ollama connection failed: server not running")
            raise RuntimeError("Ollama is not running. Start Ollama and try again.")

        except Exception as error:
            logger.error(f"Ollama error: {error}")
            raise RuntimeError(f"Ollama error: {error}")