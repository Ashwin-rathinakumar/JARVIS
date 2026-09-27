import unittest
import tempfile
import sqlite3
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.retrieval.loader import load_documents_from_directory
from app.retrieval.chunker import chunk_text
from app.retrieval.indexer import (
    index_chunks,
    search_chunks,
    semantic_search,
    cosine_similarity,
    get_index_stats,
    initialize_fts,
)
from app.retrieval.rag import ask_documents, index_all_documents, get_document_status
from app.retrieval.embeddings import OllamaEmbeddingError


class TestDocumentRAG(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.temp_path = Path(self.temp_dir.name)
        self.test_db = self.temp_path / "test_docs.db"
        self.patcher = patch("app.retrieval.indexer.DOCUMENTS_DB_PATH", self.test_db)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_chunker(self):
        text = "Alpha paragraph.\n\nBeta paragraph with more text.\n\nGamma concluding paragraph."
        chunks = chunk_text(text, source="doc.txt", chunk_size=30, chunk_overlap=10)
        self.assertTrue(len(chunks) >= 2)
        self.assertEqual(chunks[0]["source"], "doc.txt")

    @patch("app.retrieval.indexer.embed_texts")
    def test_indexing_and_lexical_search(self, mock_embed_texts):
        mock_embed_texts.return_value = [[0.1, 0.2, 0.3]]
        doc_file = self.temp_path / "notes.txt"
        doc_file.write_text("JARVIS assistant runs locally on Windows 11 with SQLite.", encoding="utf-8")

        docs = load_documents_from_directory(self.temp_path)
        self.assertEqual(len(docs), 1)

        chunks = chunk_text(docs[0]["text"], source=docs[0]["source"])
        index_chunks(chunks, source=docs[0]["source"], rel_path="notes.txt")

        stats = get_index_stats()
        self.assertEqual(stats["file_count"], 1)

        # Lexical BM25 search
        results = search_chunks("Windows")
        self.assertEqual(len(results), 1)
        self.assertIn("Windows", results[0]["content"])

        # Empty match
        no_res = search_chunks("quantum_computing_xyz")
        self.assertEqual(len(no_res), 0)

    def test_ask_documents_no_match(self):
        res = ask_documents("quantum_computing_xyz")
        self.assertIn("No relevant information found", res)

    def test_cosine_similarity(self):
        # Identical vectors
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        # Orthogonal vectors
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)
        # Opposite vectors
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0)
        # Collinear vectors
        self.assertAlmostEqual(cosine_similarity([1.0, 2.0], [2.0, 4.0]), 1.0)
        # Empty or dimension mismatch
        self.assertEqual(cosine_similarity([], [1.0]), 0.0)
        self.assertEqual(cosine_similarity([1.0], [1.0, 2.0]), 0.0)
        self.assertEqual(cosine_similarity([0.0, 0.0], [0.0, 0.0]), 0.0)

    @patch("app.retrieval.indexer.embed_texts")
    @patch("app.retrieval.indexer.embed_text")
    def test_semantic_search_ranking(self, mock_embed_text, mock_embed_texts):
        # Setup 2 chunks with mock embeddings
        # Chunk 1 is aligned with query, Chunk 2 is orthogonal
        mock_embed_texts.return_value = [
            [1.0, 0.0, 0.0],  # Chunk 0
            [0.0, 1.0, 0.0],  # Chunk 1
        ]
        mock_embed_text.return_value = [1.0, 0.0, 0.0]  # Query

        chunks = [
            {"source": "test.txt", "chunk_index": 0, "content": "Chunk about Artificial Intelligence"},
            {"source": "test.txt", "chunk_index": 1, "content": "Chunk about Gardening and Plants"},
        ]

        index_chunks(chunks, source="test.txt", rel_path="test.txt", model="nomic-embed-text")

        results = semantic_search("Artificial Intelligence", limit=2, model="nomic-embed-text")
        self.assertEqual(len(results), 2)
        # Chunk 0 should have similarity ~1.0
        self.assertEqual(results[0]["chunk_index"], 0)
        self.assertAlmostEqual(results[0]["score"], 1.0, places=2)
        self.assertIn("Artificial Intelligence", results[0]["content"])

        # Chunk 1 should have similarity ~0.0
        self.assertEqual(results[1]["chunk_index"], 1)
        self.assertAlmostEqual(results[1]["score"], 0.0, places=2)

    @patch("app.retrieval.indexer.embed_texts")
    @patch("app.retrieval.indexer.embed_text")
    def test_model_isolation(self, mock_embed_text, mock_embed_texts):
        # Index with model A
        mock_embed_texts.return_value = [[1.0, 0.0]]
        chunks = [{"source": "test.txt", "chunk_index": 0, "content": "Model A content"}]
        index_chunks(chunks, source="test.txt", rel_path="test.txt", model="model-a")

        # Search with model B
        mock_embed_text.return_value = [1.0, 0.0]
        results_b = semantic_search("query", model="model-b")
        self.assertEqual(len(results_b), 0)

        # Search with model A
        results_a = semantic_search("query", model="model-a")
        self.assertEqual(len(results_a), 1)
        self.assertEqual(results_a[0]["model"], "model-a")

    @patch("app.retrieval.indexer.embed_texts")
    def test_deduplication_on_reindexing(self, mock_embed_texts):
        mock_embed_texts.return_value = [[0.5, 0.5]]
        chunks = [{"source": "test.txt", "chunk_index": 0, "content": "Same content"}]

        # First indexing
        index_chunks(chunks, source="test.txt", rel_path="test.txt", model="nomic-embed-text")
        self.assertEqual(mock_embed_texts.call_count, 1)

        # Second indexing with identical content - should reuse existing embedding without calling embed_texts again
        index_chunks(chunks, source="test.txt", rel_path="test.txt", model="nomic-embed-text")
        self.assertEqual(mock_embed_texts.call_count, 1)

        # Check only 1 row in document_embeddings
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM document_embeddings")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    @patch("app.retrieval.indexer.embed_texts")
    def test_graceful_degradation_on_embedding_failure(self, mock_embed_texts):
        # Simulate Ollama connection failure
        mock_embed_texts.side_effect = OllamaEmbeddingError("Ollama offline")

        chunks = [{"source": "test.txt", "chunk_index": 0, "content": "Important lexical text"}]
        # Should NOT raise exception, and lexical indexing should still succeed
        index_chunks(chunks, source="test.txt", rel_path="test.txt")

        # Lexical search must work
        lex_results = search_chunks("Important")
        self.assertEqual(len(lex_results), 1)
        self.assertEqual(lex_results[0]["content"], "Important lexical text")

        # Semantic search returns empty list gracefully
        sem_results = semantic_search("Important")
        self.assertEqual(len(sem_results), 0)

    def test_database_migration_from_legacy_schema(self):
        # Create legacy DB with only indexed_files and document_chunks
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE indexed_files (source TEXT PRIMARY KEY, rel_path TEXT, chunk_count INTEGER, indexed_at TIMESTAMP)")
        cursor.execute("CREATE VIRTUAL TABLE document_chunks USING fts5(source, rel_path, chunk_index UNINDEXED, content)")
        cursor.execute("INSERT INTO indexed_files VALUES ('legacy.txt', 'legacy.txt', 1, CURRENT_TIMESTAMP)")
        cursor.execute("INSERT INTO document_chunks VALUES ('legacy.txt', 'legacy.txt', 0, 'Legacy content preserved')")
        conn.commit()
        conn.close()

        # Run initialize_fts()
        initialize_fts()

        # Check document_embeddings table exists and legacy rows are intact
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='document_embeddings'")
        self.assertIsNotNone(cursor.fetchone())

        cursor.execute("SELECT content FROM document_chunks WHERE source='legacy.txt'")
        row = cursor.fetchone()
        conn.close()
        self.assertEqual(row[0], "Legacy content preserved")


if __name__ == "__main__":
    unittest.main()
