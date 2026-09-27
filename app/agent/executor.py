import copy
from typing import Dict, Any, List, Optional, Tuple

from app.core.schemas import (
    ActionPlan,
    ActionStep,
    ActionPlanStatus,
    StepStatus,
    Observation,
    PermissionDecision,
    RiskLevel,
)
from app.brain.permissions import PermissionEngine, get_risk_level
from app.brain.confirmation import confirmation_manager
from app.tools.registry import execute_tool, ToolResult
from app.agent.audit import record_audit
from app.config.settings import MAX_AGENT_STEPS, JARVIS_DRY_RUN
from app.utils.logger import logger


def _resolve_step_arguments(
    arguments: Dict[str, Any],
    step_outputs: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any], Optional[str]]:
    """
    Resolve dependency references in step arguments safely without eval.
    Example: {"project_name_or_path": {"$from_step": "step_1", "$field": "path"}}
    """
    resolved = copy.deepcopy(arguments)

    for k, v in arguments.items():
        if isinstance(v, dict) and "$from_step" in v:
            ref_step = v["$from_step"]
            ref_field = v.get("$field")

            if ref_step not in step_outputs:
                return False, {}, f"Dependency '{ref_step}' has not produced any output."

            prev_data = step_outputs[ref_step]
            extracted_val = None

            if ref_field:
                if isinstance(prev_data, dict) and ref_field in prev_data:
                    extracted_val = prev_data[ref_field]
                elif hasattr(prev_data, ref_field):
                    extracted_val = getattr(prev_data, ref_field)
                else:
                    return False, {}, f"Field '{ref_field}' not found in output of '{ref_step}'."
            else:
                extracted_val = prev_data

            if extracted_val is None:
                return False, {}, f"No value available from '{ref_step}' for argument '{k}'."

            resolved[k] = extracted_val

    return True, resolved, None


class AgentExecutor:
    """Executes validated ActionPlans step-by-step with permission checks and observations."""

    def __init__(self, dry_run: Optional[bool] = None):
        self.dry_run = dry_run if dry_run is not None else JARVIS_DRY_RUN

    def execute_plan(
        self,
        plan: ActionPlan,
        session_id: Optional[str] = None,
        confirmed_step_id: Optional[str] = None,
        dry_run: Optional[bool] = None,
        source: str = "cli",
    ) -> Tuple[ActionPlan, List[Observation], str]:
        """
        Execute an ActionPlan until completion, failure, or confirmation pause.
        """
        is_dry_run = dry_run if dry_run is not None else self.dry_run
        observations: List[Observation] = []
        step_outputs: Dict[str, Any] = {}

        # Restore outputs from previously completed steps
        for step in plan.steps:
            if step.status == StepStatus.COMPLETED and step.result is not None:
                step_outputs[step.id] = step.result

        plan.status = ActionPlanStatus.RUNNING
        executed_count = 0

        for idx, step in enumerate(plan.steps):
            if step.status == StepStatus.COMPLETED:
                continue

            if executed_count >= MAX_AGENT_STEPS:
                plan.status = ActionPlanStatus.FAILED
                summary = f"Plan halted: exceeded maximum agent steps ({MAX_AGENT_STEPS})."
                return plan, observations, summary

            plan.current_step_index = idx
            executed_count += 1

            # 1. Resolve argument dependencies
            ok, resolved_args, dep_err = _resolve_step_arguments(step.arguments, step_outputs)
            if not ok:
                step.status = StepStatus.FAILED
                step.error = dep_err
                plan.status = ActionPlanStatus.FAILED
                obs = Observation(
                    step_id=step.id,
                    tool=step.tool,
                    success=False,
                    summary=dep_err or "Dependency resolution error",
                    error=dep_err,
                )
                observations.append(obs)
                summary = f"I couldn't proceed with {step.description or step.tool}: {dep_err}"
                return plan, observations, summary

            # 2. Permission Evaluation
            is_confirmed = (confirmed_step_id == step.id)
            decision, reason = PermissionEngine.evaluate(step.tool, resolved_args, confirmed=is_confirmed)

            if decision == PermissionDecision.DENY:
                step.status = StepStatus.FAILED
                step.error = reason or "Access denied by security policy."
                plan.status = ActionPlanStatus.FAILED
                record_audit(
                    tool=step.tool,
                    risk_level=step.risk_level.value,
                    permission_decision=decision.value,
                    arguments=resolved_args,
                    success=False,
                    session_id=session_id or plan.session_id,
                    plan_id=plan.id,
                    step_id=step.id,
                    error_code="PERMISSION_DENIED",
                    message=step.error,
                    source=source,
                )
                obs = Observation(
                    step_id=step.id,
                    tool=step.tool,
                    success=False,
                    summary=step.error,
                    error=step.error,
                )
                observations.append(obs)
                summary = f"Action denied: {step.error}"
                return plan, observations, summary

            if decision == PermissionDecision.CONFIRM and not is_confirmed and not is_dry_run:
                # Pause plan for confirmation
                desc = step.description or f"Execute {step.tool} with {resolved_args}"
                token = confirmation_manager.create_confirmation(
                    plan_id=plan.id,
                    step_id=step.id,
                    tool=step.tool,
                    arguments=resolved_args,
                    description=desc,
                )
                step.status = StepStatus.CONFIRMATION_REQUIRED
                plan.status = ActionPlanStatus.CONFIRMATION_REQUIRED
                plan.confirmation_id = token
                summary = (
                    f"This action requires confirmation:\n"
                    f"{desc}\n\n"
                    f"Proceed? [y/N]"
                )
                return plan, observations, summary

            # 3. Execution (or Dry-Run)
            step.status = StepStatus.RUNNING
            if is_dry_run and step.risk_level != RiskLevel.READ_ONLY:
                result = ToolResult(
                    success=True,
                    tool=step.tool,
                    message=f"[DRY-RUN] Simulated execution of {step.tool} ({resolved_args})",
                    data={"simulated": True},
                )
            else:
                result = execute_tool(step.tool, resolved_args)

            # Record Audit
            record_audit(
                tool=step.tool,
                risk_level=step.risk_level.value,
                permission_decision=decision.value,
                arguments=resolved_args,
                success=result.success,
                session_id=session_id or plan.session_id,
                plan_id=plan.id,
                step_id=step.id,
                error_code=result.error_code,
                message=result.message,
                source=source,
            )

            # 4. Handle Result
            if not result.success:
                step.status = StepStatus.FAILED
                step.error = result.message
                plan.status = ActionPlanStatus.FAILED
                obs = Observation(
                    step_id=step.id,
                    tool=step.tool,
                    success=False,
                    summary=result.message,
                    error=result.error or result.message,
                )
                observations.append(obs)
                summary = f"I couldn't complete '{step.description or step.tool}': {result.message} Subsequent actions were stopped."
                return plan, observations, summary

            # Succeeded
            step.status = StepStatus.COMPLETED
            step.result = result.data or result.message
            step_outputs[step.id] = result.data if result.data is not None else {"result": result.message}

            obs = Observation(
                step_id=step.id,
                tool=step.tool,
                success=True,
                summary=result.message,
                data=result.data,
            )
            observations.append(obs)

        # All steps completed successfully
        plan.status = ActionPlanStatus.COMPLETED
        final_lines = [f"Completed: {plan.goal}"]
        for obs in observations:
            final_lines.append(f"- {obs.summary}")
        return plan, observations, "\n".join(final_lines)

    def resume_plan(
        self,
        plan: ActionPlan,
        confirmed: bool = True,
        session_id: Optional[str] = None,
        dry_run: Optional[bool] = None,
    ) -> Tuple[ActionPlan, List[Observation], str]:
        """
        Resume execution of a paused ActionPlan after user confirmation.
        """
        if not confirmed:
            plan.status = ActionPlanStatus.CANCELLED
            return plan, [], "Action cancelled."

        current_step = plan.steps[plan.current_step_index] if plan.current_step_index < len(plan.steps) else None
        confirmed_step_id = current_step.id if current_step else None
        return self.execute_plan(
            plan=plan,
            session_id=session_id,
            confirmed_step_id=confirmed_step_id,
            dry_run=dry_run,
        )

