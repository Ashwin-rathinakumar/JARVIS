import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from app.voice.runtime import VoiceRuntime
from app.voice.stt import MockSTT, BaseSTT
from app.voice.tts import MockTTS, BaseTTS
from app.voice.microphone import Microphone
from app.voice.models import AudioData, TranscribedUtterance
from app.brain.orchestrator import JarvisOrchestrator
from app.tools.registry import ToolResult
from app.config.settings import WORKSPACE_DIR, BASE_DIR
from app.agent.audit import get_recent_action_records


import numpy as np
from app.state.session import session_manager

import shutil

class TestVoiceRuntime(unittest.TestCase):

    def setUp(self):
        self.mock_brain = MagicMock()
        self.mock_brain.ask.return_value = "Mocked LLM answer"
        self.orchestrator = JarvisOrchestrator(brain=self.mock_brain)
        self.mock_stt = MockSTT()
        self.mock_tts = MockTTS()
        self.session_id = f"test-voice-runtime-{self._testMethodName}"
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
        for name in ["voice_runtime_protected", "voice_workspace_test"]:
            p = WORKSPACE_DIR / name
            if p.exists():
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)

    def test_stt_transcript_reaches_jarvis_core(self):
        resp = self.runtime.handle_transcript("give me system information")
        self.assertTrue(resp.success)
        self.assertEqual(resp.intent, "system")
        self.assertIn("Operating System", resp.response)
        self.assertIn("Operating System", self.mock_tts.spoken_messages[0])

    def test_empty_transcript_does_not_invoke_tools(self):
        resp = self.runtime.handle_transcript("")
        self.assertTrue(resp.success)
        self.assertEqual(resp.intent, "chat")
        self.assertIn("didn't catch that", resp.response.lower())

    def test_safe_command_executes_normally(self):
        resp = self.runtime.handle_transcript("list the files")
        self.assertTrue(resp.success)
        self.assertEqual(resp.intent, "file")
        self.assertIn("Contents of", resp.response)

    def test_protected_command_generates_confirmation(self):
        resp = self.runtime.handle_transcript("create a folder called voice_runtime_protected")
        self.assertTrue(resp.success)
        self.assertEqual(resp.status, "confirmation_required")
        self.assertIsNotNone(resp.confirmation_id)
        self.assertIn("confirmation", self.mock_tts.spoken_messages[0].lower())

    def test_raw_transcripts_never_become_shell_commands(self):
        # Transcripts like "rm -rf /" or "powershell Get-Process" must not execute raw shell
        resp = self.runtime.handle_transcript("run powershell and execute Get-Process")
        # Should either generate confirmation for project or be denied, never execute raw shell
        self.assertNotEqual(resp.intent, "raw_shell")
        self.assertTrue(resp.status == "confirmation_required" or "denied" in resp.response.lower())

    def test_workspace_confinement_for_voice_creations(self):
        # Voice folder creation must resolve to WORKSPACE_DIR/voice_workspace_test
        resp = self.runtime.handle_transcript("create a folder called voice_workspace_test")
        token = resp.confirmation_id
        self.assertIsNotNone(token)

        # Confirm
        resp_conf = self.runtime.handle_transcript("yes")
        expected_path = (WORKSPACE_DIR / "voice_workspace_test").resolve()
        self.assertTrue(expected_path.exists())
        self.assertFalse((BASE_DIR / "voice_workspace_test").exists())

    def test_source_metadata_is_voice_in_audit_logs(self):
        self.runtime.handle_transcript("system information")
        records = get_recent_action_records(limit=5)
        self.assertGreaterEqual(len(records), 1)
        latest = records[0]
        self.assertEqual(latest.source, "voice")

    def test_microphone_failure_handled_safely(self):
        mock_mic = MagicMock()
        mock_mic.capture_push_to_talk.return_value = None  # Simulates hardware failure
        runtime = VoiceRuntime(
            orchestrator=self.orchestrator,
            microphone=mock_mic,
            stt=self.mock_stt,
            tts=self.mock_tts,
        )
        resp = runtime.listen_and_process()
        self.assertFalse(resp.success)
        self.assertEqual(resp.error, "AUDIO_CAPTURE_FAILED")

    def test_stt_failure_handled_safely(self):
        mock_mic = MagicMock()
        mock_mic.capture_push_to_talk.return_value = AudioData(samples=np.zeros(16000), sample_rate=16000)
        mock_stt = MagicMock()
        mock_stt.transcribe.return_value = TranscribedUtterance(text="", confidence=0.0)
        runtime = VoiceRuntime(
            orchestrator=self.orchestrator,
            microphone=mock_mic,
            stt=mock_stt,
            tts=self.mock_tts,
        )
        resp = runtime.listen_and_process()
        self.assertTrue(resp.success)
        self.assertIn("didn't catch that", resp.response)

    def test_tts_failure_does_not_crash_runtime(self):
        mock_failing_tts = MagicMock()
        mock_failing_tts.speak.side_effect = Exception("Sound device playback error")
        runtime = VoiceRuntime(
            orchestrator=self.orchestrator,
            stt=self.mock_stt,
            tts=mock_failing_tts,
        )
        # Runtime should not crash when TTS raises exception
        resp = runtime.handle_transcript("system info")
        self.assertTrue(resp.success)

    def test_weather_uses_unified_voice_output(self):
        weather = ToolResult(
            True,
            "Current weather in Chennai: partly cloudy, 30°C.",
            tool="get_weather",
        )
        with patch("app.brain.orchestrator.execute_tool", return_value=weather) as execute:
            resp = self.runtime.handle_transcript("What's the weather in Chennai?")

        execute.assert_called_once_with("get_weather", {"location": "Chennai", "when": "current"})
        self.assertEqual(resp.intent, "current_info")
        self.assertEqual(resp.tool_used, "get_weather")
        self.assertEqual(self.mock_tts.spoken_messages[-1], weather.message)


if __name__ == "__main__":
    unittest.main()
