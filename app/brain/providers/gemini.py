from typing import List, Dict, Optional, Any

from app.brain.providers.base import BaseLLMProvider
from app.config.settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
)
from app.brain.prompts import SYSTEM_PROMPT
from app.utils.logger import logger


class GeminiProvider(BaseLLMProvider):
    """Cloud Google Gemini LLM provider (optional)."""

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not configured.")

        try:
            from google import genai
            self.client = genai.Client(api_key=GEMINI_API_KEY)
            self.model = GEMINI_MODEL
        except Exception as error:
            logger.error(f"Failed to initialize Gemini client: {error}")
            raise

    def health_check(self) -> Dict[str, Any]:
        """Check if Gemini API key is configured."""
        return {
            "connected": bool(GEMINI_API_KEY),
            "provider": "gemini",
            "model": self.model,
        }

    def ask(self, message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        """Send prompt to Gemini."""
        history_text = ""
        if history:
            history_lines = []
            for h in history[-4:]:
                history_lines.append(f"{h.get('role', 'user').capitalize()}: {h.get('content', '')}")
            history_text = "\n".join(history_lines) + "\n"

        prompt = f"{SYSTEM_PROMPT}\n\n{history_text}User: {message}\nAssistant:"

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            return response.text.strip()
        except Exception as error:
            logger.error(f"Gemini API error: {error}")
            raise RuntimeError(f"Gemini error: {error}")