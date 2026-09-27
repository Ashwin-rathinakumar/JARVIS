import unittest
from unittest.mock import patch

from app.brain.context import build_conversation_prompt
from app.state.session import session


class TestConversationContext(unittest.TestCase):
    def setUp(self):
        session.clear()

    def tearDown(self):
        session.clear()

    @patch("app.brain.context.retrieve_relevant_memories")
    def test_injects_relevant_memory(self, mock_retrieve):
        mock_retrieve.return_value = [
            {"id": 1, "content": "My preferred editor is VS Code", "category": "general"}
        ]
        prompt = build_conversation_prompt("What editor do I prefer?")
        self.assertIn("Relevant saved memories", prompt)
        self.assertIn("My preferred editor is VS Code", prompt)
        self.assertIn("What editor do I prefer?", prompt)

    @patch("app.brain.context.retrieve_relevant_memories")
    def test_no_context_returns_original_message(self, mock_retrieve):
        mock_retrieve.return_value = []
        message = "Explain quicksort"
        self.assertEqual(build_conversation_prompt(message), message)

    @patch("app.brain.context.retrieve_relevant_memories")
    def test_includes_current_project(self, mock_retrieve):
        mock_retrieve.return_value = []
        session.set_current_project("jarvis")
        prompt = build_conversation_prompt("What am I working on?")
        self.assertIn("Current project key: jarvis", prompt)


if __name__ == "__main__":
    unittest.main()
