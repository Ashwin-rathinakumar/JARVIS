import unittest
from unittest.mock import patch, MagicMock

from app.retrieval.hybrid import hybrid_search
from app.retrieval.rag import ask_documents
from app.retrieval.indexer import search_chunks, semantic_search


class TestHybridRetrieval(unittest.TestCase):

    @patch("app.retrieval.hybrid.search_chunks")
    @patch("app.retrieval.hybrid.semantic_search")
    def test_rrf_combination_and_deduplication(self, mock_semantic, mock_bm25):
        # BM25 returns chunk A (rank 1), chunk B (rank 2)
        mock_bm25.return_value = [
            {"source": "doc1.txt", "chunk_index": 0, "rel_path": "doc1.txt", "content": "Chunk A text", "score": -0.5},
            {"source": "doc1.txt", "chunk_index": 1, "rel_path": "doc1.txt", "content": "Chunk B text", "score": -1.2},
        ]
        # Semantic returns chunk B (rank 1), chunk C (rank 2)
        mock_semantic.return_value = [
            {"chunk_id": 2, "source": "doc1.txt", "chunk_index": 1, "rel_path": "doc1.txt", "content": "Chunk B text", "score": 0.95},
            {"chunk_id": 3, "source": "doc2.txt", "chunk_index": 0, "rel_path": "doc2.txt", "content": "Chunk C text", "score": 0.80},
        ]

        # rrf_k = 60
        # Chunk A (BM25 rank 1): 1 / (60 + 1) = 1/61 ~ 0.016393
        # Chunk B (BM25 rank 2 + Semantic rank 1): 1/62 + 1/61 = 0.016129 + 0.016393 ~ 0.032522 (Highest!)
        # Chunk C (Semantic rank 2): 1 / (60 + 2) = 1/62 ~ 0.016129

        results = hybrid_search("test query", limit=5, candidate_limit=10, rrf_k=60)

        # Total 3 deduplicated chunks
        self.assertEqual(len(results), 3)

        # Top ranked should be Chunk B due to fusion boost
        self.assertEqual(results[0]["chunk_index"], 1)
        self.assertEqual(results[0]["source"], "doc1.txt")
        self.assertEqual(results[0]["lexical_rank"], 2)
        self.assertEqual(results[0]["semantic_rank"], 1)
        self.assertAlmostEqual(results[0]["score"], (1/62 + 1/61), places=4)

        # Chunk A and C rankings
        self.assertEqual(results[1]["content"], "Chunk A text")
        self.assertEqual(results[1]["lexical_rank"], 1)
        self.assertIsNone(results[1]["semantic_rank"])

        self.assertEqual(results[2]["content"], "Chunk C text")
        self.assertIsNone(results[2]["lexical_rank"])
        self.assertEqual(results[2]["semantic_rank"], 2)

    @patch("app.retrieval.hybrid.search_chunks")
    @patch("app.retrieval.hybrid.semantic_search")
    def test_bm25_only_when_semantic_empty(self, mock_semantic, mock_bm25):
        mock_bm25.return_value = [
            {"source": "doc1.txt", "chunk_index": 0, "rel_path": "doc1.txt", "content": "BM25 only text", "score": -0.1}
        ]
        mock_semantic.return_value = []

        results = hybrid_search("test query", limit=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "BM25 only text")
        self.assertEqual(results[0]["lexical_rank"], 1)
        self.assertIsNone(results[0]["semantic_rank"])

    @patch("app.retrieval.hybrid.search_chunks")
    @patch("app.retrieval.hybrid.semantic_search")
    def test_semantic_only_when_bm25_empty(self, mock_semantic, mock_bm25):
        mock_bm25.return_value = []
        mock_semantic.return_value = [
            {"chunk_id": 1, "source": "doc2.txt", "chunk_index": 0, "rel_path": "doc2.txt", "content": "Semantic only text", "score": 0.88}
        ]

        results = hybrid_search("test query", limit=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "Semantic only text")
        self.assertIsNone(results[0]["lexical_rank"])
        self.assertEqual(results[0]["semantic_rank"], 1)

    @patch("app.retrieval.hybrid.search_chunks")
    @patch("app.retrieval.hybrid.semantic_search")
    def test_graceful_degradation_on_semantic_exception(self, mock_semantic, mock_bm25):
        mock_bm25.return_value = [
            {"source": "doc1.txt", "chunk_index": 0, "rel_path": "doc1.txt", "content": "Fallback text", "score": -0.2}
        ]
        mock_semantic.side_effect = RuntimeError("Ollama connection error")

        results = hybrid_search("test query")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "Fallback text")

    @patch("app.retrieval.hybrid.search_chunks")
    @patch("app.retrieval.hybrid.semantic_search")
    def test_both_empty_returns_empty_list(self, mock_semantic, mock_bm25):
        mock_bm25.return_value = []
        mock_semantic.return_value = []

        results = hybrid_search("test query")
        self.assertEqual(results, [])

    def test_empty_query_returns_empty_list(self):
        self.assertEqual(hybrid_search(""), [])
        self.assertEqual(hybrid_search("   "), [])

    @patch("app.retrieval.rag.hybrid_search")
    def test_ask_documents_uses_hybrid_search(self, mock_hybrid):
        mock_hybrid.return_value = [
            {"source": "guide.txt", "chunk_index": 0, "content": "Grounding fact: JARVIS is local.", "score": 0.032}
        ]
        mock_brain = MagicMock()
        mock_brain.ask.return_value = "JARVIS is a local assistant."

        answer = ask_documents("What is JARVIS?", brain=mock_brain)
        mock_hybrid.assert_called_once_with("What is JARVIS?", limit=3)
        mock_brain.ask.assert_called_once()
        self.assertIn("JARVIS is local", mock_brain.ask.call_args[0][0])
        self.assertEqual(answer, "JARVIS is a local assistant.")

    @patch("app.retrieval.rag.hybrid_search")
    def test_ask_documents_without_brain_returns_formatted_excerpts(self, mock_hybrid):
        mock_hybrid.return_value = [
            {"source": "guide.txt", "chunk_index": 0, "content": "Excerpt content", "score": 0.032}
        ]
        answer = ask_documents("What is JARVIS?", brain=None)
        self.assertIn("guide.txt", answer)
        self.assertIn("Excerpt content", answer)


if __name__ == "__main__":
    unittest.main()
