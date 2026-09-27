import unittest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from app.brain.planner import JarvisPlanner, PlanValidator
from app.core.schemas import ActionPlan, ActionStep, RiskLevel, StepStatus


class TestPlanner(unittest.TestCase):

    def setUp(self):
        self.mock_brain = MagicMock()
        self.planner = JarvisPlanner(brain=self.mock_brain)

    def test_deterministic_multi_step_inspect(self):
        plan = self.planner.create_plan("find the JARVIS project and inspect it")
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].tool, "search_projects")
        self.assertEqual(plan.steps[1].tool, "inspect_project")
        self.assertIn("jarvis", plan.steps[0].arguments.get("query", "").lower())
        self.mock_brain.ask.assert_not_called()

    def test_deterministic_multi_step_open_vscode(self):
        plan = self.planner.create_plan("find the JARVIS project and open it in VS Code")
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].tool, "search_projects")
        self.assertEqual(plan.steps[1].tool, "open_project")
        self.mock_brain.ask.assert_not_called()

    def test_deterministic_multi_step_create_and_write(self):
        plan = self.planner.create_plan("create a folder called test_dir and write hello into test_dir/note.txt")
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].tool, "create_directory")
        self.assertEqual(plan.steps[1].tool, "write_text_file")

    def test_validator_bounds_max_steps(self):
        # Create a plan with 10 steps
        excessive_steps = [
            ActionStep(
                id=f"step_{i}",
                tool="system_information",
                arguments={},
                description=f"Step {i}",
                risk_level=RiskLevel.READ_ONLY,
            )
            for i in range(1, 11)
        ]
        plan = ActionPlan(
            id="test-max-steps",
            goal="Too many steps",
            created_at=datetime.now(timezone.utc).isoformat(),
            steps=excessive_steps,
        )
        is_valid, reason = PlanValidator.validate_plan(plan)
        self.assertFalse(is_valid)
        self.assertIn("exceeds maximum allowed", reason)

    def test_validator_rejects_nonexistent_tool(self):
        plan = ActionPlan(
            id="test-invalid-tool",
            goal="Invalid tool test",
            created_at=datetime.now(timezone.utc).isoformat(),
            steps=[
                ActionStep(
                    id="step_1",
                    tool="non_existent_fake_tool_xyz",
                    arguments={},
                    description="Run invalid tool",
                    risk_level=RiskLevel.READ_ONLY,
                )
            ],
        )
        is_valid, reason = PlanValidator.validate_plan(plan)
        self.assertFalse(is_valid)
        self.assertTrue("blocked by security policy" in reason or "unapproved" in reason.lower())

    def test_validator_rejects_blocked_tool(self):
        plan = ActionPlan(
            id="test-blocked-tool",
            goal="Blocked tool test",
            created_at=datetime.now(timezone.utc).isoformat(),
            steps=[
                ActionStep(
                    id="step_1",
                    tool="raw_shell",
                    arguments={"command": "dir"},
                    description="Run shell",
                    risk_level=RiskLevel.BLOCKED,
                )
            ],
        )
        is_valid, reason = PlanValidator.validate_plan(plan)
        self.assertFalse(is_valid)
        self.assertIn("blocked by security policy", reason)

    def test_llm_json_plan_fallback(self):
        # When deterministic patterns do not match, planner asks LLM
        self.mock_brain.ask.return_value = '''
        ```json
        {
            "id": "llm-plan-1",
            "goal": "Custom analysis",
            "steps": [
                {
                    "id": "step_1",
                    "tool": "system_information",
                    "arguments": {},
                    "description": "Get host info"
                }
            ]
        }
        ```
        '''
        plan = self.planner.create_plan("Please analyze my system architecture deeply")
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].tool, "system_information")
        self.mock_brain.ask.assert_called_once()


if __name__ == "__main__":
    unittest.main()
