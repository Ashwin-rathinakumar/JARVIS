import unittest
from app.brain.router import execute_command
from app.state.session import session


class TestRouter(unittest.TestCase):

    def setUp(self):
        session.clear()

    def tearDown(self):
        session.clear()

    def test_tool_routing(self):
        # Known deterministic command
        res = execute_command("system info")
        self.assertIsNotNone(res)
        self.assertIn("Operating System", res)
        self.assertEqual(session.last_tool, "system_information")

    def test_chat_fallback(self):
        # Conversational input that should not route to any tool
        res = execute_command("Can you explain how quicksort works in theory?")
        # When intent is chat, execute_command returns None so main() uses brain.ask()
        self.assertIsNone(res)

    def test_project_routing(self):
        res = execute_command("list projects")
        self.assertIn("JARVIS [jarvis]", res)
        self.assertEqual(session.last_tool, "list_projects")


if __name__ == "__main__":
    unittest.main()
