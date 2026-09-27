from typing import Optional, Any, Dict
import re
from app.brain.llm import JarvisBrain
from app.brain.intent import classify_intent, classify_intent_deterministic
from app.brain.planner import JarvisPlanner, PlanValidator
from app.brain.permissions import PermissionEngine, get_risk_level
from app.brain.confirmation import confirmation_manager
from app.agent.executor import AgentExecutor
from app.agent.audit import record_audit
from app.tools.registry import execute_tool, TOOL_REGISTRY, ToolResult
from app.state.session import session_manager, SessionState
from app.core.schemas import (
    ChatResponse,
    ActionPlan,
    ActionStep,
    ActionPlanStatus,
    StepStatus,
    PermissionDecision,
    RiskLevel,
)
from app.utils.logger import logger
from app.agent.controlled import ControlledAgent, AgentRunStatus


def _get_intent_category(tool_name: Optional[str]) -> str:
    """Map tool name to high-level intent category."""
    if not tool_name:
        return "chat"

    tool_def = TOOL_REGISTRY.get(tool_name)
    if not tool_def:
        return "tool"

    category_map = {
        "Applications": "system",
        "System": "system",
        "Files": "file",
        "Memory": "memory",
        "Projects": "project",
        "Documents": "document",
        "CurrentInfo": "current_info",
    }
    return category_map.get(tool_def.category, "tool")


class JarvisOrchestrator:
    """
    Central orchestration engine for JARVIS.

    Coordinates user requests, multi-step agentic planning, deterministic tool execution,
    permission enforcement, confirmation management, and LLM reasoning.
    """

    def __init__(self, brain: Optional[JarvisBrain] = None):
        self.brain = brain or JarvisBrain()
        self.planner = JarvisPlanner(brain=self.brain)
        self.executor = AgentExecutor()
        self.agent = ControlledAgent(self.brain.generate)

    @staticmethod
    def _agent_response(run, session_id: str) -> ChatResponse:
        if run.status == AgentRunStatus.WAITING_FOR_CONFIRMATION:
            step = run.steps[run.current_step]
            message = f"The next agent step requires confirmation: {step.action}({step.arguments}). Do you want me to continue?"
            return ChatResponse(success=True, intent="agent", response=message, session_id=session_id,
                                status="confirmation_required", confirmation_id=run.confirmation_id)
        success = run.status == AgentRunStatus.COMPLETED
        return ChatResponse(success=success, intent="agent", response=run.final_summary or f"Agent status: {run.status.value}.",
                            session_id=session_id, status=run.status.value.lower())

    def process(
        self,
        message: str,
        session_id: Optional[str] = None,
        source: str = "cli",
    ) -> ChatResponse:
        """
        Process a user input string and return a structured ChatResponse.
        """
        raw_text = (message or "").strip()
        current_session: SessionState = session_manager.get_session(session_id)

        if not raw_text:
            return ChatResponse(
                success=True,
                intent="chat",
                response="How can I assist you?",
                tool_used=None,
                session_id=current_session.session_id,
                error=None,
            )

        logger.info(f"Orchestrator processing request [session={current_session.session_id[:8]}]: {raw_text[:60]}")
        lower = raw_text.lower()

        try:
            active_agent = self.agent.status(current_session.session_id)
            if active_agent and active_agent.status == AgentRunStatus.WAITING_FOR_CONFIRMATION and lower in {"y", "yes", "confirm", "proceed", "n", "no", "cancel", "stop"}:
                approved = lower in {"y", "yes", "confirm", "proceed"}
                return self._agent_response(self.agent.confirm(current_session.session_id, approved), current_session.session_id)
            if lower in {"cancel", "stop the task", "never mind"} and active_agent:
                return self._agent_response(self.agent.cancel(current_session.session_id), current_session.session_id)
            if lower.rstrip(".?") in {"what are you doing", "task status", "current task"}:
                if not active_agent:
                    return ChatResponse(success=True, intent="agent", response="There is no agent task in this session.", session_id=current_session.session_id)
                completed = sum(1 for step in active_agent.steps if step.status == "COMPLETED")
                return ChatResponse(success=True, intent="agent", response=f"Objective: {active_agent.objective}. Status: {active_agent.status.value}. Completed steps: {completed}.", session_id=current_session.session_id)
            if re.match(r"^(?:investigate|diagnose|check\s+.+\s+and|run\s+the\s+tests\s+and)\b", lower):
                run = self.agent.start(raw_text, current_session.session_id)
                return self._agent_response(run, current_session.session_id)
            # -------------------------------------------------------------
            # 0. Handle Active Confirmation Replies (e.g. "y", "yes", "n", "cancel")
            # -------------------------------------------------------------
            if current_session.pending_plan and current_session.pending_confirmation_id:
                if lower in {"y", "yes", "confirm", "proceed", "sure", "ok"}:
                    token = current_session.pending_confirmation_id
                    conf_details = confirmation_manager.consume_confirmation(token)
                    if conf_details:
                        plan: ActionPlan = current_session.pending_plan
                        current_session.pending_plan = None
                        current_session.pending_confirmation_id = None

                        logger.info(f"Resuming confirmed plan [{plan.id[:8]}] step [{conf_details.step_id}]")
                        res_plan, obs_list, summary = self.executor.execute_plan(
                            plan,
                            session_id=current_session.session_id,
                            confirmed_step_id=conf_details.step_id,
                            source=source,
                        )

                        # Check if another step requires confirmation
                        if res_plan.status == ActionPlanStatus.CONFIRMATION_REQUIRED:
                            current_session.pending_plan = res_plan
                            current_session.pending_confirmation_id = res_plan.confirmation_id
                            return ChatResponse(
                                success=True,
                                intent="action_plan",
                                response=summary,
                                session_id=current_session.session_id,
                                status="confirmation_required",
                                confirmation_id=res_plan.confirmation_id,
                                action_plan=res_plan,
                            )

                        current_session.add_turn("user", raw_text)
                        current_session.add_turn("assistant", summary)

                        return ChatResponse(
                            success=(res_plan.status == ActionPlanStatus.COMPLETED),
                            intent="action_plan",
                            response=summary,
                            session_id=current_session.session_id,
                            status=res_plan.status.value,
                            action_plan=res_plan,
                        )
                    else:
                        current_session.pending_plan = None
                        current_session.pending_confirmation_id = None
                        return ChatResponse(
                            success=False,
                            intent="system",
                            response="Confirmation token expired or not found. Please re-issue the command.",
                            session_id=current_session.session_id,
                            error="CONFIRMATION_EXPIRED",
                        )

                elif lower in {"n", "no", "cancel", "stop", "abort", "reject"}:
                    token = current_session.pending_confirmation_id
                    confirmation_manager.cancel_confirmation(token)
                    current_session.pending_plan = None
                    current_session.pending_confirmation_id = None
                    logger.info("User cancelled pending confirmation.")
                    return ChatResponse(
                        success=True,
                        intent="system",
                        response="Action cancelled.",
                        session_id=current_session.session_id,
                    )

            # -------------------------------------------------------------
            # 1. Check for Compound / Multi-Step Goal (Planner)
            # -------------------------------------------------------------
            # Indicators for planning: " and ", " then ", "find ... and open ...", "create ... and write ..."
            is_compound_indicator = any(kw in lower for kw in [" and ", " then ", " and then ", "find ", "locate "])
            plan = self.planner.plan_deterministic(raw_text, session_id=current_session.session_id)

            if plan:
                logger.info(f"Executing planned multi-step goal with {len(plan.steps)} steps")
                res_plan, obs_list, summary = self.executor.execute_plan(
                    plan,
                    session_id=current_session.session_id,
                    source=source,
                )

                if res_plan.status == ActionPlanStatus.CONFIRMATION_REQUIRED:
                    current_session.pending_plan = res_plan
                    current_session.pending_confirmation_id = res_plan.confirmation_id
                    return ChatResponse(
                        success=True,
                        intent="action_plan",
                        response=summary,
                        session_id=current_session.session_id,
                        status="confirmation_required",
                        confirmation_id=res_plan.confirmation_id,
                        action_plan=res_plan,
                    )

                current_session.add_turn("user", raw_text)
                current_session.add_turn("assistant", summary)

                return ChatResponse(
                    success=(res_plan.status == ActionPlanStatus.COMPLETED),
                    intent="action_plan",
                    response=summary,
                    session_id=current_session.session_id,
                    status=res_plan.status.value,
                    action_plan=res_plan,
                )

            # -------------------------------------------------------------
            # 2. Fast Single-Tool Deterministic / Classification Routing
            # -------------------------------------------------------------
            decision: Dict[str, Any] = classify_intent(raw_text)
            intent = decision.get("intent", "chat")
            tool_name = decision.get("tool")
            arguments = decision.get("arguments", {})
            route_category = decision.get("route_category", "UNKNOWN")
            logger.debug(
                "Orchestration route category=%s intent=%s tool=%s arguments=%r confidence=%s reason=%s",
                route_category, intent, tool_name, arguments,
                decision.get("confidence"), decision.get("reason"),
            )

            if intent == "clarification":
                clarification_intent = "current_info" if route_category == "CURRENT_INFO" else "project"
                return ChatResponse(success=False, intent=clarification_intent, response=arguments["message"],
                                    session_id=current_session.session_id)

            if intent == "tool" and tool_name:
                intent_cat = _get_intent_category(tool_name)
                risk = get_risk_level(tool_name)

                # Inject brain dependency if needed
                if tool_name in {"ask_documents", "model_status"} and self.brain is not None:
                    arguments["brain"] = self.brain

                # Check Permission Engine
                perm_decision, reason = PermissionEngine.evaluate(tool_name, arguments)
                logger.debug("Permission tool=%s decision=%s", tool_name, perm_decision.value)

                if perm_decision == PermissionDecision.DENY:
                    record_audit(
                        tool=tool_name,
                        risk_level=risk.value,
                        permission_decision=perm_decision.value,
                        arguments=arguments,
                        success=False,
                        session_id=current_session.session_id,
                        error_code="PERMISSION_DENIED",
                        message=reason,
                        source=source,
                    )
                    return ChatResponse(
                        success=False,
                        intent=intent_cat,
                        response=f"Access denied: {reason}",
                        tool_used=tool_name,
                        session_id=current_session.session_id,
                        error="PERMISSION_DENIED",
                    )

                if perm_decision == PermissionDecision.CONFIRM:
                    token = confirmation_manager.create_confirmation(
                        plan_id=f"single_{tool_name}",
                        step_id="step_1",
                        tool=tool_name,
                        arguments=arguments,
                        description=f"Execute {tool_name} with {arguments}",
                    )
                    single_step = ActionStep(
                        id="step_1",
                        tool=tool_name,
                        arguments=arguments,
                        risk_level=risk,
                        requires_confirmation=True,
                        status=StepStatus.CONFIRMATION_REQUIRED,
                    )
                    single_plan = ActionPlan(
                        id=f"single_{token[:8]}",
                        goal=raw_text,
                        steps=[single_step],
                        status=ActionPlanStatus.CONFIRMATION_REQUIRED,
                        created_at=current_session.session_id,
                        session_id=current_session.session_id,
                        confirmation_id=token,
                    )
                    current_session.pending_plan = single_plan
                    current_session.pending_confirmation_id = token
                    confirm_msg = f"This action requires confirmation:\n{tool_name}({arguments})\n\nProceed? [y/N]"
                    return ChatResponse(
                        success=True,
                        intent=intent_cat,
                        response=confirm_msg,
                        tool_used=tool_name,
                        session_id=current_session.session_id,
                        status="confirmation_required",
                        confirmation_id=token,
                        action_plan=single_plan,
                    )

                # Execute tool
                logger.info(f"Orchestrator invoking tool '{tool_name}' ({intent_cat}) with arguments: {arguments}")
                result: ToolResult = execute_tool(tool_name, arguments)

                # Record audit
                record_audit(
                    tool=tool_name,
                    risk_level=risk.value,
                    permission_decision=perm_decision.value,
                    arguments=arguments,
                    success=result.success,
                    session_id=current_session.session_id,
                    error_code=result.error_code,
                    message=result.message,
                    source=source,
                )

                # Update session state with action
                current_session.set_last_action(
                    intent=intent_cat,
                    tool=tool_name,
                    command=raw_text,
                    argument=arguments,
                )
                current_session.conversation_context.record(intent_cat, tool_name, arguments)

                # Record conversational turn
                current_session.add_turn("user", raw_text)
                current_session.add_turn("assistant", result.message)

                return ChatResponse(
                    success=result.success,
                    intent=intent_cat,
                    response=result.message,
                    tool_used=tool_name,
                    session_id=current_session.session_id,
                    error=result.error,
                    data=result.data,
                )

            # -------------------------------------------------------------
            # 3. LLM Reasoning Branch (Chat Fallback)
            # -------------------------------------------------------------
            logger.info(f"Orchestrator delegating to LLM brain: {raw_text[:60]}")
            response_text = self.brain.ask(raw_text, session_target=current_session)

            # Ensure turn is recorded in current_session
            if not current_session.history or current_session.history[-1].get("content") != response_text:
                current_session.add_turn("user", raw_text)
                current_session.add_turn("assistant", response_text)

            return ChatResponse(
                success=True,
                intent="chat",
                response=response_text,
                tool_used=None,
                session_id=current_session.session_id,
                error=None,
            )

        except Exception as error:
            logger.error(f"Orchestrator exception: {error}", exc_info=True)
            return ChatResponse(
                success=False,
                intent="unknown",
                response=f"An error occurred while processing your request: {error}",
                tool_used=None,
                session_id=current_session.session_id,
                error=str(error),
            )
