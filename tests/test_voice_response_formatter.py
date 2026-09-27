import unittest
from app.response.formatter import ResponseFormatter
from app.core.schemas import ChatResponse


class TestVoiceResponseFormatter(unittest.TestCase):

    def test_empty_response_formatting(self):
        self.assertEqual(ResponseFormatter.format_for_voice(""), "I didn't catch that.")
        self.assertEqual(ResponseFormatter.format_for_voice(None), "I didn't catch that.")

    def test_confirmation_required_formatting(self):
        resp = ChatResponse(
            success=True,
            intent="file",
            response="This action requires confirmation:\nCreate directory: agent_test\n\nProceed? [y/N]",
            session_id="test-session",
            status="confirmation_required",
        )
        formatted = ResponseFormatter.format_for_voice(resp)
        self.assertIn("requires confirmation", formatted.lower())
        self.assertIn("continue", formatted.lower())

    def test_permission_denied_formatting(self):
        resp = ChatResponse(
            success=False,
            intent="file",
            response="Access denied: Writing executable or script files (.ps1) is strictly blocked.",
            session_id="test-session",
            error="PERMISSION_DENIED",
        )
        formatted = ResponseFormatter.format_for_voice(resp)
        self.assertIn("Action denied", formatted)
        self.assertIn("strictly blocked", formatted)

    def test_creation_formatting(self):
        res1 = ResponseFormatter.format_for_voice("Created folder: C:\\JARVIS\\workspace\\voice_test")
        self.assertEqual(res1, "Created the folder C:\\JARVIS\\workspace\\voice_test.")

        res2 = ResponseFormatter.format_for_voice("Created file: C:\\JARVIS\\workspace\\notes.txt")
        self.assertEqual(res2, "Created the file C:\\JARVIS\\workspace\\notes.txt.")

    def test_markdown_cleaning(self):
        raw = "Here is the result:\n* item 1\n* item 2\n```python\nprint('hello')\n```"
        formatted = ResponseFormatter.format_for_voice(raw)
        self.assertNotIn("```", formatted)
        self.assertNotIn("*", formatted)


if __name__ == "__main__":
    unittest.main()
