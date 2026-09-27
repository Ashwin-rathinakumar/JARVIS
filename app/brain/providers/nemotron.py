"""Nemotron provider for configurable OpenAI-compatible HTTP endpoints."""
import json
import time
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlparse

import requests

from app.brain.prompts import NEMOTRON_SYSTEM_PROMPT
from app.brain.providers.base import BaseLLMProvider, CancellationToken
from app.config.settings import (
    JARVIS_LLM_API_KEY, JARVIS_LLM_BASE_URL, JARVIS_LLM_MAX_TOKENS,
    JARVIS_LLM_MODEL, JARVIS_LLM_TEMPERATURE, JARVIS_LLM_TIMEOUT,
    MAX_CONTEXT_CHARS, MAX_CONTEXT_MESSAGES,
)
from app.utils.logger import logger


class NemotronProvider(BaseLLMProvider):
    def __init__(self, base_url: str = JARVIS_LLM_BASE_URL, model: str = JARVIS_LLM_MODEL,
                 api_key: str = JARVIS_LLM_API_KEY, timeout: int = JARVIS_LLM_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    @property
    def endpoint_category(self) -> str:
        host = (urlparse(self.base_url).hostname or "").lower()
        if host in {"localhost", "127.0.0.1", "::1"}:
            return "local"
        if host.startswith("10.") or host.startswith("192.168.") or host.startswith("172."):
            return "LAN"
        return "remote"

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _messages(self, message: str, history: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": NEMOTRON_SYSTEM_PROMPT}]
        used = 0
        selected = []
        for turn in reversed((history or [])[-MAX_CONTEXT_MESSAGES:]):
            content = str(turn.get("content", ""))
            if used + len(content) > MAX_CONTEXT_CHARS:
                break
            selected.append({"role": turn.get("role", "user"), "content": content})
            used += len(content)
        messages.extend(reversed(selected))
        messages.append({"role": "user", "content": message})
        return messages

    def health_check(self) -> Dict[str, Any]:
        try:
            response = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=min(self.timeout, 5))
            response.raise_for_status()
            models = [item.get("id") for item in response.json().get("data", [])]
            return {"connected": True, "model": self.model, "model_available": self.model in models,
                    "endpoint_category": self.endpoint_category, "available_models": models}
        except requests.exceptions.Timeout:
            return {"connected": False, "model": self.model, "error": "timeout", "endpoint_category": self.endpoint_category}
        except Exception as error:
            return {"connected": False, "model": self.model, "error": str(error), "endpoint_category": self.endpoint_category}

    def ask(self, message: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        started = time.monotonic()
        logger.info("LLM request start provider=nemotron model=%s endpoint=%s", self.model, self.endpoint_category)
        payload = {"model": self.model, "messages": self._messages(message, history), "stream": False,
                   "temperature": JARVIS_LLM_TEMPERATURE, "max_tokens": JARVIS_LLM_MAX_TOKENS}
        try:
            response = requests.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=payload,
                                     timeout=self.timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("Nemotron returned an empty or malformed response.")
            logger.info("LLM request complete provider=nemotron model=%s latency_ms=%d", self.model,
                        int((time.monotonic() - started) * 1000))
            return content.strip()
        except requests.exceptions.Timeout as error:
            logger.warning("LLM timeout provider=nemotron model=%s timeout=%s", self.model, self.timeout)
            raise RuntimeError("Nemotron request timed out.") from error
        except requests.exceptions.ConnectionError as error:
            raise RuntimeError("Nemotron endpoint is unavailable.") from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise RuntimeError("Nemotron returned a malformed response.") from error

    def stream(self, message: str, history: Optional[List[Dict[str, str]]] = None,
               cancellation: Optional[CancellationToken] = None) -> Iterator[str]:
        payload = {"model": self.model, "messages": self._messages(message, history), "stream": True,
                   "temperature": JARVIS_LLM_TEMPERATURE, "max_tokens": JARVIS_LLM_MAX_TOKENS}
        with requests.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=payload,
                           timeout=self.timeout, stream=True) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if cancellation and cancellation.cancelled:
                    break
                if not line or not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                data = json.loads(line[6:])
                chunk = data["choices"][0]["delta"].get("content", "")
                if chunk:
                    yield chunk
