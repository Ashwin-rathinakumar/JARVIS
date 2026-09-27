import unittest
from unittest.mock import patch, MagicMock
import requests

from app.brain.providers.ollama import OllamaProvider
from app.brain.providers.gemini import GeminiProvider
from app.brain.llm import JarvisBrain


class TestProviderFallback(unittest.TestCase):

    @patch("requests.post")
    def test_ollama_connection_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")
        provider = OllamaProvider()
        with self.assertRaises(RuntimeError) as ctx:
            provider.ask("hello")
        self.assertIn("Ollama is not running", str(ctx.exception))

    @patch("requests.post")
    def test_ollama_timeout(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("Read timeout")
        provider = OllamaProvider()
        with self.assertRaises(RuntimeError) as ctx:
            provider.ask("hello")
        self.assertIn("timed out", str(ctx.exception))

    @patch("requests.post")
    def test_brain_graceful_error_handling(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")
        brain = JarvisBrain("ollama")
        response = brain.ask("hello")
        self.assertIn("Ollama error", response)

    def test_gemini_missing_api_key(self):
        with patch("app.brain.providers.gemini.GEMINI_API_KEY", None):
            with self.assertRaises(ValueError):
                GeminiProvider()

    @patch("app.brain.providers.gemini.GEMINI_API_KEY", None)
    def test_brain_fallback_from_unconfigured_gemini_to_ollama(self):
        brain = JarvisBrain("gemini")
        # Should fallback to Ollama provider
        self.assertEqual(brain.provider_name, "ollama")


if __name__ == "__main__":
    unittest.main()
