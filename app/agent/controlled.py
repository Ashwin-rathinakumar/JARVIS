"""Controlled plan-act-observe loop for JARVIS v0.7."""
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.agent.audit import record_audit
from app.brain.confirmation import confirmation_manager
from app.brain.permissions import PermissionEngine, get_risk_level
from app.config.projects import resolve_project_key
from app.config.settings import JARVIS_AGENT_MAX_RETRIES, JARVIS_AGENT_MAX_RUNTIME_SECONDS, JARVIS_AGENT_MAX_STEPS
from app.core.schemas import PermissionDecision
from app.tools.registry import execute_tool
from app.utils.logger import logger


class AgentRunStatus(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    REPLANNING = "REPLANNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STEP_LIMIT_REACHED = "STEP_LIMIT_REACHED"


@dataclass
class AgentStep:
    id: str
    action: str
    arguments: Dict[str, Any]
    reason: str = ""
    status: str = "PENDING"
    permission_level: Optional[str] = None
    result: Optional[str] = None
    retries: int = 0


@dataclass
class AgentObservation:
    step_id: str
    success: bool
    summary: str
    data: Any = None
    error: Optional[str] = None


@dataclass
class AgentRun:
    run_id: str
    session_id: str
    objective: str
    status: AgentRunStatus = AgentRunStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    current_step: int = 0
    steps: List[AgentStep] = field(default_factory=list)
    observations: List[AgentObservation] = field(default_factory=list)
    max_steps: int = JARVIS_AGENT_MAX_STEPS
    confirmation_id: Optional[str] = None
    final_summary: Optional[str] = None
    started_monotonic: float = field(default_factory=time.monotonic, repr=False)


@dataclass(frozen=True)
class AgentCapability:
    name: str
    description: str
    arguments: Dict[str, str]


AGENT_CAPABILITIES: Dict[str, AgentCapability] = {
    "inspect_project": AgentCapability("inspect_project", "Inspect registered project metadata", {"path_or_name": "registered project"}),
    "project_status": AgentCapability("project_status", "Inspect registered project status", {"project_name": "registered project"}),
    "list_project_files": AgentCapability("list_project_files", "List files under a registered project", {"project": "registered project", "relative_path": "safe relative path, optional"}),
    "read_project_file": AgentCapability("read_project_file", "Read a bounded project file", {"project": "registered project", "relative_path": "safe relative path"}),
    "search_project_text": AgentCapability("search_project_text", "Search bounded text in a project", {"project": "registered project", "query": "text up to 200 characters"}),
    "run_project_tests": AgentCapability("run_project_tests", "Run the project's registered test command", {"project": "registered project"}),
    "system_information": AgentCapability("system_information", "Read system information", {}),
    "get_weather": AgentCapability("get_weather", "Read live weather", {"location": "location", "when": "current, today, or tomorrow"}),
}


def capability_manifest() -> List[Dict[str, Any]]:
    return [{"name": item.name, "description": item.description, "arguments": item.arguments,
             "risk_level": get_risk_level(item.name).value} for item in AGENT_CAPABILITIES.values()]


def _validate_path(value: str) -> bool:
    return bool(value) and not value.startswith(("/", "\\")) and ":" not in value and ".." not in value.replace("\\", "/").split("/")


def validate_agent_step(step: AgentStep) -> Optional[str]:
    capability = AGENT_CAPABILITIES.get(step.action)
    if not capability:
        return f"Unknown or disallowed agent action '{step.action}'."
    if set(step.arguments) - set(capability.arguments):
        return "Unsupported arguments were supplied."
    for required in capability.arguments:
        if "optional" not in capability.arguments[required] and required not in step.arguments:
            return f"Missing required argument '{required}'."
    project = step.arguments.get("project") or step.arguments.get("project_name") or step.arguments.get("path_or_name")
    if project and not resolve_project_key(str(project)):
        return f"Unknown registered project '{project}'."
    relative = step.arguments.get("relative_path")
    if relative is not None and not _validate_path(str(relative)):
        return "Unsafe relative project path."
    if any(key in step.arguments for key in {"command", "shell", "powershell", "url"}):
        return "Arbitrary commands and URLs are not allowed."
    return None


def parse_agent_proposal(raw: str) -> tuple[List[AgentStep], Optional[str], Optional[str]]:
    try:
        data = json.loads(raw)
        if data.get("type") == "complete":
            return [], str(data.get("summary", "Task completed.")), None
        if data.get("type") != "plan" or not isinstance(data.get("steps"), list):
            return [], None, "Malformed agent plan."
        steps = []
        for index, item in enumerate(data["steps"]):
            if not isinstance(item, dict) or not isinstance(item.get("action"), str) or not isinstance(item.get("arguments", {}), dict):
                return [], None, "Malformed agent step."
            step = AgentStep(str(item.get("id", f"step_{index + 1}")), item["action"], item.get("arguments", {}), str(item.get("reason", "")))
            error = validate_agent_step(step)
            if error:
                return [], None, error
            steps.append(step)
        return steps, None, None
    except (json.JSONDecodeError, TypeError, AttributeError):
        return [], None, "Malformed agent plan."


class ControlledAgent:
    """Runs one bounded, validated agent task per session."""
    def __init__(self, proposer: Callable[[str], str], max_steps: int = JARVIS_AGENT_MAX_STEPS,
                 max_retries: int = JARVIS_AGENT_MAX_RETRIES, max_runtime: int = JARVIS_AGENT_MAX_RUNTIME_SECONDS):
        self.proposer = proposer
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.max_runtime = max_runtime
        self.runs: Dict[str, AgentRun] = {}
        self.events: List[Dict[str, Any]] = []

    def _event(self, run: AgentRun, event: str, **details) -> None:
        item = {"run_id": run.run_id, "session_id": run.session_id, "event": event, **details}
        self.events.append(item)
        logger.info("Agent event=%s run=%s status=%s", event, run.run_id[:8], run.status.value)

    def start(self, objective: str, session_id: str) -> AgentRun:
        active = self.runs.get(session_id)
        if active and active.status not in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED, AgentRunStatus.STEP_LIMIT_REACHED}:
            return active
        run = AgentRun(str(uuid.uuid4()), session_id, objective, max_steps=self.max_steps)
        self.runs[session_id] = run
        self._event(run, "created")
        return self._plan_and_continue(run, initial=True)

    def _prompt(self, run: AgentRun) -> str:
        observations = [{"step_id": o.step_id, "success": o.success, "summary": o.summary} for o in run.observations]
        return json.dumps({"objective": run.objective, "capabilities": capability_manifest(), "observations": observations,
                           "instruction": "Return JSON type plan with safe next steps, or type complete with a grounded summary."})

    def _plan_and_continue(self, run: AgentRun, initial: bool = False) -> AgentRun:
        run.status = AgentRunStatus.PLANNING if initial else AgentRunStatus.REPLANNING
        try:
            raw = self.proposer(self._prompt(run))
        except Exception as error:
            run.status = AgentRunStatus.FAILED
            run.final_summary = f"Reasoning provider failed: {error}"
            self._event(run, "provider_failed")
            return run
        steps, summary, error = parse_agent_proposal(raw)
        if error or len(steps) > run.max_steps:
            run.status = AgentRunStatus.FAILED
            run.final_summary = error or "Plan exceeds the step limit."
            self._event(run, "plan_rejected", reason=run.final_summary)
            return run
        if summary is not None:
            run.status = AgentRunStatus.COMPLETED
            observed = [f"- {item.step_id}: {'succeeded' if item.success else 'failed'} — {item.summary[:500]}" for item in run.observations]
            run.final_summary = "Observed:\n" + ("\n".join(observed) or "- No actions were executed.") + f"\n\nProposed conclusion:\n{summary}"
            self._event(run, "completed")
            return run
        run.steps.extend(steps)
        while run.current_step < len(run.steps):
            if run.current_step >= run.max_steps:
                run.status = AgentRunStatus.STEP_LIMIT_REACHED
                run.final_summary = "Step limit reached with partial results."
                return run
            if time.monotonic() - run.started_monotonic > self.max_runtime:
                run.status = AgentRunStatus.CANCELLED
                run.final_summary = "Agent time limit reached with partial results."
                return run
            step = run.steps[run.current_step]
            error = validate_agent_step(step)
            if error:
                run.status = AgentRunStatus.FAILED
                run.final_summary = error
                return run
            risk = get_risk_level(step.action)
            step.permission_level = risk.value
            decision, reason = PermissionEngine.evaluate(step.action, step.arguments)
            if decision == PermissionDecision.DENY:
                run.status = AgentRunStatus.FAILED
                run.final_summary = f"Permission denied: {reason}"
                return run
            if decision == PermissionDecision.CONFIRM:
                run.confirmation_id = confirmation_manager.create_confirmation(run.run_id, step.id, step.action, step.arguments, step.reason or step.action)
                run.status = AgentRunStatus.WAITING_FOR_CONFIRMATION
                self._event(run, "confirmation_required", step=step.id)
                return run
            self._execute(run, step, decision)
            if not run.observations[-1].success and step.retries < self.max_retries:
                step.retries += 1
                self._execute(run, step, decision)
            run.current_step += 1
        return self._plan_and_continue(run)

    def _execute(self, run: AgentRun, step: AgentStep, decision: PermissionDecision) -> None:
        run.status = AgentRunStatus.EXECUTING
        step.status = "RUNNING"
        result = execute_tool(step.action, step.arguments)
        summary = result.message[:6000]
        observation = AgentObservation(step.id, result.success, summary, result.data, result.error)
        run.observations.append(observation)
        step.status = "COMPLETED" if result.success else "FAILED"
        step.result = summary
        run.status = AgentRunStatus.OBSERVING
        record_audit(step.action, get_risk_level(step.action).value, decision.value, step.arguments, result.success,
                     session_id=run.session_id, plan_id=run.run_id, step_id=step.id,
                     error_code=result.error_code, message=summary, source="agent")
        self._event(run, "observed", step=step.id, success=result.success)

    def confirm(self, session_id: str, approved: bool) -> Optional[AgentRun]:
        run = self.runs.get(session_id)
        if not run or run.status != AgentRunStatus.WAITING_FOR_CONFIRMATION or not run.confirmation_id:
            return run
        if not approved:
            confirmation_manager.cancel_confirmation(run.confirmation_id)
            run.status = AgentRunStatus.CANCELLED
            run.final_summary = "Agent action was not approved."
            return run
        details = confirmation_manager.consume_confirmation(run.confirmation_id)
        if not details:
            run.status = AgentRunStatus.FAILED
            run.final_summary = "Confirmation expired."
            return run
        step = run.steps[run.current_step]
        self._execute(run, step, PermissionDecision.ALLOW)
        run.current_step += 1
        run.confirmation_id = None
        return self._plan_and_continue(run)

    def cancel(self, session_id: str) -> Optional[AgentRun]:
        run = self.runs.get(session_id)
        if run and run.status not in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
            if run.confirmation_id:
                confirmation_manager.cancel_confirmation(run.confirmation_id)
            run.status = AgentRunStatus.CANCELLED
            run.final_summary = "Agent run cancelled."
            self._event(run, "cancelled")
        return run

    def status(self, session_id: str) -> Optional[AgentRun]:
        return self.runs.get(session_id)
