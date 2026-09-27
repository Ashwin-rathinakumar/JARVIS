from typing import Optional, Dict, Any

from app.config.settings import LLM_PROVIDER
from app.brain.providers.base import BaseLLMProvider
from app.brain.providers.gemini import GeminiProvider
from app.brain.providers.ollama import OllamaProvider
from app.state.session import session
from app.brain.context import build_conversation_prompt
from app.utils.logger import logger


class JarvisBrain:
    """Core LLM reasoning brain for JARVIS."""

    def __init__(self, provider_name: Optional[str] = None):
        self.provider_name = (provider_name or LLM_PROVIDER).lower()
        self.provider: BaseLLMProvider = self._init_provider(self.provider_name)

    def _init_provider(self, name: str) -> BaseLLMProvider:
        if name == "gemini":
            try:
                return GeminiProvider()
            except Exception as e:
                logger.warning(f"Gemini init failed ({e}), falling back to Ollama.")
                self.provider_name = "ollama"
                return OllamaProvider()

        if name == "ollama":
            return OllamaProvider()

        logger.warning(f"Unknown provider '{name}', defaulting to Ollama.")
        self.provider_name = "ollama"
        return OllamaProvider()

    def health_check(self) -> Dict[str, Any]:
        """Perform health check on the configured LLM provider."""
        try:
            status = self.provider.health_check()
            status["provider"] = self.provider_name
            return status
        except Exception as e:
            return {
                "provider": self.provider_name,
                "connected": False,
                "error": str(e),
            }

    def ask(self, message: str) -> str:
        """Send a natural language prompt to the active LLM provider."""
        try:
            history = session.get_recent_history(limit=6)
            prompt = build_conversation_prompt(message)
            response = self.provider.ask(prompt, history=history)

            # Record turn in session history
            session.add_turn("user", message)
            session.add_turn("assistant", response)

            return response

        except Exception as error:
            logger.error(f"Brain reasoning error ({self.provider_name}): {error}")
            return f"{self.provider_name.capitalize()} error: {error}"