import unittest
from unittest.mock import MagicMock, patch
from app.brain.orchestrator import JarvisOrchestrator
from app.state.session import session_manager


class TestOrchestrator(unittest.TestCase):

    def setUp(self):
        self.mock_brain = MagicMock()
        self.mock_brain.ask.return_value = "Mocked LLM explanation."
        self.orchestrator = JarvisOrchestrator(brain=self.mock_brain)

    def test_empty_message(self):
        resp = self.orchestrator.process("")
        self.assertTrue(resp.success)
        self.assertEqual(resp.intent, "chat")
        self.assertIn("assist", resp.response.lower())

    def test_chat_intent_routing(self):
        resp = self.orchestrator.process("Explain quantum computing", session_id="test-session-1")
        self.assertTrue(resp.success)
        self.assertEqual(resp.intent, "chat")
        self.assertEqual(resp.response, "Mocked LLM explanation.")
        self.assertEqual(resp.session_id, "test-session-1")
        self.assertIsNone(resp.tool_used)
        self.mock_brain.ask.assert_called_once()

    def test_system_tool_routing(self):
        resp = self.orchestrator.process("system info")
        self.assertTrue(resp.success)
        self.assertEqual(resp.intent, "system")
        self.assertEqual(resp.tool_used, "system_information")
        self.assertIn("Operating System", resp.response)
        self.mock_brain.ask.assert_not_called()

    def test_memory_tool_routing(self):
        resp = self.orchestrator.process("remember that I use Python for data science")
        self.assertTrue(resp.success)
        self.assertEqual(resp.intent, "memory")
        self.assertEqual(resp.tool_used, "remember")
        self.assertIn("Remembered", resp.response)
        self.mock_brain.ask.assert_not_called()

    def test_file_tool_routing_variants(self):
        test_queries = [
            "list files",
            "list the files",
            "show me the files",
            "show files",
            "what files are in this folder?",
            "show the files in the project",
            "list files in the current directory",
        ]
        for query in test_queries:
            self.mock_brain.reset_mock()
            resp = self.orchestrator.process(query)
            self.assertTrue(resp.success, f"Failed for query: {query}")
            self.assertEqual(resp.intent, "file", f"Intent mismatch for query: {query}")
            self.assertEqual(resp.tool_used, "list_files", f"Tool mismatch for query: {query}")
            self.assertIn("Contents of", resp.response, f"Response content mismatch for query: {query}")
            self.mock_brain.ask.assert_not_called()

    def test_multi_session_isolation(self):
        s1 = "session-alpha"
        s2 = "session-beta"

        self.orchestrator.process("Hello from Alpha", session_id=s1)
        self.orchestrator.process("Hello from Beta", session_id=s2)

        session_a = session_manager.get_session(s1)
        session_b = session_manager.get_session(s2)

        self.assertIn("Hello from Alpha", [m["content"] for m in session_a.history])
        self.assertNotIn("Hello from Alpha", [m["content"] for m in session_b.history])

    def test_graceful_error_handling(self):
        self.mock_brain.ask.side_effect = Exception("Ollama connection failed")
        resp = self.orchestrator.process("Tell me a story")
        # Should return response indicating error or failed gracefully
        self.assertIn("Ollama connection failed", resp.response)


if __name__ == "__main__":
    unittest.main()
