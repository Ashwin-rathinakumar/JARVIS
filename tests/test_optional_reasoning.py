"""Local routing must not depend on optional model availability."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.brain.llm import JarvisBrain
from app.brain.orchestrator import JarvisOrchestrator
from app.brain import prompts, semantic
from app.config.projects import PROJECTS
from app.state.session import session_manager
from app.tools.registry import ToolResult
from app.voice.runtime import VoiceRuntime
from app.voice.stt import MockSTT
from app.voice.tts import MockTTS


class OptionalReasoningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name in ("streetlight", "sentinel"):
            (self.root / name / "backend").mkdir(parents=True)
        registry = patch.dict(PROJECTS, {name: {"name": name.title(), "path": str(self.root / name), "aliases": [name]}
                                      for name in ("streetlight", "sentinel")}, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.sid = self.id()
        self.addCleanup(session_manager.delete_session, self.sid)
        self.brain = JarvisBrain("none")
        self.orch = JarvisOrchestrator(self.brain)
        self.execute = MagicMock(side_effect=self.result)
        for target in ("app.brain.orchestrator.execute_tool", "app.agent.executor.execute_tool"):
            mocked = patch(target, self.execute)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.model_call = patch.object(self.brain, "decide", side_effect=AssertionError("Local command requested model reasoning"))
        self.model_call.start()
        self.addCleanup(self.model_call.stop)

    def result(self, tool, args):
        if tool == "git_status":
            return ToolResult(True, "Branch local. Clean.", data={"branch": "local", "project": args["project_name"], "staged": [], "modified": [], "untracked": [], "remotes": []})
        if tool in {"project_folder", "open_project_folder"}:
            path = self.root / args["project_name"].lower() / args.get("folder", "backend")
            return ToolResult(True, "Folder located.", data={"path": str(path)})
        return ToolResult(True, "Completed " + tool)

    def say(self, message):
        return self.orch.process(message, self.sid)

    def select(self):
        self.assertTrue(self.say("Open Streetlight.").success)

    def test_project_open_without_provider(self):
        self.select()
        self.assertIsNone(self.brain.provider)
        self.assertEqual(session_manager.get_session(self.sid).conversation_context.active_project, "Streetlight")

    def test_project_followup_without_provider(self):
        self.select()
        self.assertEqual(self.say("Open its backend.").tool_used, "open_project_folder")
        self.assertEqual(self.say("Open that folder.").tool_used, "open_folder")

    def test_git_status_without_provider(self):
        self.select()
        self.assertEqual(self.say("Check its git status.").tool_used, "git_status")
        self.assertEqual(self.execute.call_args.args[1]["project_name"], "streetlight")

    def test_system_queries_without_provider(self):
        for command in ("system info", "What's my operating system?", "What CPU do I have?"):
            self.assertEqual(self.say(command).tool_used, "system_information")
        self.assertEqual(self.say("What Python version am I running?").tool_used, "python_version")

    def test_confirmation_without_provider(self):
        self.select()
        self.assertEqual(self.say("Push it.").status, "confirmation_required")
        self.execute.reset_mock()
        self.assertTrue(self.say("yes").success)
        self.execute.assert_called_once_with("git_push", {"project_name": "streetlight"})

    def test_references_without_provider(self):
        self.select()
        for command in ("Open it", "Open that", "Open this project"):
            self.assertEqual(self.say(command).tool_used, "open_project")
        self.assertEqual(self.say("Push the repo").status, "confirmation_required")
        self.assertEqual(self.say("What branch is it on first?").tool_used, "git_status")
        self.assertIn("cancelled", self.say("no").response)

    def test_replacement_without_provider(self):
        self.select()
        self.say("Push it")
        self.assertEqual(self.say("Actually push Sentinel instead").status, "confirmation_required")
        self.say("yes")
        self.execute.assert_called_with("git_push", {"project_name": "sentinel"})

    def test_voice_uses_local_pipeline_without_provider(self):
        voice = VoiceRuntime(self.orch, microphone=MagicMock(), stt=MockSTT(), tts=MockTTS(), session_id=self.sid)
        for command, tool in [("Open Streetlight", "open_project"), ("Check its git status", "git_status"), ("What's my operating system?", "system_information")]:
            self.assertEqual(voice.handle_transcript(command).tool_used, tool)
        self.assertEqual(voice.handle_transcript("Push it").status, "confirmation_required")
        self.assertIn("cancelled", voice.handle_transcript("no").response)

    def test_disabled_startup_never_initializes_adapter_or_fallback(self):
        with patch.object(JarvisBrain, "_init_provider", side_effect=AssertionError("Adapter initialized")):
            for name in ("none", "", "disabled", "off"):
                brain = JarvisBrain(name)
                self.assertIsNone(brain.provider)
                self.assertIsNone(brain.fallback_provider)
                self.assertFalse(brain.health_check()["connected"])
                brain.close()

    def test_default_configuration_can_disable_provider(self):
        with patch("app.brain.llm.LLM_PROVIDER", "none"), patch.object(JarvisBrain, "_init_provider") as initialize:
            self.assertIsNone(JarvisBrain().provider)
            initialize.assert_not_called()

    def test_provider_initialization_failure_does_not_break_startup(self):
        with patch.object(JarvisBrain, "_init_provider", side_effect=RuntimeError("unavailable")):
            brain = JarvisBrain("ollama")
        self.assertTrue(JarvisOrchestrator(brain).process("system info", self.sid).success)
        self.assertFalse(brain.status()["available"])

    def test_unreachable_model_does_not_break_local_tools(self):
        brain = JarvisBrain("mock")
        brain.provider.ask = MagicMock(side_effect=TimeoutError("offline"))
        orch = JarvisOrchestrator(brain)
        self.assertTrue(orch.process("Open Streetlight", self.sid).success)
        self.assertEqual(orch.process("Check its git status", self.sid).tool_used, "git_status")
        self.assertEqual(orch.process("What's my operating system?", self.sid).tool_used, "system_information")
        brain.provider.ask.assert_not_called()

    def test_no_provider_general_question_is_clear(self):
        brain = JarvisBrain("none")
        response = JarvisOrchestrator(brain).process("What is a black hole?", self.sid)
        self.assertFalse(response.success)
        self.assertIn("No conversational model", response.response)
        self.assertIn("Local project", response.response)
        self.assertIn("No conversational model", brain.ask("Hello"))
        self.assertIn("No conversational model", brain.generate("Hello"))
        self.assertIn("No conversational model", brain.chat([]))

    def test_runtime_prompts_are_provider_neutral(self):
        forbidden = "astra"
        for value in (prompts.SYSTEM_PROMPT, prompts.NEMOTRON_SYSTEM_PROMPT,
                      semantic.decision_prompt("hello", session_manager.get_session(self.sid))):
            self.assertNotIn(forbidden, value.lower())
        import app.config.settings as settings
        self.assertFalse(any(name.startswith(forbidden.upper() + "_") for name in vars(settings)))

    def test_unknown_provider_does_not_select_an_implicit_endpoint(self):
        with patch("app.brain.llm.JARVIS_LLM_FALLBACK_ENABLED", False), patch("app.brain.llm.OllamaProvider") as ollama:
            brain = JarvisBrain("unknown-adapter")
            self.assertIsNone(brain.provider)
            ollama.assert_not_called()


if __name__ == "__main__":
    unittest.main()
