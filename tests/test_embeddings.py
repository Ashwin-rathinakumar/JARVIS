import unittest
from unittest.mock import patch, MagicMock
import requests

from app.retrieval.embeddings import (
    OllamaEmbeddingEngine,
    OllamaEmbeddingError,
    embed_text,
    embed_texts,
)


class TestOllamaEmbeddings(unittest.TestCase):

    def test_empty_input(self):
        self.assertEqual(embed_text(""), [])
        self.assertEqual(embed_text("   "), [])
        self.assertEqual(embed_texts([]), [])
        self.assertEqual(embed_texts(["", "  "]), [[], []])

    @patch("requests.post")
    def test_successful_single_embed_modern(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "embeddings": [[0.1, 0.2, 0.3, 0.4]]
        }
        mock_post.return_value = mock_resp

        vec = embed_text("Hello JARVIS", model="nomic-embed-text")
        self.assertEqual(vec, [0.1, 0.2, 0.3, 0.4])
        mock_post.assert_called_once()
        self.assertIn("/api/embed", mock_post.call_args[0][0])

    @patch("requests.post")
    def test_successful_batch_embed_modern(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "embeddings": [
                [0.1, 0.2],
                [0.3, 0.4],
            ]
        }
        mock_post.return_value = mock_resp

        vecs = embed_texts(["doc1", "doc2"], model="nomic-embed-text")
        self.assertEqual(len(vecs), 2)
        self.assertEqual(vecs[0], [0.1, 0.2])
        self.assertEqual(vecs[1], [0.3, 0.4])

    @patch("requests.post")
    def test_fallback_to_legacy_embeddings_endpoint(self, mock_post):
        # 1st call to /api/embed returns 404 (not supported)
        resp_404 = MagicMock()
        resp_404.status_code = 404

        # Subsequent call to /api/embeddings returns legacy format
        resp_legacy = MagicMock()
        resp_legacy.status_code = 200
        resp_legacy.json.return_value = {
            "embedding": [0.5, 0.6, 0.7]
        }

        mock_post.side_effect = [resp_404, resp_legacy]

        vec = embed_text("Legacy test text")
        self.assertEqual(vec, [0.5, 0.6, 0.7])
        self.assertEqual(mock_post.call_count, 2)
        self.assertIn("/api/embed", mock_post.call_args_list[0][0][0])
        self.assertIn("/api/embeddings", mock_post.call_args_list[1][0][0])

    @patch("requests.post")
    def test_connection_failure(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("Failed to connect")

        with self.assertRaises(OllamaEmbeddingError) as ctx:
            embed_text("Test connection error")
        self.assertIn("not running or unreachable", str(ctx.exception))

    @patch("requests.post")
    def test_timeout_failure(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("Read timeout")

        with self.assertRaises(OllamaEmbeddingError) as ctx:
            embed_text("Test timeout")
        self.assertIn("timed out", str(ctx.exception))

    @patch("requests.post")
    def test_http_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_post.return_value = mock_resp

        with self.assertRaises(OllamaEmbeddingError):
            embed_text("Test HTTP 500 error")

    @patch("requests.post")
    def test_malformed_response(self, mock_post):
        # First /api/embed returns 404 to trigger fallback
        resp_404 = MagicMock()
        resp_404.status_code = 404

        # Legacy endpoint returns malformed data without 'embedding' key
        resp_bad = MagicMock()
        resp_bad.status_code = 200
        resp_bad.json.return_value = {"something_else": 123}

        mock_post.side_effect = [resp_404, resp_bad]

        with self.assertRaises(OllamaEmbeddingError) as ctx:
            embed_text("Test malformed response")
        self.assertIn("Malformed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
