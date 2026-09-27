import unittest
from unittest.mock import MagicMock, patch

from app.brain.orchestrator import JarvisOrchestrator
from app.runtime.activation import MockWakeWordProvider, SilenceThresholdVAD
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

    def test_shutdown_is_idempotent_and_releases_resources(self):
        runtime = self.make_runtime()
        runtime.shutdown()
        runtime.shutdown()
        self.assertEqual(runtime.state, RuntimeState.STOPPED)
        runtime.microphone.close.assert_called_once()
