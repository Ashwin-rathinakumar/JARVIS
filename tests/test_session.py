import unittest
from unittest.mock import MagicMock
from app.state.session import SessionState


class TestSessionState(unittest.TestCase):

    def setUp(self):
        self.state = SessionState()

    def test_project_tracking(self):
        self.assertIsNone(self.state.get_current_project())
        self.state.set_current_project("keer")
        self.assertEqual(self.state.get_current_project(), "keer")
        self.state.clear_current_project()
        self.assertIsNone(self.state.get_current_project())

    def test_process_tracking(self):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Running
        self.state.register_process("test_job", mock_proc)
        self.assertEqual(self.state.get_process("test_job"), mock_proc)
        self.assertIn("test_job", self.state.list_active_processes())

        # When process terminates
        mock_proc.poll.return_value = 0
        self.assertIsNone(self.state.get_process("test_job"))
        self.assertNotIn("test_job", self.state.list_active_processes())

    def test_history_bounding(self):
        for i in range(25):
            self.state.add_turn("user", f"message {i}")

        # Check bounded at 20
        self.assertEqual(len(self.state.history), 20)
        recent = self.state.get_recent_history(limit=5)
        self.assertEqual(len(recent), 5)
        self.assertEqual(recent[-1]["content"], "message 24")

    def test_clear(self):
        self.state.set_current_project("jarvis")
        self.state.add_turn("user", "hi")
        self.state.clear()
        self.assertIsNone(self.state.get_current_project())
        self.assertEqual(len(self.state.history), 0)


if __name__ == "__main__":
    unittest.main()
