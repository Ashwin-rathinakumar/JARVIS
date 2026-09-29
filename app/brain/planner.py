import re
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from app.core.schemas import ActionPlan, ActionStep, ActionPlanStatus, RiskLevel
from app.brain.permissions import get_risk_level, PermissionEngine
from app.tools.registry import TOOL_REGISTRY
from app.config.settings import MAX_PLAN_STEPS, OLLAMA_MODEL, OLLAMA_URL, OLLAMA_TIMEOUT
from app.utils.logger import logger
import requests


PLANNER_SYSTEM_PROMPT = """You are the JARVIS Task Planner.
Your job is to break down a complex multi-step user goal into an ActionPlan containing strictly validated steps.

AVAILABLE TOOLS:
- search_projects (arguments: {"query": "project name"}) -> returns matching project paths
- inspect_project (arguments: {"path_or_name": "path or key"}) -> returns project metadata
- open_project (arguments: {"project_name_or_path": "path or key", "application": "vscode"}) -> opens project in VS Code
- search_files (arguments: {"query": "filename", "directory": "."}) -> searches for files
- find_file (arguments: {"pattern": "*.py", "directory": "."}) -> glob search
- list_files (arguments: {"directory": "."}) -> lists directory contents
- read_text_file (arguments: {"filepath": "path"}) -> reads text file
- create_directory (arguments: {"folder_path": "path"}) -> creates folder (requires confirmation)
- write_text_file (arguments: {"filepath": "path", "content": "text", "overwrite": false}) -> writes text file (requires confirmation)
- open_application (arguments: {"app": "notepad|calc|explorer|paint|vscode|browser"})
- system_information (arguments: {})
- remember (arguments: {"content": "..."})
- ask_documents (arguments: {"query": "..."})
- get_recent_actions (arguments: {"limit": 10})

DEPENDENCY REFERENCE:
If step 2 needs output from step 1, use:
{"argument_name": {"$from_step": "step_1", "$field": "path"}}

OUTPUT FORMAT (ONLY VALID JSON, NO OTHER TEXT):
{
    "goal": "description of user goal",
    "steps": [
        {
            "id": "step_1",
            "tool": "search_projects",
            "arguments": {"query": "Sentinel"},
            "description": "Search for Sentinel project"
        },
        {
            "id": "step_2",
            "tool": "open_project",
            "arguments": {
                "project_name_or_path": {"$from_step": "step_1", "$field": "path"},
                "application": "vscode"
            },
            "description": "Open discovered project in VS Code"
        }
    ]
}
"""


class PlanValidator:
    """Validates ActionPlan structures for security, tool validity, and bounds."""

    @staticmethod
    def validate(plan: ActionPlan) -> Tuple[bool, Optional[str]]:
        if not plan.steps:
            return False, "Plan contains no steps."

        if len(plan.steps) > MAX_PLAN_STEPS:
            return False, f"Plan exceeds maximum allowed steps ({len(plan.steps)} > {MAX_PLAN_STEPS})."

        step_ids = set()
        for idx, step in enumerate(plan.steps):
            if not step.id:
                step.id = f"step_{idx+1}"

            if step.id in step_ids:
                return False, f"Duplicate step ID '{step.id}' in plan."
            step_ids.add(step.id)

            # 1. Risk level and security check
            actual_risk = get_risk_level(step.tool)
            if actual_risk == RiskLevel.BLOCKED:
                return False, f"Tool '{step.tool}' is blocked by security policy in step '{step.id}'."

            # 2. Tool existence
            tool_def = TOOL_REGISTRY.get(step.tool)
            if not tool_def:
                return False, f"Unknown or unapproved tool '{step.tool}' in step '{step.id}'."

            step.risk_level = actual_risk
            step.requires_confirmation = (actual_risk in {RiskLevel.MEDIUM, RiskLevel.HIGH})

            # 3. Argument and Dependency Validation
            if not isinstance(step.arguments, dict):
                return False, f"Arguments for step '{step.id}' must be a dictionary."

            for arg_key, arg_val in step.arguments.items():
                if isinstance(arg_val, dict) and "$from_step" in arg_val:
                    ref_step_id = arg_val["$from_step"]
                    if ref_step_id not in step_ids or ref_step_id == step.id:
                        return False, f"Invalid step dependency reference '{ref_step_id}' in step '{step.id}'."

        return True, None

    @classmethod
    def validate_plan(cls, plan: ActionPlan) -> Tuple[bool, Optional[str]]:
        """Alias for validate."""
        return cls.validate(plan)


class JarvisPlanner:
    """Converts multi-step user goals into validated ActionPlans."""

    def __init__(self, brain: Optional[Any] = None):
        self.brain = brain

    def plan_deterministic(self, goal: str, session_id: Optional[str] = None) -> Optional[ActionPlan]:
        """
        Fast pattern-based plan generation for common compound patterns.
        """
        lower = goal.lower().strip()

        # Git compound operations are bounded registered workflows, not free-form
        # plans. Let the orchestrator bind project context and require approval.
        from app.projects.git_commands import parse_git_command
        if parse_git_command(goal):
            return None

        # Pattern: "find (my) <project> (project) and open (it) in (vs )?code"
        m = re.match(
            r"^(?:find|locate|search\s+for)\s+(?:my\s+)?(?:the\s+)?(.+?)(?:\s+project)?\s+and\s+open\s+(?:it\s+)?(?:in\s+)?(?:vs\s+)?code(?:\.exe)?$",
            lower
        )
        if m:
            proj_query = m.group(1).strip()
            plan_id = str(uuid.uuid4())
            steps = [
                ActionStep(
                    id="step_1",
                    tool="search_projects",
                    arguments={"query": proj_query},
                    description=f"Search for {proj_query} project directory",
                    risk_level=RiskLevel.READ_ONLY,
                ),
                ActionStep(
                    id="step_2",
                    tool="open_project",
                    arguments={
                        "project_name_or_path": {"$from_step": "step_1", "$field": "path"},
                        "application": "vscode"
                    },
                    description=f"Open {proj_query} in VS Code",
                    risk_level=RiskLevel.LOW,
                )
            ]
            plan = ActionPlan(
                id=plan_id,
                goal=goal,
                steps=steps,
                status=ActionPlanStatus.PENDING,
                created_at=datetime.now(timezone.utc).isoformat(),
                session_id=session_id,
            )
            valid, err = PlanValidator.validate(plan)
            if valid:
                return plan

        # Pattern: "find (the) <project> (project) and inspect (it)"
        m = re.match(
            r"^(?:find|locate|search\s+for)\s+(?:the\s+)?(?:my\s+)?(.+?)(?:\s+project)?\s+and\s+inspect\s+(?:it)?$",
            lower
        )
        if m:
            proj_query = m.group(1).strip()
            plan_id = str(uuid.uuid4())
            steps = [
                ActionStep(
                    id="step_1",
                    tool="search_projects",
                    arguments={"query": proj_query},
                    description=f"Search for {proj_query} project",
                    risk_level=RiskLevel.READ_ONLY,
                ),
                ActionStep(
                    id="step_2",
                    tool="inspect_project",
                    arguments={
                        "path_or_name": {"$from_step": "step_1", "$field": "path"}
                    },
                    description=f"Inspect project structure and metadata",
                    risk_level=RiskLevel.READ_ONLY,
                )
            ]
            plan = ActionPlan(
                id=plan_id,
                goal=goal,
                steps=steps,
                status=ActionPlanStatus.PENDING,
                created_at=datetime.now(timezone.utc).isoformat(),
                session_id=session_id,
            )
            valid, err = PlanValidator.validate(plan)
            if valid:
                return plan

        # Pattern: "create (a )folder (called )<name> (and write <content> into <filepath>)?"
        m_compound = re.match(
            r"^create\s+(?:a\s+)?(?:folder|directory)\s+(?:called\s+|named\s+)?([^\s]+)\s+and\s+write\s+(.+?)\s+(?:in|into|to)\s+(.+)$",
            lower
        )
        if m_compound:
            folder_name = m_compound.group(1).strip()
            content = m_compound.group(2).strip()
            filepath = m_compound.group(3).strip()
            plan_id = str(uuid.uuid4())
            steps = [
                ActionStep(
                    id="step_1",
                    tool="create_directory",
                    arguments={"folder_path": folder_name},
                    description=f"Create directory: {folder_name}",
                    risk_level=RiskLevel.MEDIUM,
                    requires_confirmation=True,
                ),
                ActionStep(
                    id="step_2",
                    tool="write_text_file",
                    arguments={"filepath": filepath, "content": content},
                    description=f"Write text to file: {filepath}",
                    risk_level=RiskLevel.MEDIUM,
                    requires_confirmation=True,
                )
            ]
            plan = ActionPlan(
                id=plan_id,
                goal=goal,
                steps=steps,
                status=ActionPlanStatus.PENDING,
                created_at=datetime.now(timezone.utc).isoformat(),
                session_id=session_id,
            )
            valid, err = PlanValidator.validate(plan)
            if valid:
                return plan

        # Pattern: "create (a )folder (called )<name>"
        m = re.match(
            r"^create\s+(?:a\s+)?(?:folder|directory)\s+(?:called\s+|named\s+)?(.+)$",
            lower
        )
        if m:
            folder_name = m.group(1).strip()
            plan_id = str(uuid.uuid4())
            steps = [
                ActionStep(
                    id="step_1",
                    tool="create_directory",
                    arguments={"folder_path": folder_name},
                    description=f"Create directory: {folder_name}",
                    risk_level=RiskLevel.MEDIUM,
                    requires_confirmation=True,
                )
            ]
            plan = ActionPlan(
                id=plan_id,
                goal=goal,
                steps=steps,
                status=ActionPlanStatus.PENDING,
                created_at=datetime.now(timezone.utc).isoformat(),
                session_id=session_id,
            )
            valid, err = PlanValidator.validate(plan)
            if valid:
                return plan

        # Pattern: "write <content> (in|into|to) <filepath>"
        m = re.match(
            r"^write\s+(.+?)\s+(?:in|into|to)\s+(.+)$",
            goal,
            re.IGNORECASE
        )
        if m:
            content = m.group(1).strip()
            filepath = m.group(2).strip()
            plan_id = str(uuid.uuid4())
            steps = [
                ActionStep(
                    id="step_1",
                    tool="write_text_file",
                    arguments={"filepath": filepath, "content": content},
                    description=f"Write text to file: {filepath}",
                    risk_level=RiskLevel.MEDIUM,
                    requires_confirmation=True,
                )
            ]
            plan = ActionPlan(
                id=plan_id,
                goal=goal,
                steps=steps,
                status=ActionPlanStatus.PENDING,
                created_at=datetime.now(timezone.utc).isoformat(),
                session_id=session_id,
            )
            valid, err = PlanValidator.validate(plan)
            if valid:
                return plan

        return None

    def plan(self, goal: str, session_id: Optional[str] = None) -> Optional[ActionPlan]:
        """
        Generate a validated ActionPlan for a user goal.
        Tries deterministic patterns first, then LLM planner fallback.
        """
        # 1. Deterministic planner
        det_plan = self.plan_deterministic(goal, session_id=session_id)
        if det_plan:
            logger.info(f"Generated deterministic ActionPlan [{det_plan.id[:8]}] with {len(det_plan.steps)} steps")
            return det_plan

        # 2. LLM Planner
        try:
            if self.brain and hasattr(self.brain, "ask"):
                raw_content = self.brain.ask(
                    f"{PLANNER_SYSTEM_PROMPT}\n\nCreate an ActionPlan for this goal: {goal}"
                )
            else:
                payload = {
                    "model": OLLAMA_MODEL,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Create an ActionPlan for this goal: {goal}"}
                    ]
                }
                response = requests.post(
                    f"{OLLAMA_URL}/api/chat",
                    json=payload,
                    timeout=min(OLLAMA_TIMEOUT, 10)
                )
                response.raise_for_status()
                data = response.json()
                raw_content = data["message"]["content"]

            # Clean JSON if wrapped in markdown code blocks
            clean_json = raw_content.strip()
            if "```" in clean_json:
                m_code = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_json)
                if m_code:
                    clean_json = m_code.group(1).strip()

            plan_dict = json.loads(clean_json)

            if "id" not in plan_dict:
                plan_dict["id"] = str(uuid.uuid4())
            if "status" not in plan_dict:
                plan_dict["status"] = ActionPlanStatus.PENDING
            if "created_at" not in plan_dict:
                plan_dict["created_at"] = datetime.now(timezone.utc).isoformat()
            plan_dict["session_id"] = session_id

            plan = ActionPlan(**plan_dict)
            valid, error_msg = PlanValidator.validate(plan)
            if valid:
                logger.info(f"Generated and validated LLM ActionPlan [{plan.id[:8]}] with {len(plan.steps)} steps")
                return plan
            else:
                logger.warning(f"Generated ActionPlan failed validation: {error_msg}")
                return None

        except Exception as e:
            logger.error(f"Planner error ({e})")
            return None

    def create_plan(self, goal: str, session_id: Optional[str] = None) -> Optional[ActionPlan]:
        """Alias for plan."""
        return self.plan(goal, session_id=session_id)
