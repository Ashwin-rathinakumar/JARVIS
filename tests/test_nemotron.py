import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from app.brain.llm import JarvisBrain
from app.brain.orchestrator import JarvisOrchestrator
from app.brain.providers.mock import MockProvider
from app.brain.providers.nemotron import NemotronProvider
from app.brain.reasoning import parse_reasoning_plan
from app.runtime.core import JarvisRuntime
from app.runtime.state import RuntimeState
from app.tools.registry import ToolResult
from app.voice.stt import MockSTT
from app.voice.tts import MockTTS


def http_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class TestNemotronProvider(unittest.TestCase):
    def test_provider_selection(self):
        self.assertIsInstance(JarvisBrain("nemotron").provider, NemotronProvider)
        self.assertEqual(JarvisBrain("ollama").provider_name, "ollama")

    @patch("app.brain.providers.nemotron.requests.post")
    def test_openai_compatible_general_query(self, post):
        post.return_value = http_response({"choices": [{"message": {"content": "Recursion uses self-reference."}}]})
        provider = NemotronProvider(base_url="http://192.168.1.20:8000/v1", model="nemotron-test")
        self.assertIn("self-reference", provider.ask("What is recursion?"))
        self.assertEqual(provider.endpoint_category, "LAN")
        self.assertTrue(post.call_args.args[0].endswith("/chat/completions"))
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])

    def test_deterministic_commands_bypass_model(self):
        provider = MockProvider("should not be used")
        brain = JarvisBrain("mock")
        brain.provider = provider
        orchestrator = JarvisOrchestrator(brain=brain)
        with patch("app.brain.orchestrator.execute_tool", return_value=ToolResult(True, "ok")):
            for command in ["Show system information.", "Open K.E.E.R.", "What's the weather in Chennai?"]:
                orchestrator.process(command, session_id="nemotron-bypass")
        self.assertEqual(provider.requests, [])

    def test_primary_failure_uses_one_configured_fallback(self):
        brain = JarvisBrain("mock")
        brain.provider = MagicMock()
        brain.provider.ask.side_effect = RuntimeError("offline")
        brain.fallback_provider_name = "mock-fallback"
        brain.fallback_provider = MockProvider("fallback answer")
        self.assertEqual(brain.ask("hello"), "fallback answer")
        self.assertEqual(len(brain.fallback_provider.requests), 1)

    def test_total_failure_is_truthful(self):
        brain = JarvisBrain("mock")
        brain.provider = MagicMock()
        brain.provider.ask.side_effect = RuntimeError("primary offline")
        brain.fallback_provider = MagicMock()
        brain.fallback_provider.ask.side_effect = RuntimeError("fallback offline")
        answer = brain.ask("hello")
        self.assertIn("fallback offline", answer)

    @patch("app.brain.providers.nemotron.requests.post", side_effect=requests.exceptions.Timeout())
    def test_timeout_is_bounded_and_runtime_recovers(self, _post):
        brain = JarvisBrain("nemotron")
        brain.fallback_provider = None
        runtime = JarvisRuntime(orchestrator=JarvisOrchestrator(brain=brain), microphone=MagicMock(),
                                stt=MockSTT(), tts=MockTTS(), session_id="nemotron-timeout")
        response = runtime.process_transcript("What is recursion?")
        self.assertIn("timed out", response.response.lower())
        self.assertEqual(runtime.state, RuntimeState.IDLE)

    def test_bounded_context_reaches_provider(self):
        provider = MockProvider("answer")
        brain = JarvisBrain("mock")
        brain.provider = provider
        orchestrator = JarvisOrchestrator(brain=brain)
        orchestrator.process("Tell me about black holes.", session_id="reasoning-context")
        orchestrator.process("What happens at the event horizon?", session_id="reasoning-context")
        history = provider.requests[1]["history"]
        self.assertTrue(any("black holes" in turn["content"] for turn in history))

    def test_multiple_nemotron_turns_in_one_persistent_runtime(self):
        brain = JarvisBrain("mock")
        brain.provider = MockProvider("reasoning response")
        runtime = JarvisRuntime(orchestrator=JarvisOrchestrator(brain=brain), microphone=MagicMock(),
                                stt=MockSTT(), tts=MockTTS(), session_id="nemotron-continuous")
        for prompt in ["Hello JARVIS.", "What is recursion?", "Tell me about black holes.",
                       "What happens near the event horizon?"]:
            self.assertTrue(runtime.process_transcript(prompt).success)
            self.assertEqual(runtime.state, RuntimeState.IDLE)
        self.assertEqual(len(brain.provider.requests), 4)
        self.assertTrue(any("black holes" in turn["content"] for turn in brain.provider.requests[-1]["history"]))
        runtime.shutdown()
        self.assertEqual(runtime.state, RuntimeState.STOPPED)

    def test_valid_plan_is_parsed_but_never_executed(self):
        raw = json.dumps({"type": "plan", "objective": "diagnose", "steps": ["inspect", "test"],
                          "requires_tools": True, "proposed_actions": ["run tests"]})
        with patch("app.brain.orchestrator.execute_tool") as execute:
            plan = parse_reasoning_plan(raw)
        self.assertEqual(plan.objective, "diagnose")
        execute.assert_not_called()

    def test_malformed_or_hostile_plan_executes_nothing(self):
        hostile = '{"type":"plan","objective":"bad","steps":"rm -rf /","proposed_actions":["taskkill","PowerShell C:/outside"]}'
        with patch("app.brain.orchestrator.execute_tool") as execute:
            self.assertIsNone(parse_reasoning_plan(hostile))
        execute.assert_not_called()

    def test_model_status_is_safe_and_deterministic(self):
        brain = JarvisBrain("mock")
        brain.provider = MockProvider()
        response = JarvisOrchestrator(brain=brain).process("What model are you using?", session_id="model-status")
        self.assertEqual(response.tool_used, "model_status")
        self.assertNotIn("api_key", response.response.lower())
        self.assertEqual(brain.provider.requests, [])


if __name__ == "__main__":
    unittest.main()
