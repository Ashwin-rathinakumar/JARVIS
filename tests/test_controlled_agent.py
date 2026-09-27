import json
import unittest
from unittest.mock import MagicMock, patch

from app.agent.controlled import (
    AgentRunStatus, AgentStep, ControlledAgent, capability_manifest,
    parse_agent_proposal, validate_agent_step,
)
from app.brain.orchestrator import JarvisOrchestrator
from app.tools.registry import ToolResult


class ScriptedProposer:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def plan(*steps):
    return json.dumps({"type": "plan", "steps": list(steps)})


def complete(summary="Grounded summary"):
    return json.dumps({"type": "complete", "summary": summary})


class TestControlledAgent(unittest.TestCase):
    def test_agent_creation_and_safe_replanning_loop(self):
        proposer = ScriptedProposer(
            plan({"action": "inspect_project", "arguments": {"path_or_name": "sentinel"}}),
            plan({"action": "read_project_file", "arguments": {"project": "sentinel", "relative_path": "README.md"}}),
            complete("Observed project metadata and README."),
        )
        agent = ControlledAgent(proposer)
        with patch("app.agent.controlled.execute_tool", side_effect=[
            ToolResult(True, "metadata", tool="inspect_project"),
            ToolResult(True, "readme", tool="read_project_file"),
        ]) as execute, patch("app.agent.controlled.record_audit") as audit:
            run = agent.start("Investigate Sentinel", "session-safe")
        self.assertEqual(run.status, AgentRunStatus.COMPLETED)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(len(run.observations), 2)
        self.assertEqual(audit.call_count, 2)
        self.assertIn("metadata", proposer.prompts[1])
        self.assertIn("Observed:", run.final_summary)
        self.assertIn("Proposed conclusion:", run.final_summary)

    def test_normal_conversation_does_not_create_agent(self):
        brain = MagicMock()
        brain.ask.return_value = "Recursion answer"
        orchestrator = JarvisOrchestrator(brain=brain)
        response = orchestrator.process("What is recursion?", session_id="normal-chat")
        self.assertEqual(response.intent, "chat")
        self.assertIsNone(orchestrator.agent.status("normal-chat"))

    def test_unknown_and_shell_actions_execute_nothing(self):
        hostile = [
            {"action": "destroy_computer", "arguments": {}},
            {"action": "powershell", "arguments": {"command": "rm -rf /"}},
            {"action": "subprocess", "arguments": {"command": "taskkill"}},
        ]
        for index, step in enumerate(hostile):
            with self.subTest(step=step), patch("app.agent.controlled.execute_tool") as execute:
                run = ControlledAgent(ScriptedProposer(plan(step))).start("hostile", f"hostile-{index}")
                self.assertEqual(run.status, AgentRunStatus.FAILED)
                execute.assert_not_called()

    def test_unsafe_path_and_unknown_project_rejected(self):
        for step in [
            AgentStep("1", "read_project_file", {"project": "sentinel", "relative_path": "../../Windows/System32"}),
            AgentStep("1", "run_project_tests", {"project": "unknown"}),
        ]:
            self.assertIsNotNone(validate_agent_step(step))

    def test_step_limit(self):
        proposer = ScriptedProposer(plan(
            {"action": "system_information", "arguments": {}},
            {"action": "system_information", "arguments": {}},
        ))
        run = ControlledAgent(proposer, max_steps=1).start("too many", "step-limit")
        self.assertEqual(run.status, AgentRunStatus.FAILED)

    def test_retry_limit(self):
        proposer = ScriptedProposer(plan({"action": "system_information", "arguments": {}}), complete())
        with patch("app.agent.controlled.execute_tool", return_value=ToolResult(False, "failed", error="failed")) as execute, \
             patch("app.agent.controlled.record_audit"):
            run = ControlledAgent(proposer, max_retries=1).start("retry", "retry")
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(run.status, AgentRunStatus.COMPLETED)

    def test_confirmation_pause_approval_and_denial(self):
        step = {"action": "run_project_tests", "arguments": {"project": "sentinel"}}
        with patch("app.agent.controlled.execute_tool", return_value=ToolResult(True, "tests passed")) as execute, \
             patch("app.agent.controlled.record_audit"):
            agent = ControlledAgent(ScriptedProposer(plan(step), complete()))
            run = agent.start("test sentinel", "confirm-yes")
            self.assertEqual(run.status, AgentRunStatus.WAITING_FOR_CONFIRMATION)
            execute.assert_not_called()
            run = agent.confirm("confirm-yes", True)
            self.assertEqual(run.status, AgentRunStatus.COMPLETED)
            execute.assert_called_once()

            denied = ControlledAgent(ScriptedProposer(plan(step)))
            run = denied.start("test sentinel", "confirm-no")
            denied.confirm("confirm-no", False)
            self.assertEqual(run.status, AgentRunStatus.CANCELLED)
            self.assertEqual(execute.call_count, 1)

    def test_cancellation_timeout_and_provider_failure(self):
        waiting = ControlledAgent(ScriptedProposer(plan({"action": "run_project_tests", "arguments": {"project": "sentinel"}})))
        run = waiting.start("wait", "cancel")
        self.assertEqual(waiting.cancel("cancel").status, AgentRunStatus.CANCELLED)

        timed = ControlledAgent(ScriptedProposer(plan({"action": "system_information", "arguments": {}})), max_runtime=-1)
        self.assertEqual(timed.start("timeout", "timeout").status, AgentRunStatus.CANCELLED)

        failed = ControlledAgent(ScriptedProposer(RuntimeError("model offline")))
        run = failed.start("failure", "failure")
        self.assertEqual(run.status, AgentRunStatus.FAILED)
        self.assertIn("model offline", run.final_summary)

    def test_malformed_plan_executes_nothing(self):
        with patch("app.agent.controlled.execute_tool") as execute:
            run = ControlledAgent(ScriptedProposer("not json")).start("bad", "bad")
        self.assertEqual(run.status, AgentRunStatus.FAILED)
        execute.assert_not_called()

    def test_capabilities_are_generated_from_registry(self):
        names = {item["name"] for item in capability_manifest()}
        self.assertIn("run_project_tests", names)
        self.assertNotIn("raw_shell", names)

    def test_persistent_runtime_returns_to_idle_after_agent_failure(self):
        brain = MagicMock()
        brain.generate.return_value = "malformed"
        orchestrator = JarvisOrchestrator(brain=brain)
        from app.runtime.core import JarvisRuntime
        from app.runtime.state import RuntimeState
        from app.voice.stt import MockSTT
        from app.voice.tts import MockTTS
        runtime = JarvisRuntime(orchestrator=orchestrator, microphone=MagicMock(), stt=MockSTT(),
                                tts=MockTTS(), session_id="agent-runtime-failure")
        response = runtime.process_transcript("Investigate the Sentinel backend")
        self.assertFalse(response.success)
        self.assertEqual(runtime.state, RuntimeState.IDLE)


if __name__ == "__main__":
    unittest.main()
