import sqlite3
import re
import json
import math
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config.settings import DOCUMENTS_DB_PATH, OLLAMA_EMBED_MODEL
from app.retrieval.embeddings import embed_text, embed_texts, OllamaEmbeddingError
from app.utils.logger import logger


def get_fts_connection() -> sqlite3.Connection:
    """Get connection to the documents database."""
    DOCUMENTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DOCUMENTS_DB_PATH)


def initialize_fts():
    """
    Initialize SQLite tables for both lexical FTS5 BM25 and semantic embeddings.
    Performs non-destructive schema creation/migrations.
    """
    conn = get_fts_connection()
    try:
        cursor = conn.cursor()
        # Lexical file metadata
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS indexed_files (
                source TEXT PRIMARY KEY,
                rel_path TEXT,
                chunk_count INTEGER,
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Lexical FTS5 virtual table
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks USING fts5(
                source,
                rel_path,
                chunk_index UNINDEXED,
                content,
                tokenize='porter unicode61'
            )
        """)
        # Semantic vector embeddings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_hash TEXT,
                model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                embedding TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, chunk_index, model)
            )
        """)
        conn.commit()
    finally:
        conn.close()


def clean_fts_query(query: str) -> str:
    """Sanitize query for FTS5 syntax, escaping special characters."""
    words = re.findall(r"\w+", query)
    if not words:
        return ""
    return " OR ".join(f'"{w}"*' for w in words)


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Compute cosine similarity between two float vectors in pure Python."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def index_chunks(
    chunks: List[Dict[str, Any]],
    source: str,
    rel_path: str,
    generate_embeddings: bool = True,
    model: Optional[str] = None,
):
    """
    Store chunks into the FTS5 table and generate/persist semantic embeddings.
    If embedding generation fails, lexical indexing still succeeds gracefully.
    """
    initialize_fts()
    active_model = model or OLLAMA_EMBED_MODEL
    conn = get_fts_connection()

    try:
        cursor = conn.cursor()

        # 1. Update Lexical Index (FTS5 + indexed_files)
        cursor.execute("DELETE FROM document_chunks WHERE source = ?", (source,))
        cursor.execute("DELETE FROM indexed_files WHERE source = ?", (source,))

        for c in chunks:
            cursor.execute(
                """
                INSERT INTO document_chunks (source, rel_path, chunk_index, content)
                VALUES (?, ?, ?, ?)
                """,
                (c["source"], rel_path, c["chunk_index"], c["content"])
            )

        cursor.execute(
            """
            INSERT INTO indexed_files (source, rel_path, chunk_count)
            VALUES (?, ?, ?)
            """,
            (source, rel_path, len(chunks))
        )
        conn.commit()
        logger.info(f"Indexed {len(chunks)} lexical chunks for {source}")

        # 2. Update Semantic Embeddings
        if generate_embeddings and chunks:
            # Check existing embeddings to avoid unnecessary re-embedding
            cursor.execute(
                """
                SELECT chunk_index, chunk_hash, dimensions, embedding
                FROM document_embeddings
                WHERE source = ? AND model = ?
                """,
                (source, active_model)
            )
            existing_rows = {row[0]: (row[1], row[2], row[3]) for row in cursor.fetchall()}

            chunks_to_embed = []
            chunk_hashes = []

            for c in chunks:
                c_hash = hashlib.sha256(c["content"].encode("utf-8")).hexdigest()
                chunk_hashes.append(c_hash)
                idx = c["chunk_index"]

                # If existing hash matches, reuse existing embedding
                if idx in existing_rows and existing_rows[idx][0] == c_hash:
                    continue
                chunks_to_embed.append((idx, c["content"], c_hash))

            if chunks_to_embed:
                try:
                    texts = [item[1] for item in chunks_to_embed]
                    embeddings = embed_texts(texts, model=active_model)

                    for (idx, _, c_hash), emb in zip(chunks_to_embed, embeddings):
                        if emb:
                            emb_json = json.dumps(emb)
                            cursor.execute(
                                """
                                INSERT INTO document_embeddings
                                    (source, rel_path, chunk_index, chunk_hash, model, dimensions, embedding)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(source, chunk_index, model) DO UPDATE SET
                                    rel_path = excluded.rel_path,
                                    chunk_hash = excluded.chunk_hash,
                                    dimensions = excluded.dimensions,
                                    embedding = excluded.embedding,
                                    created_at = CURRENT_TIMESTAMP
                                """,
                                (source, rel_path, idx, c_hash, active_model, len(emb), emb_json)
                            )
                    conn.commit()
                    logger.info(f"Persisted {len(embeddings)} embeddings for {source} (model: {active_model})")

                except Exception as e:
                    logger.warning(
                        f"Semantic embedding generation failed for '{source}' with model '{active_model}': {e}. "
                        f"Lexical index remains operational."
                    )

            # Clean up any stale chunk embeddings beyond current chunk count
            cursor.execute(
                "DELETE FROM document_embeddings WHERE source = ? AND model = ? AND chunk_index >= ?",
                (source, active_model, len(chunks))
            )
            conn.commit()

    finally:
        conn.close()


def search_chunks(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Search chunks using FTS5 BM25 ranking (lexical keyword search)."""
    initialize_fts()
    cleaned = clean_fts_query(query)
    if not cleaned:
        return []

    conn = get_fts_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT source, rel_path, chunk_index, content, rank
                FROM document_chunks
                WHERE document_chunks MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (cleaned, top_k)
            )
            rows = cursor.fetchall()
            return [
                {
                    "source": row[0],
                    "rel_path": row[1],
                    "chunk_index": row[2],
                    "content": row[3],
                    "score": round(row[4], 4),
                }
                for row in rows
            ]
        except sqlite3.OperationalError as error:
            logger.warning(f"FTS search query error for '{cleaned}': {error}")
            return []
    finally:
        conn.close()


def semantic_search(
    query: str,
    limit: int = 5,
    model: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search document chunks by semantic embedding cosine similarity.
    Compares query embedding only against stored chunks of the matching model.
    """
    if not query or not query.strip():
        return []

    initialize_fts()
    active_model = model or OLLAMA_EMBED_MODEL

    try:
        query_vec = embed_text(query, model=active_model)
    except Exception as e:
        logger.warning(f"Failed to generate query embedding for semantic search: {e}")
        return []

    if not query_vec:
        return []

    conn = get_fts_connection()
    try:
        cursor = conn.cursor()
        # Retrieve all stored embeddings for the active model alongside chunk text
        cursor.execute(
            """
            SELECT
                de.id,
                de.source,
                de.rel_path,
                de.chunk_index,
                de.dimensions,
                de.embedding,
                dc.content
            FROM document_embeddings de
            LEFT JOIN document_chunks dc
                ON de.source = dc.source AND de.chunk_index = dc.chunk_index
            WHERE de.model = ?
            """,
            (active_model,)
        )
        rows = cursor.fetchall()

        results = []
        for row in rows:
            chunk_id, source, rel_path, chunk_index, dimensions, emb_str, content = row
            try:
                emb_vec = json.loads(emb_str)
                # Verify dimension compatibility
                if len(emb_vec) != len(query_vec):
                    logger.debug(
                        f"Dimension mismatch for chunk {chunk_id} ({len(emb_vec)} != {len(query_vec)}). Skipping."
                    )
                    continue

                sim = cosine_similarity(query_vec, emb_vec)
                results.append({
                    "chunk_id": chunk_id,
                    "source": source,
                    "rel_path": rel_path,
                    "chunk_index": chunk_index,
                    "content": content or "",
                    "score": round(sim, 4),
                    "model": active_model,
                })
            except Exception as parse_err:
                logger.debug(f"Error parsing stored embedding {chunk_id}: {parse_err}")
                continue

        # Sort descending by cosine similarity score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    finally:
        conn.close()


def get_index_stats() -> Dict[str, Any]:
    """Retrieve statistics about the document index (both lexical and semantic)."""
    initialize_fts()
    conn = get_fts_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(chunk_count) FROM indexed_files")
        row = cursor.fetchone()
        file_count = row[0] or 0
        chunk_count = row[1] or 0

        cursor.execute("SELECT source, chunk_count, indexed_at FROM indexed_files")
        files = [{"source": r[0], "chunks": r[1], "indexed_at": r[2]} for r in cursor.fetchall()]

        # Embedding statistics
        cursor.execute("SELECT COUNT(*), COUNT(DISTINCT model) FROM document_embeddings")
        emb_row = cursor.fetchone()
        embedded_chunk_count = emb_row[0] or 0

        cursor.execute("SELECT DISTINCT model FROM document_embeddings")
        models = [m[0] for m in cursor.fetchall()]

    finally:
        conn.close()

    return {
        "file_count": file_count,
        "chunk_count": chunk_count,
        "embedded_chunk_count": embedded_chunk_count,
        "embedding_models": models,
        "active_embed_model": OLLAMA_EMBED_MODEL,
        "files": files,
        "db_path": str(DOCUMENTS_DB_PATH),
    }
