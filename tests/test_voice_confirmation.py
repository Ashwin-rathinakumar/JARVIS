import unittest
from unittest.mock import MagicMock
from pathlib import Path

from app.voice.runtime import VoiceRuntime
from app.voice.stt import MockSTT
from app.voice.tts import MockTTS
from app.brain.orchestrator import JarvisOrchestrator
from app.brain.confirmation import confirmation_manager
from app.state.session import session_manager
from app.config.settings import WORKSPACE_DIR
from app.agent.audit import get_recent_action_records


import shutil

class TestVoiceConfirmation(unittest.TestCase):

    def setUp(self):
        self.mock_brain = MagicMock()
        self.mock_brain.ask.return_value = "Mock response"
        self.orchestrator = JarvisOrchestrator(brain=self.mock_brain)
        self.mock_stt = MockSTT()
        self.mock_tts = MockTTS()
        self.session_id = f"test-voice-conf-{self._testMethodName}"
        session_manager.delete_session(self.session_id)
        self._cleanup_test_dirs()
        self.runtime = VoiceRuntime(
            orchestrator=self.orchestrator,
            stt=self.mock_stt,
            tts=self.mock_tts,
            session_id=self.session_id,
        )

    def tearDown(self):
        self._cleanup_test_dirs()

    def _cleanup_test_dirs(self):
        for name in ["voice_conf_yes", "voice_conf_no", "voice_conf_ambiguous", "voice_conf_expired"]:
            p = WORKSPACE_DIR / name
            if p.exists():
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)

    def test_voice_confirmation_flow_yes(self):
        # 1. User issues action requiring confirmation
        resp1 = self.runtime.handle_transcript("create a folder called voice_conf_yes")
        self.assertEqual(resp1.status, "confirmation_required")
        self.assertIsNotNone(resp1.confirmation_id)

        # Verify folder not created yet
        target_dir = WORKSPACE_DIR / "voice_conf_yes"
        self.assertFalse(target_dir.exists())

        # 2. User confirms with "yes"
        resp2 = self.runtime.handle_transcript("yes")
        self.assertEqual(resp2.status, "completed")
        self.assertTrue(target_dir.exists())
        self.assertIn("Created folder", resp2.response)

    def test_voice_confirmation_flow_no(self):
        # 1. User issues action requiring confirmation
        resp1 = self.runtime.handle_transcript("create a folder called voice_conf_no")
        self.assertEqual(resp1.status, "confirmation_required")

        target_dir = WORKSPACE_DIR / "voice_conf_no"
        self.assertFalse(target_dir.exists())

        # 2. User cancels with "no"
        resp2 = self.runtime.handle_transcript("no")
        self.assertIn("cancelled", resp2.response.lower())
        self.assertFalse(target_dir.exists())

    def test_voice_ambiguous_confirmation_does_not_execute(self):
        # 1. User issues action requiring confirmation
        resp1 = self.runtime.handle_transcript("create a folder called voice_conf_ambiguous")
        self.assertEqual(resp1.status, "confirmation_required")

        target_dir = WORKSPACE_DIR / "voice_conf_ambiguous"
        self.assertFalse(target_dir.exists())

        # 2. User says "maybe"
        resp2 = self.runtime.handle_transcript("maybe")
        self.assertEqual(resp2.status, "confirmation_required")
        self.assertIn("didn't receive a clear confirmation", resp2.response)
        self.assertFalse(target_dir.exists())

    def test_expired_confirmation_token_handled_safely(self):
        # 1. Create a confirmation
        resp1 = self.runtime.handle_transcript("create a folder called voice_conf_expired")
        token = resp1.confirmation_id
        self.assertIsNotNone(token)

        # Manually consume or invalidate token to simulate expiration
        confirmation_manager.consume_confirmation(token)

        # 2. User tries to confirm
        resp2 = self.runtime.handle_transcript("yes")
        self.assertFalse(resp2.success)
        self.assertIn("expired", resp2.response.lower())


if __name__ == "__main__":
    unittest.main()
