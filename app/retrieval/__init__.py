"""Local Document Retrieval and RAG module for JARVIS."""
from app.retrieval.rag import index_all_documents, ask_documents, get_document_status
from app.retrieval.indexer import (
    index_chunks,
    search_chunks,
    semantic_search,
    cosine_similarity,
    get_index_stats,
)
from app.retrieval.hybrid import hybrid_search
from app.retrieval.embeddings import (
    OllamaEmbeddingEngine,
    OllamaEmbeddingError,
    embed_text,
    embed_texts,
)
from app.retrieval.loader import load_documents_from_directory
from app.retrieval.chunker import chunk_text

__all__ = [
    "index_all_documents",
    "ask_documents",
    "get_document_status",
    "index_chunks",
    "search_chunks",
    "semantic_search",
    "hybrid_search",
    "cosine_similarity",
    "get_index_stats",
    "OllamaEmbeddingEngine",
    "OllamaEmbeddingError",
    "embed_text",
    "embed_texts",
    "load_documents_from_directory",
    "chunk_text",
]
