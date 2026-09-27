import unittest
from unittest.mock import MagicMock, patch

from app.brain.orchestrator import JarvisOrchestrator
from app.runtime.activation import MockWakeWordProvider, SilenceThresholdVAD, WakeWordDetector, TranscriptWakeWordProvider
from app.runtime.core import JarvisRuntime
from app.runtime.state import RuntimeState, RuntimeStateMachine
from app.tools.registry import ToolResult
from app.voice.models import AudioData
from app.voice.stt import MockSTT
from app.voice.tts import MockTTS


class TestPersistentRuntime(unittest.TestCase):
    def make_runtime(self, wake=None):
        mic = MagicMock()
        mic.capture_push_to_talk.return_value = AudioData(b"\0\0" * 100)
        return JarvisRuntime(
            orchestrator=JarvisOrchestrator(brain=MagicMock()), microphone=mic,
            stt=MockSTT(), tts=MockTTS(), wake_provider=wake, session_id=self.id(),
        )

    def test_state_machine_rejects_illegal_transition(self):
        states = RuntimeStateMachine()
        states.transition(RuntimeState.THINKING)
        with self.assertRaises(ValueError):
            states.transition(RuntimeState.LISTENING)

    def test_multiple_turns_return_to_idle(self):
        runtime = self.make_runtime()
        runtime.voice.orchestrator.brain.ask.return_value = "Hello."
        response = runtime.process_transcript("Hello JARVIS")
        self.assertTrue(response.success)
        self.assertEqual(runtime.state, RuntimeState.IDLE)
        self.assertIn(RuntimeState.THINKING, [entry.current for entry in runtime.state_machine.transitions])
        self.assertIn(RuntimeState.SPEAKING, [entry.current for entry in runtime.state_machine.transitions])

    def test_weather_follow_up_inherits_location(self):
        runtime = self.make_runtime()
        results = [
            ToolResult(True, "Current weather in Chennai: clear sky.", tool="get_weather"),
            ToolResult(True, "Weather for Chennai tomorrow: rain.", tool="get_weather"),
        ]
        with patch("app.brain.orchestrator.execute_tool", side_effect=results) as execute:
            runtime.process_transcript("What's the weather in Chennai?")
            response = runtime.process_transcript("What about tomorrow?")
        self.assertTrue(response.success)
        self.assertEqual(execute.call_args_list[1].args, ("get_weather", {"location": "Chennai", "when": "tomorrow"}))

    def test_project_follow_up_inherits_project(self):
        runtime = self.make_runtime()
        results = [ToolResult(True, "Opened Sentinel AI in VS Code.", tool="open_project"),
                   ToolResult(True, "Closed Sentinel AI.", tool="close_project")]
        with patch("app.brain.orchestrator.execute_tool", side_effect=results) as execute:
            runtime.process_transcript("Open Sentinel AI")
            response = runtime.process_transcript("Close it")
        self.assertTrue(response.success)
        self.assertEqual(execute.call_args_list[1].args[0], "close_project")
        self.assertEqual(execute.call_args_list[1].args[1]["project_name"], "Sentinel AI")

    def test_context_does_not_bypass_confirmation(self):
        runtime = self.make_runtime()
        runtime.process_transcript("Open Sentinel AI")
        response = runtime.process_transcript("Delete it")
        self.assertNotEqual(response.intent, "raw_shell")
        self.assertNotEqual(response.tool_used, "delete_file")

    def test_wake_event_runs_one_capture_cycle(self):
        wake = MockWakeWordProvider()
        runtime = self.make_runtime(wake)
        runtime.stt.queue_response("Show system information")
        with patch("app.brain.orchestrator.execute_tool", return_value=ToolResult(True, "System info", tool="system_information")):
            wake.trigger()
            runtime.start_listening()
            import time
            for _ in range(20):
                if runtime.microphone.capture_push_to_talk.called:
                    break
                time.sleep(0.02)
            runtime.stop_listening()
        self.assertTrue(runtime.microphone.capture_push_to_talk.called)

    def test_vad_threshold(self):
        vad = SilenceThresholdVAD(1.0)
        self.assertFalse(vad.should_stop(False, 4.0))
        self.assertFalse(vad.should_stop(True, 0.9))
        self.assertTrue(vad.should_stop(True, 1.0))

    def test_wake_phrase_and_same_utterance_command(self):
        detector = WakeWordDetector(("hey jarvis", "jarvis"))
        self.assertEqual(detector.extract_command("Hey, JARVIS. Open Sentinel AI"), "Open Sentinel AI")
        self.assertEqual(detector.extract_command("Jarvis!"), "")
        self.assertIsNone(detector.extract_command("I mentioned Jarvis yesterday"))
        mic = MagicMock()
        mic.capture_push_to_talk.return_value = AudioData(b"\0\0" * 100)
        stt = MockSTT()
        stt.queue_response("Hey Jarvis, show system info")
        wake = TranscriptWakeWordProvider(mic, stt, ("hey jarvis",), 1.5)
        self.assertTrue(wake.wait_for_wake(1.5))
        self.assertEqual(wake.take_command(), "show system info")
        self.assertIsNone(wake.take_command())
        mic.capture_push_to_talk.assert_called_once_with(duration=1.5)

    def test_project_tests_follow_up_requests_confirmation(self):
        runtime = self.make_runtime()
        with patch("app.brain.orchestrator.execute_tool", return_value=ToolResult(True, "Opened.", tool="open_project")) as execute:
            runtime.process_transcript("Open Sentinel AI", follow_up=True)
            response = runtime.process_transcript("Run its tests", follow_up=True)
        self.assertEqual(runtime.state, RuntimeState.FOLLOW_UP)
        self.assertEqual(response.status, "confirmation_required")
        self.assertEqual(response.tool_used, "run_project_tests")
        self.assertEqual(execute.call_count, 1)  # No tests before confirmation.
        with patch("app.agent.executor.execute_tool", return_value=ToolResult(True, "Tests passed.", tool="run_project_tests")) as execute_tests:
            confirmed = runtime.process_transcript("Yes", follow_up=True)
        self.assertTrue(confirmed.success)
        self.assertEqual(execute_tests.call_count, 1)
        runtime.shutdown()

    def test_conversation_window_expires_to_idle(self):
        runtime = self.make_runtime()
        runtime.stt.queue_response("")
        with patch("app.runtime.core.JARVIS_FOLLOW_UP_SECONDS", 0.06), patch("app.runtime.core.JARVIS_WAKE_WINDOW_SECONDS", 0.02):
            runtime._conversation_window("")
        self.assertEqual(runtime.state, RuntimeState.IDLE)
        self.assertTrue(runtime.microphone.capture_push_to_talk.called)
        runtime.shutdown()

    def test_shutdown_is_idempotent_and_releases_resources(self):
        runtime = self.make_runtime()
        runtime.shutdown()
        runtime.shutdown()
        self.assertEqual(runtime.state, RuntimeState.STOPPED)
        runtime.microphone.close.assert_called_once()
