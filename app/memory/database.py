import sqlite3
import re

from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config.settings import DATABASE_PATH
from app.utils.logger import logger

def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )
    return sqlite3.connect(DATABASE_PATH)


def initialize_database():
    """Initialize database and safely migrate schema without losing existing data."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        # Create table if not present
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                metadata TEXT
            )
        """)

        # Safe schema migration for existing databases
        cursor.execute("PRAGMA table_info(memories)")
        columns = [col[1] for col in cursor.fetchall()]

        if "category" not in columns:
            cursor.execute("ALTER TABLE memories ADD COLUMN category TEXT DEFAULT 'general'")
            logger.info("Migrated memories table: added category column")

        if "updated_at" not in columns:
            cursor.execute("ALTER TABLE memories ADD COLUMN updated_at TIMESTAMP")
            logger.info("Migrated memories table: added updated_at column")

        if "metadata" not in columns:
            cursor.execute("ALTER TABLE memories ADD COLUMN metadata TEXT")
            logger.info("Migrated memories table: added metadata column")

        conn.commit()
    finally:
        conn.close()


def save_memory(content: str, category: str = "general") -> bool:
    """Save an explicit memory to the database."""
    content = content.strip()
    if not content:
        return False

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memories (content, category) VALUES (?, ?)",
            (content, category)
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(f"Saved memory ({category}): {content[:40]}...")
    return True


def get_memories(limit: int = 10, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve saved memories, newest first."""
    conn = get_connection()
    try:
        cursor = conn.cursor()

        if category:
            cursor.execute(
                """
                SELECT id, content, category, created_at
                FROM memories
                WHERE category = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (category, limit)
            )
        else:
            cursor.execute(
                """
                SELECT id, content, category, created_at
                FROM memories
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,)
            )

        rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": row[0],
            "content": row[1],
            "category": row[2] if len(row) > 2 else "general",
            "created_at": row[3] if len(row) > 3 else None,
        }
        for row in rows
    ]


def search_memories(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search memories using SQL LIKE match."""
    query = query.strip()
    if not query:
        return []

    pattern = f"%{query}%"
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, content, category, created_at
            FROM memories
            WHERE content LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (pattern, limit)
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        {
            "id": row[0],
            "content": row[1],
            "category": row[2],
            "created_at": row[3],
        }
        for row in rows
    ]
MEMORY_STOP_WORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "i",
    "me",
    "my",
    "mine",
    "you",
    "your",
    "yours",
    "we",
    "our",
    "ours",
    "they",
    "their",
    "what",
    "which",
    "who",
    "where",
    "when",
    "why",
    "how",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "with",
    "and",
    "or",
    "that",
    "this",
    "it",
}


def _normalize_word(word: str) -> str:
    """
    Perform tiny normalization for memory matching.

    This is intentionally lightweight.
    Semantic embeddings will replace/improve this in Phase B.
    """
    word = word.lower().strip()

    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]

    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]

        # preferred -> preferr -> prefer
        if len(word) >= 2 and word[-1] == word[-2]:
            word = word[:-1]

    elif len(word) > 4 and word.endswith("s"):
        word = word[:-1]

    return word


def _tokenize_memory_text(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())

    tokens = []

    for word in words:
        if word in MEMORY_STOP_WORDS:
            continue

        normalized = _normalize_word(word)

        if normalized and normalized not in MEMORY_STOP_WORDS:
            tokens.append(normalized)

    return tokens


def _calculate_memory_relevance(query: str, memory_content: str) -> float:
    """
    Return a lightweight relevance score between 0 and 1.

    Phase A intentionally avoids embedding dependencies.
    """

    query_tokens = set(_tokenize_memory_text(query))
    memory_tokens = set(_tokenize_memory_text(memory_content))

    if not query_tokens or not memory_tokens:
        return 0.0

    direct_matches = query_tokens.intersection(memory_tokens)

    overlap_score = len(direct_matches) / len(query_tokens)

    fuzzy_matches = 0

    unmatched_query = query_tokens - direct_matches
    unmatched_memory = memory_tokens - direct_matches

    for query_word in unmatched_query:
        for memory_word in unmatched_memory:
            similarity = SequenceMatcher(
                None,
                query_word,
                memory_word
            ).ratio()

            if similarity >= 0.82:
                fuzzy_matches += 1
                break

    fuzzy_score = fuzzy_matches / len(query_tokens)

    score = overlap_score + (fuzzy_score * 0.5)

    return min(score, 1.0)


def get_relevant_memories(
    query: str,
    limit: int = 3,
    min_score: float = 0.25,
) -> List[Dict[str, Any]]:
    """
    Retrieve memories relevant to a natural-language query.

    Phase A uses lightweight token/fuzzy matching.
    Phase B will introduce embedding-based semantic retrieval.
    """

    query = query.strip()

    if not query:
        return []

    # Search a reasonable recent window rather than loading
    # an unlimited database into memory.
    memories = get_memories(limit=100)

    ranked = []

    for memory in memories:
        score = _calculate_memory_relevance(
            query,
            memory["content"],
        )

        if score >= min_score:
            item = dict(memory)
            item["relevance_score"] = score
            ranked.append(item)

    ranked.sort(
        key=lambda memory: (
            memory["relevance_score"],
            memory["id"],
        ),
        reverse=True,
    )

    return ranked[:limit]

def forget_memory(memory_id: int) -> bool:
    """Delete a memory by its ID."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
    finally:
        conn.close()

    if deleted:
        logger.info(f"Deleted memory with ID {memory_id}")
    return deleted


def format_memories_display(memories: List[Dict[str, Any]]) -> str:
    """Format a list of memory dicts for CLI output."""
    if not memories:
        return "I don't have any saved memories yet."

    lines = ["Saved memories:"]
    for m in memories:
        category_tag = f" [{m.get('category', 'general')}]" if m.get('category') != 'general' else ""
        lines.append(f"{m['id']}. {m['content']}{category_tag}")

    return "\n".join(lines)