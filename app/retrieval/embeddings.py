import requests
from typing import List, Optional, Any, Union

from app.config.settings import (
    OLLAMA_URL,
    OLLAMA_EMBED_MODEL,
    OLLAMA_TIMEOUT,
)
from app.utils.logger import logger


class OllamaEmbeddingError(Exception):
    """Controlled application-level exception for embedding failures."""
    pass


class OllamaEmbeddingEngine:
    """Local embedding engine leveraging Ollama's HTTP API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self.base_url = (base_url or OLLAMA_URL).rstrip("/")
        self.model = model or OLLAMA_EMBED_MODEL
        self.timeout = timeout if timeout is not None else OLLAMA_TIMEOUT

    def embed_text(self, text: str, model: Optional[str] = None) -> List[float]:
        """
        Generate embedding vector for a single string.
        Returns an empty list if text is empty or whitespace only.
        """
        if not text or not text.strip():
            return []

        results = self.embed_texts([text], model=model)
        if results and len(results) > 0:
            return results[0]
        return []

    def embed_texts(self, texts: List[str], model: Optional[str] = None) -> List[List[float]]:
        """
        Generate embedding vectors for a batch of strings.
        Prefers Ollama's /api/embed endpoint with fallback to legacy /api/embeddings.
        """
        if not texts:
            return []

        active_model = model or self.model
        non_empty_indices = [i for i, t in enumerate(texts) if t and t.strip()]

        if not non_empty_indices:
            return [[] for _ in texts]

        inputs_to_send = [texts[i] for i in non_empty_indices]

        # 1. Try modern /api/embed endpoint (supports batch inputs)
        try:
            embed_url = f"{self.base_url}/api/embed"
            payload = {
                "model": active_model,
                "input": inputs_to_send if len(inputs_to_send) > 1 else inputs_to_send[0],
            }

            resp = requests.post(embed_url, json=payload, timeout=self.timeout)

            # If endpoint is supported and successful
            if resp.status_code == 200:
                data = resp.json()
                if "embeddings" in data and isinstance(data["embeddings"], list):
                    raw_embeddings = data["embeddings"]
                    # Ensure dimensions match requested count
                    if len(raw_embeddings) == len(inputs_to_send):
                        result_list: List[List[float]] = [[] for _ in texts]
                        for orig_idx, emb in zip(non_empty_indices, raw_embeddings):
                            result_list[orig_idx] = emb
                        return result_list
                elif "embedding" in data and isinstance(data["embedding"], list):
                    # Single result format
                    result_list = [[] for _ in texts]
                    result_list[non_empty_indices[0]] = data["embedding"]
                    return result_list

            elif resp.status_code in (404, 501):
                # /api/embed not supported on older Ollama versions, fall through to /api/embeddings
                logger.debug(f"/api/embed returned {resp.status_code}, falling back to legacy /api/embeddings")
            else:
                resp.raise_for_status()

        except requests.exceptions.Timeout as e:
            logger.error(f"Embedding request to Ollama timed out after {self.timeout}s: {e}")
            raise OllamaEmbeddingError(f"Ollama embedding timed out after {self.timeout} seconds.") from e

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to Ollama at {self.base_url}: {e}")
            raise OllamaEmbeddingError("Ollama is not running or unreachable at configured URL.") from e

        except requests.exceptions.HTTPError as e:
            logger.error(f"Ollama embedding HTTP error for model '{active_model}': {e}")
            raise OllamaEmbeddingError(f"Ollama embedding failed with HTTP error: {e}") from e

        except OllamaEmbeddingError:
            raise

        except Exception as e:
            logger.debug(f"Modern /api/embed failed ({e}), attempting legacy /api/embeddings fallback")

        # 2. Fallback to legacy /api/embeddings endpoint (one item per request)
        try:
            embeddings_url = f"{self.base_url}/api/embeddings"
            result_list = [[] for _ in texts]

            for orig_idx in non_empty_indices:
                payload = {
                    "model": active_model,
                    "prompt": texts[orig_idx],
                }
                resp = requests.post(embeddings_url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()

                if "embedding" not in data or not isinstance(data["embedding"], list):
                    raise OllamaEmbeddingError(f"Malformed embedding response from Ollama: {data}")

                result_list[orig_idx] = data["embedding"]

            return result_list

        except requests.exceptions.Timeout as e:
            logger.error(f"Legacy embedding request timed out: {e}")
            raise OllamaEmbeddingError(f"Ollama embedding timed out after {self.timeout} seconds.") from e

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Legacy embedding connection error: {e}")
            raise OllamaEmbeddingError("Ollama is not running or unreachable.") from e

        except Exception as e:
            logger.error(f"Ollama embedding failure for model '{active_model}': {e}")
            raise OllamaEmbeddingError(f"Failed to generate embeddings: {e}") from e


# Module-level default instance and convenience helpers
default_engine = OllamaEmbeddingEngine()


def embed_text(
    text: str,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None
) -> List[float]:
    """Generate embedding vector for a single text using Ollama."""
    if base_url or timeout:
        engine = OllamaEmbeddingEngine(base_url=base_url, model=model, timeout=timeout)
        return engine.embed_text(text, model=model)
    return default_engine.embed_text(text, model=model)


def embed_texts(
    texts: List[str],
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: Optional[int] = None
) -> List[List[float]]:
    """Generate embedding vectors for multiple texts using Ollama."""
    if base_url or timeout:
        engine = OllamaEmbeddingEngine(base_url=base_url, model=model, timeout=timeout)
        return engine.embed_texts(texts, model=model)
    return default_engine.embed_texts(texts, model=model)
