from typing import Optional, Any, Dict
import re
from app.brain.llm import JarvisBrain
from app.brain.intent import classify_intent, classify_intent_deterministic
from app.brain.routing import RouteCategory
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
from app.brain.followups import YES, NO, contextual_decision, present_result
from app.brain.semantic import bind_references, useful_response
from app.state.session import observe_tool_result


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

        logger.debug("Orchestrator input session=%s text=%r", current_session.session_id[:8], raw_text)
        lower = raw_text.lower().rstrip(".!?,").strip()
        if lower in YES:
            lower = "yes"
        elif lower in NO:
            lower = "no"
        # A correction is a new proposal, never approval for the old action.
        raw_text = re.sub(r"^actually\s+", "", raw_text, flags=re.I)
        raw_text = re.sub(r"\s+instead[.!?]?$", "", raw_text, flags=re.I)

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
                if not confirmation_manager.get_confirmation(current_session.pending_confirmation_id):
                    current_session.pending_plan = None
                    current_session.pending_confirmation_id = None
                    return ChatResponse(success=False, intent="system", response="That confirmation request has expired. Please issue the command again.",
                                        session_id=current_session.session_id, error="CONFIRMATION_EXPIRED")
                if lower in {"maybe", "perhaps", "not sure", "hmm"}:
                    return ChatResponse(success=True, intent="system", response="I didn't receive a clear confirmation. Say yes to continue or no to cancel.",
                                        status="confirmation_required", confirmation_id=current_session.pending_confirmation_id, session_id=current_session.session_id)
                if lower in {"y", "yes", "confirm", "proceed", "sure", "ok"}:
                    token = current_session.pending_confirmation_id
                    conf_details = confirmation_manager.consume_confirmation(token)
                    if conf_details:
                        plan: ActionPlan = current_session.pending_plan
                        # Execute the exact token-bound arguments, not a later edited plan.
                        step = next((s for s in plan.steps if s.id == conf_details.step_id), None)
                        from app.agent.executor import _resolve_step_arguments
                        outputs = {s.id: s.result for s in plan.steps if s.status == StepStatus.COMPLETED}
                        ok, resolved, _ = _resolve_step_arguments(step.arguments, outputs) if step else (False, {}, None)
                        if not ok or step.tool != conf_details.tool or resolved != conf_details.arguments:
                            current_session.pending_plan = None
                            current_session.pending_confirmation_id = None
                            return ChatResponse(success=False, intent="system", response="The pending action changed. Please request it again.", session_id=current_session.session_id)
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
                if current_session.pending_confirmation_id and any(get_risk_level(s.tool) not in {RiskLevel.READ_ONLY} for s in plan.steps):
                    confirmation_manager.cancel_confirmation(current_session.pending_confirmation_id)
                    current_session.pending_plan = None
                    current_session.pending_confirmation_id = None
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
            decision: Dict[str, Any] = contextual_decision(raw_text, current_session) or classify_intent(raw_text)
            # Let semantic reasoning handle descriptive folder requests that the
            # legacy open-project grammar otherwise mistakes for project names.
            is_gk = decision.get("route_category") == RouteCategory.GENERAL_KNOWLEDGE.value
            is_no_provider_gk = is_gk and (self.brain.provider is None and self.brain.fallback_provider is None)
            needs_semantic = not is_no_provider_gk and ((decision.get("intent") == "chat" and not decision.get("answer")) or (decision.get("tool") == "open_project" and re.search(r"\b(?:backend|folder)\b", raw_text, re.I)))
            if needs_semantic and callable(getattr(type(self.brain), "decide", None)):
                decision = self.brain.decide(raw_text, current_session)
            decision = bind_references(decision, current_session)
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
                                    session_id=current_session.session_id, error=decision.get("error"))

            if intent == "tool" and tool_name:
                if decision.get("semantic"):
                    proposal = ActionPlan(id="semantic_proposal", goal=raw_text, created_at="now",
                                          session_id=current_session.session_id,
                                          steps=[ActionStep(id="step_1", tool=tool_name, arguments=arguments)])
                    valid, error = PlanValidator.validate(proposal)
                    if not valid:
                        return ChatResponse(success=False, intent="system", response=error,
                                            session_id=current_session.session_id)
                if tool_name.startswith("git_"):
                    from app.tools.git import resolve_git_project, GitFailure
                    selected = (arguments.get("project_name") or current_session.conversation_context.last_project
                                or current_session.get_current_project())
                    try:
                        project_key, _ = resolve_git_project(selected)
                    except GitFailure as error:
                        return ChatResponse(success=False, intent="project", response=error.message,
                                            tool_used=tool_name, session_id=current_session.session_id, error=error.code)
                    # Bind the project before confirmation; later context changes cannot retarget it.
                    arguments["project_name"] = project_key
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
                    if current_session.pending_confirmation_id:
                        confirmation_manager.cancel_confirmation(current_session.pending_confirmation_id)
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
                if risk != RiskLevel.READ_ONLY and current_session.pending_confirmation_id:
                    confirmation_manager.cancel_confirmation(current_session.pending_confirmation_id)
                    current_session.pending_plan = None
                    current_session.pending_confirmation_id = None
                logger.info("Invoking tool=%s category=%s", tool_name, intent_cat)
                if tool_name == "current_project":
                    target = current_session.conversation_context.last_project or current_session.current_project
                    result = ToolResult(True, f"Current project is {target}." if target else "No project is currently active.")
                else:
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
                if result.success:
                    current_session.set_last_action(
                        intent=intent_cat,
                        tool=tool_name,
                        command=raw_text,
                        argument=arguments,
                    )
                observe_tool_result(current_session.session_id, tool_name, arguments, result)
                rendered = present_result(raw_text, tool_name, result, decision.get("detailed", False))
                if decision.get("semantic") and result.success and not re.search(r"\b(?:raw|full|detailed)\b", raw_text, re.I):
                    rendered = self.brain.summarize_tool(raw_text, tool_name, result, current_session)

                # Record conversational turn
                current_session.add_turn("user", raw_text)
                current_session.add_turn("assistant", rendered)

                return ChatResponse(
                    success=result.success,
                    intent=intent_cat,
                    response=rendered,
                    tool_used=tool_name,
                    session_id=current_session.session_id,
                    error=result.error,
                    data=result.data,
                )

            # -------------------------------------------------------------
            # 3. LLM Reasoning Branch (Chat Fallback)
            # -------------------------------------------------------------
            logger.debug("Conversation response session=%s semantic_answer=%s", current_session.session_id[:8], bool(decision.get("answer")))
            response_text = decision.get("answer") or self.brain.ask(raw_text, session_target=current_session)
            cleaned = useful_response(response_text)
            if not cleaned:
                return ChatResponse(
                    success=False,
                    intent="chat",
                    response="I couldn't produce a useful answer to that request. Please rephrase it.",
                    tool_used=None,
                    session_id=current_session.session_id,
                    error=None,
                )
            response_text = cleaned

            # Ensure turn is recorded in current_session
            if decision.get("answer") or not current_session.history or current_session.history[-1].get("content") != response_text:
                current_session.add_turn("user", raw_text)
                current_session.add_turn("assistant", response_text)

            return ChatResponse(
                success=bool(self.brain and (self.brain.provider is not None or self.brain.fallback_provider is not None)),
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
