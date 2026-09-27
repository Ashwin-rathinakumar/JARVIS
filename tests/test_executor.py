import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from app.agent.executor import AgentExecutor
from app.core.schemas import ActionPlan, ActionStep, RiskLevel, StepStatus, ActionPlanStatus
from app.config.settings import WORKSPACE_DIR


class TestExecutor(unittest.TestCase):

    def setUp(self):
        self.executor = AgentExecutor()

    def test_execute_read_only_multi_step_plan(self):
        plan = ActionPlan(
            id="plan-test-1",
            goal="Inspect system and current files",
            created_at=datetime.now(timezone.utc).isoformat(),
            steps=[
                ActionStep(
                    id="step_1",
                    tool="system_information",
                    arguments={},
                    description="Get system info",
                    risk_level=RiskLevel.READ_ONLY,
                ),
                ActionStep(
                    id="step_2",
                    tool="list_files",
                    arguments={"directory": "."},
                    description="List files in root",
                    risk_level=RiskLevel.READ_ONLY,
                ),
            ],
        )

        completed_plan, observations, summary = self.executor.execute_plan(plan, session_id="test-exec-session")
        self.assertEqual(completed_plan.status, ActionPlanStatus.COMPLETED)
        self.assertEqual(len(observations), 2)
        self.assertTrue(observations[0].success)
        self.assertTrue(observations[1].success)
        self.assertIn("Operating System", str(observations[0].summary))

    def test_confirmation_pause_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_target = Path(tmp_dir) / "exec_folder"

            plan = ActionPlan(
                id="plan-test-2",
                goal="Create directory safely",
                created_at=datetime.now(timezone.utc).isoformat(),
                steps=[
                    ActionStep(
                        id="step_1",
                        tool="create_folder",
                        arguments={"folder_path": str(test_target)},
                        description="Create folder",
                        risk_level=RiskLevel.MEDIUM,
                        requires_confirmation=True,
                    )
                ],
            )

            # First run without confirmation -> should pause
            paused_plan, obs1, sum1 = self.executor.execute_plan(plan, session_id="test-conf-pause")
            self.assertEqual(paused_plan.status, ActionPlanStatus.CONFIRMATION_REQUIRED)
            self.assertIsNotNone(paused_plan.confirmation_id)
            self.assertFalse(test_target.exists())

            # Resume with confirmed=True
            resumed_plan, obs2, sum2 = self.executor.resume_plan(paused_plan, confirmed=True, session_id="test-conf-pause")
            self.assertEqual(resumed_plan.status, ActionPlanStatus.COMPLETED)
            self.assertTrue(test_target.exists())
            self.assertEqual(len(obs2), 1)
            self.assertTrue(obs2[0].success)

    def test_dependency_resolution(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            plan = ActionPlan(
                id="plan-test-3",
                goal="Search and inspect",
                created_at=datetime.now(timezone.utc).isoformat(),
                steps=[
                    ActionStep(
                        id="step_1",
                        tool="search_projects",
                        arguments={"query": "JARVIS"},
                        description="Find JARVIS project",
                        risk_level=RiskLevel.READ_ONLY,
                    ),
                    ActionStep(
                        id="step_2",
                        tool="inspect_project",
                        arguments={"path_or_name": {"$from_step": "step_1", "$field": "path"}},
                        description="Inspect the discovered project",
                        risk_level=RiskLevel.READ_ONLY,
                    ),
                ],
            )

            completed_plan, observations, summary = self.executor.execute_plan(plan)
            self.assertEqual(completed_plan.status, ActionPlanStatus.COMPLETED)
            self.assertEqual(len(observations), 2)
            self.assertTrue(observations[0].success)
            self.assertTrue(observations[1].success)
            self.assertIn("Project Inspection: JARVIS", str(observations[1].summary))

    def test_dry_run_mode(self):
        plan = ActionPlan(
            id="plan-test-4",
            goal="Dry run creation",
            created_at=datetime.now(timezone.utc).isoformat(),
            steps=[
                ActionStep(
                    id="step_1",
                    tool="create_folder",
                    arguments={"folder_path": "dry_run_test_dir"},
                    description="Create folder dry run",
                    risk_level=RiskLevel.MEDIUM,
                )
            ],
        )

        completed_plan, observations, summary = self.executor.execute_plan(plan, dry_run=True)
        self.assertEqual(completed_plan.status, ActionPlanStatus.COMPLETED)
        self.assertTrue(observations[0].success)
        self.assertIn("DRY-RUN", str(observations[0].summary))


if __name__ == "__main__":
    unittest.main()
