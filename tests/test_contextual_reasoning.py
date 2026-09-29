import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.brain.llm import JarvisBrain
from app.brain.orchestrator import JarvisOrchestrator
from app.brain.providers.mock import MockProvider
from app.brain.semantic import parse_decision, decision_prompt, capabilities, bind_references
from app.brain.confirmation import confirmation_manager
from app.config.projects import PROJECTS
from app.state.session import SessionState, session_manager
from app.tools.registry import ToolResult
from app.tools.folders import project_folder, open_folder, project_overview
from app.voice.runtime import VoiceRuntime
from app.voice.stt import MockSTT
from app.voice.tts import MockTTS


def proposal(tool, **args):
    return json.dumps({"mode": "tool", "tool": tool, "arguments": args, "confidence": .97})


class ContextualReasoningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        projects = {}
        for key, name in (("streetlight", "Streetlight"), ("sentinel", "Sentinel AI"), ("jarvis", "JARVIS")):
            path = self.root / key
            (path / "backend").mkdir(parents=True)
            (path / "backend/requirements.txt").write_text("fastapi==0.1\n")
            projects[key] = {"name": name, "path": str(path), "aliases": [key]}
        registry = patch.dict(PROJECTS, projects, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.sid = self.id()
        self.state = session_manager.get_session(self.sid)
        self.addCleanup(session_manager.delete_session, self.sid)
        self.brain = JarvisBrain("mock")
        self.brain.fallback_provider = None
        self.brain.provider = MockProvider(json.dumps({"mode": "conversation", "response": "A concrete explanation."}))
        self.orch = JarvisOrchestrator(self.brain)
        self.execute = MagicMock(side_effect=self.result)
        for target in ("app.brain.orchestrator.execute_tool", "app.agent.executor.execute_tool"):
            mock = patch(target, self.execute)
            mock.start()
            self.addCleanup(mock.stop)

    def result(self, tool, args):
        if tool == "git_status":
            return ToolResult(True, "Branch feature/api. Modified: api.py. Untracked: test.py.", tool=tool,
                              data={"project": "streetlight", "branch": "feature/api", "modified": ["api.py"], "staged": [], "untracked": ["test.py"], "remotes": ["origin"]})
        if tool in {"project_folder", "open_project_folder"}:
            data = project_folder(args["project_name"], args.get("folder", "backend"))
            return ToolResult(data["success"], data["message"], tool=tool, data=data)
        if tool == "open_folder":
            return ToolResult(True, "Opened folder.", data={"path": args["path"]})
        return ToolResult(True, f"Completed {tool}.", tool=tool)

    def say(self, text, semantic=None):
        if semantic is not None:
            self.brain.provider.response = semantic
        return self.orch.process(text, self.sid)

    def select(self):
        self.assertTrue(self.say("Open Streetlight.").success)

    def test_cpu_knowledge_conversation(self):
        self.assertEqual(self.say("What is a CPU?").intent, "chat")
        self.execute.assert_not_called()

    def test_cpu_local_query(self):
        self.assertEqual(self.say("What CPU do I have?", proposal("system_information")).tool_used, "system_information")

    def test_git_knowledge_conversation(self):
        self.assertEqual(self.say("What is Git?").intent, "chat")
        self.execute.assert_not_called()

    def test_git_status_uses_context(self):
        self.select()
        self.assertEqual(self.say("Check git status.").tool_used, "git_status")
        self.assertEqual(self.execute.call_args.args[1]["project_name"], "streetlight")

    def test_about_git_status_is_not_execution(self):
        self.say("What does git status do?")
        self.execute.assert_not_called()

    def test_successful_open_updates_context(self):
        self.select()
        self.assertEqual(self.state.conversation_context.active_project, "Streetlight")
        self.assertEqual(self.state.current_project, "Streetlight")

    def test_its_git_reference(self):
        self.select()
        self.assertEqual(self.say("Check its git status.").tool_used, "git_status")

    def test_push_it_uses_same_project(self):
        self.select()
        response = self.say("Push it.")
        self.assertEqual(response.status, "confirmation_required")
        self.assertEqual(self.state.pending_plan.steps[0].arguments["project_name"], "streetlight")

    def test_context_survives_conversation(self):
        self.select()
        self.say("What is FastAPI?")
        self.say("Explain dependency injection.")
        self.say("Check its git status.")
        self.assertEqual(self.state.conversation_context.active_repository, "Streetlight")

    def test_path_survives_git_query(self):
        self.select()
        self.say("Show me its backend.")
        expected = self.state.conversation_context.active_path
        self.say("Check git status.")
        self.assertEqual(self.state.conversation_context.active_path, expected)

    def test_open_that_folder(self):
        self.select()
        self.say("Show me its backend.")
        self.say("Open that folder.")
        self.assertEqual(self.execute.call_args.args, ("open_folder", {"path": str(self.root / "streetlight/backend")}))

    def test_ambiguous_open_it(self):
        self.state.conversation_context.recent_entities = ["Streetlight", "Sentinel AI"]
        response = self.say("Open it.")
        self.assertFalse(response.success)
        self.assertIn("Which", response.response)
        self.execute.assert_not_called()

    def test_python_version_local_query(self):
        self.assertEqual(self.say("What Python version am I running?", proposal("python_version")).tool_used, "python_version")

    def test_python_explanation(self):
        self.say("Explain Python versions.")
        self.execute.assert_not_called()

    def test_model_summarizes_verified_result(self):
        self.brain.provider = MagicMock()
        self.brain.provider.ask.side_effect = [proposal("system_information"), "You're using Windows on a 12-core CPU."]
        self.execute.side_effect = None
        self.execute.return_value = ToolResult(True, "OS: Windows; CPU cores: 12")
        response = self.say("Tell me about this machine's hardware.")
        self.assertIn("12-core", response.response)
        self.assertIn("OS: Windows", self.brain.provider.ask.call_args.args[0])

    def test_raw_result_and_full_status(self):
        self.select()
        brief = self.say("Check git status.")
        self.assertIn("2 changed files", brief.response)
        self.assertIn("api.py", self.say("Show raw result.").response)
        self.assertIn("api.py", self.say("Show me the full git status.").response)

    def test_exact_confirmation_resumes(self):
        self.select()
        self.say("Commit those changes as fix API.")
        self.execute.reset_mock()
        self.assertTrue(self.say("yes.").success)
        self.execute.assert_called_once_with("git_commit", {"project_name": "streetlight", "message": "fix API"})

    def test_no_cancels(self):
        self.select()
        self.say("Push it.")
        token = self.state.pending_confirmation_id
        self.execute.reset_mock()
        self.assertIn("cancelled", self.say("No.").response)
        self.assertIsNone(confirmation_manager.get_confirmation(token))
        self.execute.assert_not_called()

    def test_replacement_revokes_old_token(self):
        self.select()
        self.say("Push it.")
        old = self.state.pending_confirmation_id
        response = self.say("Actually push Sentinel instead.")
        self.assertEqual(response.status, "confirmation_required")
        self.assertIsNone(confirmation_manager.get_confirmation(old))
        self.assertEqual(self.state.pending_plan.steps[0].arguments["project_name"], "sentinel")
        self.say("yes")
        self.assertEqual(self.execute.call_args.args, ("git_push", {"project_name": "sentinel"}))

    def test_readonly_followup_preserves_pending(self):
        self.select()
        self.say("Push it.")
        token = self.state.pending_confirmation_id
        response = self.say("What branch is it on first?")
        self.assertEqual(response.tool_used, "git_status")
        self.assertEqual(self.state.pending_confirmation_id, token)
        self.say("yes")
        self.assertEqual(self.execute.call_args.args[0], "git_push")

    def test_unknown_tool_never_executes(self):
        self.assertFalse(self.say("Do something special", proposal("raw_shell", command="whoami")).success)
        self.execute.assert_not_called()

    def test_malformed_model_response(self):
        for raw in ["{broken", '[]', '{"mode":"tool","tool":[],"confidence":1}', '{"mode":"tool","tool":"git_push","arguments":"bad","confidence":1}']:
            self.assertFalse(self.say("Do something special", raw).success)
        self.execute.assert_not_called()

    def test_timeout_safe_and_fastpath_survives(self):
        self.brain.provider = MagicMock()
        self.brain.provider.ask.side_effect = TimeoutError("timed out")
        self.assertFalse(self.say("Take me somewhere new").success)
        self.assertTrue(self.say("system info").success)
        self.execute.assert_called_once_with("system_information", {})

    def test_model_cannot_disable_confirmation(self):
        self.select()
        raw = json.loads(proposal("git_push", project_name="active_project"))
        raw["requires_confirmation"] = False
        self.execute.reset_mock()
        self.assertEqual(self.say("Send our work upstream", json.dumps(raw)).status, "confirmation_required")
        self.execute.assert_not_called()

    def test_model_shell_target_rejected(self):
        for value in ["Streetlight; whoami", "$(whoami)", "../Streetlight", "C:\\Windows"]:
            self.assertFalse(self.say("Take me somewhere", proposal("open_project", project_name=value)).success)
        self.execute.assert_not_called()

    def test_voice_uses_shared_reasoning(self):
        voice = VoiceRuntime(self.orch, microphone=MagicMock(), stt=MockSTT(), tts=MockTTS(), session_id=self.sid)
        self.brain.provider.response = proposal("open_project", project_name="Streetlight")
        response = voice.handle_transcript("Let's work on Streetlight.")
        self.assertEqual(response.tool_used, "open_project")
        self.assertEqual(self.state.conversation_context.active_project, "Streetlight")

    def test_voice_can_query_while_confirmation_pending(self):
        self.select()
        self.say("Push it")
        voice = VoiceRuntime(self.orch, microphone=MagicMock(), stt=MockSTT(), tts=MockTTS(), session_id=self.sid)
        self.assertEqual(voice.handle_transcript("What branch is it on first?").tool_used, "git_status")
        self.assertIsNotNone(self.state.pending_confirmation_id)

    def test_general_technical_question_has_no_tool(self):
        self.say("What does FastAPI Depends do?")
        self.execute.assert_not_called()

    def test_os_query_and_definition(self):
        self.assertEqual(self.say("What's my operating system?", proposal("system_information")).tool_used, "system_information")
        self.execute.reset_mock()
        self.say("What is an operating system?", json.dumps({"mode": "conversation", "response": "An OS manages hardware and programs."}))
        self.execute.assert_not_called()

    def test_this_project_semantic_reference(self):
        self.select()
        self.assertEqual(self.say("What's this project built with?", proposal("project_overview", project_name="this project")).tool_used, "project_overview")

    def test_repo_semantic_reference(self):
        self.select()
        self.assertEqual(self.say("What's going on with this repo?", proposal("git_status", project_name="the repo")).tool_used, "git_status")

    def test_those_changes_commit_message(self):
        self.select()
        self.say("Commit those changes as fix API.")
        self.assertEqual(self.state.pending_plan.steps[0].arguments["message"], "fix API")

    def test_failed_operation_preserves_context(self):
        self.select()
        before = self.state.conversation_context.snapshot()
        self.execute.side_effect = None
        self.execute.return_value = ToolResult(False, "Editor unavailable")
        self.assertFalse(self.say("Open Sentinel").success)
        self.assertEqual(self.state.conversation_context.snapshot(), before)

    def test_git_success_updates_state(self):
        self.select()
        self.say("Check its git status")
        state = self.state.conversation_context
        self.assertEqual(state.active_repository, "Streetlight")
        self.assertEqual(state.last_action, "git_status")
        self.assertEqual(state.last_result["branch"], "feature/api")

    def test_weather_uses_existing_external_tool(self):
        self.assertEqual(self.say("What's the weather in Chennai?").tool_used, "get_weather")
        self.assertEqual(self.brain.provider.requests, [])

    def test_filler_does_not_pass_as_answer(self):
        for answer in ["Sure, I can help with that.", "Is there anything else I can assist you with?"]:
            response = self.say("Explain recursion", json.dumps({"mode": "conversation", "response": answer}))
            self.assertFalse(response.success)
            self.assertNotEqual(response.response, answer)

    def test_semantic_project_variants(self):
        for command in ["Open Streetlight.", "Open the Streetlight project.", "Can you open Streetlight?", "Fire up Streetlight.", "Let's work on Streetlight.", "Take me to Streetlight."]:
            with self.subTest(command=command):
                self.assertEqual(self.say(command, proposal("open_project", project_name="Streetlight")).tool_used, "open_project")

    def test_semantic_repository_variants(self):
        self.select()
        for command in ["Check git status.", "What's going on with this repo?", "Are there any changes here?", "Is this repository clean?"]:
            self.assertEqual(self.say(command, proposal("git_status", project_name="active_project")).tool_used, "git_status")

    def test_knowledge_guard_rejects_action_proposal(self):
        for message in ["What is Git?", "How does git status work?", "Why does Git have branches?", "What is a repository?", "What happens if I delete this folder?"]:
            self.assertEqual(parse_decision(proposal("git_push", project_name="JARVIS"), message)["intent"], "chat")

    def test_prompt_capabilities_and_state(self):
        self.select()
        self.say("Push it")
        prompt = decision_prompt("What branch first?", self.state)
        self.assertIn("Streetlight", prompt)
        self.assertIn('"pending_action"', prompt)
        self.assertNotIn(self.state.pending_confirmation_id, prompt)
        push = next(c for c in capabilities() if c["name"] == "git_push")
        self.assertTrue(push["requires_confirmation"])
        self.assertFalse(push["read_only"])

    def test_previous_project(self):
        self.select()
        self.say("Open Sentinel")
        self.say("Open previous project")
        self.assertEqual(self.state.conversation_context.active_project, "Streetlight")

    def test_session_isolation(self):
        self.select()
        response = self.orch.process("Open it", self.sid + "other")
        self.assertFalse(response.success)
        self.assertIsNone(session_manager.get_session(self.sid + "other").conversation_context.last_project)
        session_manager.delete_session(self.sid + "other")

    def test_folder_path_escape_rejected(self):
        for folder in ("../sentinel", "C:/Windows", "backend;whoami"):
            self.assertFalse(project_folder("Streetlight", folder)["success"])

    def test_backend_metadata_is_grounded(self):
        result = project_overview("Streetlight")
        self.assertTrue(result["success"])
        self.assertIn("fastapi", result["stack"])

    def test_project_root_navigation(self):
        self.select()
        self.say("Open its backend")
        self.say("Go back to the project root")
        self.assertEqual(self.state.conversation_context.active_path, str(self.root / "streetlight"))

    def test_unknown_target_clarifies_without_execution(self):
        self.assertFalse(self.say("Take me somewhere", proposal("open_project", project_name="Totally Unknown")).success)
        self.execute.assert_not_called()

    def test_model_cannot_add_hidden_arguments(self):
        response = self.say("Send work upstream", proposal("git_push", project_name="JARVIS", confirmed=True))
        self.assertFalse(response.success)
        self.execute.assert_not_called()

    def test_explanation_receives_previous_git_result(self):
        self.select()
        self.say("Check git status")
        self.say("What does that mean?")
        prompt = self.brain.provider.requests[-1]["message"]
        self.assertIn("feature/api", prompt)
        self.assertIn("api.py", prompt)

    def test_model_external_capability_result(self):
        response = self.say("Give me today's market news", json.dumps({"mode": "external", "response": "I have no connected news source to verify today's headlines."}))
        self.assertFalse(response.success)
        self.execute.assert_not_called()

    def test_confirmed_action_context_updates(self):
        self.select()
        self.say("Push it")
        self.say("yes")
        self.assertEqual(self.state.conversation_context.last_action, "git_push")
        self.assertEqual(self.state.conversation_context.active_repository, "Streetlight")

    def test_low_risk_new_action_cancels_pending_push(self):
        self.select()
        self.say("Push it")
        token = self.state.pending_confirmation_id
        self.say("Open Sentinel")
        self.assertIsNone(confirmation_manager.get_confirmation(token))
        self.assertIsNone(self.state.pending_confirmation_id)

    def test_plain_prose_cannot_claim_action_execution(self):
        response = self.say("Take me to Streetlight", "Opened Streetlight successfully.")
        self.assertFalse(response.success)
        self.execute.assert_not_called()

    def test_unsupported_live_information_cannot_be_invented(self):
        response = self.say("Give me today's stock price", json.dumps({"mode": "conversation", "response": "It is 123 today."}))
        self.assertFalse(response.success)
        self.assertNotIn("123", response.response)

    def test_downloads_folder_semantic_route(self):
        response = self.say("Take me to my downloads", proposal("open_folder", path="Downloads"))
        self.assertEqual(response.tool_used, "open_folder")
        self.assertEqual(self.execute.call_args.args[1]["path"], str(Path.home() / "Downloads"))

    def test_named_backend_semantic_route(self):
        response = self.say("Open the Streetlight FastAPI backend", proposal("open_project_folder", project_name="Streetlight", folder="backend"))
        self.assertTrue(response.success)
        self.assertEqual(response.tool_used, "open_project_folder")

    def test_stack_switch_sequence(self):
        self.say("Open Sentinel")
        self.say("What's this project built with?", proposal("project_overview", project_name="this project"))
        self.say("Open its backend")
        self.assertEqual(self.state.conversation_context.active_path, str(self.root / "sentinel/backend"))

    def test_readonly_question_other_project_does_not_retarget_pending(self):
        self.select()
        self.say("Push it")
        self.say("Check JARVIS git status")
        self.say("yes")
        self.assertEqual(self.execute.call_args.args, ("git_push", {"project_name": "streetlight"}))

    def test_mutated_plan_cannot_use_old_approval(self):
        self.select()
        self.say("Push it")
        self.state.pending_plan.steps[0].arguments["project_name"] = "sentinel"
        self.execute.reset_mock()
        self.assertFalse(self.say("yes").success)
        self.execute.assert_not_called()

    def test_secret_redaction(self):
        from app.utils.logger import redact_secrets
        value = redact_secrets("api_key=superprivate https://user:private@host/ Bearer abcdef ghp_private")
        for secret in ("superprivate", "user:private", "abcdef", "ghp_private"):
            self.assertNotIn(secret, value)

    def test_untrusted_file_content_not_retained(self):
        self.state.conversation_context.observe("read_text_file", {"filepath": ".env"}, ToolResult(True, "private material"))
        self.assertNotIn("private material", json.dumps(self.state.conversation_context.snapshot()))

    def test_api_confirmation_is_session_bound(self):
        from fastapi.testclient import TestClient
        from app.api.server import create_app
        self.select()
        self.say("Push it")
        token = self.state.pending_confirmation_id
        client = TestClient(create_app(self.brain))
        self.addCleanup(client.close)
        self.execute.reset_mock()
        response = client.post(f"/api/actions/{token}/confirm", params={"session_id": self.sid + "other"})
        self.assertEqual(response.status_code, 404)
        self.assertIsNotNone(confirmation_manager.get_confirmation(token))
        self.execute.assert_not_called()
        response = client.post(f"/api/actions/{token}/confirm", params={"session_id": self.sid})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.execute.assert_called_once_with("git_push", {"project_name": "streetlight"})
        session_manager.delete_session(self.sid + "other")

    def test_api_cancellation_cannot_cancel_other_session(self):
        from fastapi.testclient import TestClient
        from app.api.server import create_app
        self.select()
        self.say("Push it")
        token = self.state.pending_confirmation_id
        with TestClient(create_app(self.brain)) as client:
            response = client.post(f"/api/actions/{token}/cancel", params={"session_id": self.sid + "other"})
            self.assertEqual(response.status_code, 404)
            self.assertIsNotNone(confirmation_manager.get_confirmation(token))
            response = client.post(f"/api/actions/{token}/cancel", params={"session_id": self.sid})
            self.assertTrue(response.json()["success"])
        self.assertIsNone(self.state.pending_confirmation_id)
        session_manager.delete_session(self.sid + "other")

    def test_negation_cannot_authorize_model_proposal(self):
        decision = parse_decision(proposal("git_push", project_name="JARVIS"), "Don't push the project")
        self.assertEqual(decision["intent"], "chat")


if __name__ == "__main__":
    unittest.main()
