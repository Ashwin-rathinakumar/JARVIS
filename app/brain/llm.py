from typing import Optional, Dict, Any, List

from app.config.settings import LLM_PROVIDER, JARVIS_LLM_FALLBACK, JARVIS_LLM_FALLBACK_ENABLED
from app.brain.providers.base import BaseLLMProvider
from app.brain.providers.gemini import GeminiProvider
from app.brain.providers.ollama import OllamaProvider
from app.brain.providers.nemotron import NemotronProvider
from app.brain.providers.mock import MockProvider
from app.state.session import session as default_session, SessionState
from app.utils.logger import logger
from app.brain.context import build_context


class JarvisBrain:
    """Core LLM reasoning brain for JARVIS."""

    def __init__(self, provider_name: Optional[str] = None):
        self.provider_name = (provider_name or LLM_PROVIDER).lower()
        self.provider: BaseLLMProvider = self._init_provider(self.provider_name)
        self.fallback_provider_name: Optional[str] = None
        self.fallback_provider: Optional[BaseLLMProvider] = None
        if JARVIS_LLM_FALLBACK_ENABLED and JARVIS_LLM_FALLBACK and JARVIS_LLM_FALLBACK != self.provider_name:
            self.fallback_provider_name = JARVIS_LLM_FALLBACK
            self.fallback_provider = self._init_provider(JARVIS_LLM_FALLBACK)

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

        if name == "nemotron":
            return NemotronProvider()

        if name == "mock":
            return MockProvider()

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

    def ask(self, message: str, session_target: Optional[SessionState] = None) -> str:
        """
        Send natural language to the active LLM provider.

        Before sending the request, JARVIS builds contextual information
        from persistent memory and current session/project state.
        """
        active_session = session_target or default_session

        try:
            history = active_session.get_recent_messages()

            contextual_message = build_context(message)

            try:
                response = self.provider.ask(contextual_message, history=history)
            except Exception as primary_error:
                if not self.fallback_provider:
                    raise
                logger.warning("LLM fallback primary=%s fallback=%s reason=%s", self.provider_name,
                               self.fallback_provider_name, primary_error)
                response = self.fallback_provider.ask(contextual_message, history=history)

            # Store the original human message, not the internally
            # augmented context prompt.
            active_session.add_turn("user", message)
            active_session.add_turn("assistant", response)

            return response

        except Exception as error:
            logger.error(
                f"Brain reasoning error ({self.provider_name}): {error}"
            )
            return f"{self.provider_name.capitalize()} error: {error}"

    def status(self) -> Dict[str, Any]:
        health = self.health_check()
        return {
            "provider": self.provider_name,
            "model": health.get("model", getattr(self.provider, "model", "unknown")),
            "available": bool(health.get("connected", False) and health.get("model_available", True)),
            "endpoint_category": health.get("endpoint_category", "local" if self.provider_name == "ollama" else "configured"),
            "fallback": self.fallback_provider_name,
        }

    def close(self) -> None:
        self.provider.close()
        if self.fallback_provider:
            self.fallback_provider.close()

    def generate(self, prompt: str) -> str:
        """Direct text generation without session context."""
        return self.provider.generate(prompt)

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Direct chat with raw messages."""
        return self.provider.chat(messages)
