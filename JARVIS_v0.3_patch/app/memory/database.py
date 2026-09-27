import sqlite3
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



def retrieve_relevant_memories(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Return memories that are lexically relevant to a conversational query.

    This lightweight scorer intentionally avoids embeddings for v0.3's first
    step. It tokenizes both the query and stored memories, ignores common
    filler words, rewards exact phrase/term overlap, and uses recency only as a
    small tie-breaker.
    """
    import re

    query = query.strip().lower()
    if not query:
        return []

    stop_words = {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "do",
        "for", "from", "how", "i", "in", "is", "it", "me", "my", "of",
        "on", "or", "that", "the", "this", "to", "was", "what", "when",
        "where", "which", "who", "why", "with", "you", "your", "can",
        "could", "would", "should", "tell", "about", "please",
    }

    def tokens(text: str) -> set[str]:
        return {
            token for token in re.findall(r"[a-z0-9_+.#-]+", text.lower())
            if len(token) > 1 and token not in stop_words
        }

    query_tokens = tokens(query)
    if not query_tokens:
        return []

    # Memories are explicitly user-saved and expected to stay relatively
    # small. Reading a bounded recent set keeps this simple and predictable.
    candidates = get_memories(limit=200)
    scored = []
    for index, memory in enumerate(candidates):
        content = memory.get("content", "")
        content_lower = content.lower()
        memory_tokens = tokens(content_lower)
        overlap = query_tokens & memory_tokens
        if not overlap:
            continue

        score = float(len(overlap) * 3)
        score += sum(1.0 for term in overlap if term in content_lower)

        # Reward multi-word query fragments when present verbatim.
        meaningful_query = " ".join(
            token for token in re.findall(r"[a-z0-9_+.#-]+", query)
            if token not in stop_words
        )
        if meaningful_query and meaningful_query in content_lower:
            score += 4.0

        # Small recency tie-breaker: candidates are newest first.
        score += max(0.0, 0.5 - index * 0.002)
        scored.append((score, memory))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in scored[:limit]]

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