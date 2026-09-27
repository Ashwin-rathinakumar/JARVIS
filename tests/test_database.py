import unittest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import patch

from app.memory.database import (
    initialize_database,
    save_memory,
    get_memories,
    search_memories,
    forget_memory,
    format_memories_display,
)


class TestMemoryDatabase(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_jarvis.db"
        self.patcher = patch("app.memory.database.DATABASE_PATH", self.db_path)
        self.patcher.start()
        initialize_database()

    def tearDown(self):
        self.patcher.stop()
        self.temp_dir.cleanup()

    def test_initialize_and_migrate(self):
        # Verify columns exist
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(memories)")
            col_names = [col[1] for col in cursor.fetchall()]
            self.assertIn("id", col_names)
            self.assertIn("content", col_names)
            self.assertIn("category", col_names)
            self.assertIn("created_at", col_names)
            self.assertIn("updated_at", col_names)

    def test_save_and_retrieve_memories(self):
        save_memory("Test memory 1", "work")
        save_memory("Test memory 2", "personal")

        mems = get_memories()
        self.assertEqual(len(mems), 2)
        # Newest first
        self.assertEqual(mems[0]["content"], "Test memory 2")
        self.assertEqual(mems[0]["category"], "personal")

    def test_search_memories(self):
        save_memory("Remember to buy milk")
        save_memory("Write code in Python")

        results = search_memories("Python")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "Write code in Python")

        no_results = search_memories("Rust")
        self.assertEqual(len(no_results), 0)

    def test_forget_memory(self):
        save_memory("Temporary note")
        mems = get_memories()
        mem_id = mems[0]["id"]

        success = forget_memory(mem_id)
        self.assertTrue(success)

        mems_after = get_memories()
        self.assertEqual(len(mems_after), 0)

    def test_format_display(self):
        empty_str = format_memories_display([])
        self.assertIn("I don't have any saved memories yet", empty_str)

        formatted = format_memories_display([{"id": 1, "content": "Sample", "category": "general"}])
        self.assertIn("1. Sample", formatted)


if __name__ == "__main__":
    unittest.main()
