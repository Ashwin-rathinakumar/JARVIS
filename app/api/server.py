from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import (
    JARVIS_NAME,
    VERSION,
    LLM_PROVIDER,
    OLLAMA_MODEL,
)
from app.brain.llm import JarvisBrain
from app.brain.orchestrator import JarvisOrchestrator
from app.brain.confirmation import confirmation_manager
from app.agent.audit import get_audit_records, _get_connection
from app.core.schemas import (
    ChatRequest,
    ChatResponse,
    MemoryCreateRequest,
    MemoryResponse,
    ToolInfo,
    HealthResponse,
    ActionPlan,
    AuditRecord,
    ActionPlanStatus,
)
from app.tools.registry import TOOL_REGISTRY
from app.memory.database import (
    save_memory,
    get_memories,
    search_memories,
    get_connection,
)
from app.retrieval.indexer import get_index_stats
from app.state.session import session_manager
from app.utils.logger import logger


class PlanRequest(BaseModel):
    goal: str = Field(..., description="Goal to plan")
    session_id: Optional[str] = Field(None, description="Optional conversation session ID")


def create_app(brain: Optional[JarvisBrain] = None) -> FastAPI:
    """Factory creating and configuring the JARVIS FastAPI application."""
    app = FastAPI(
        title=f"{JARVIS_NAME} Core API",
        version=VERSION,
        description="Local-first Personal AI Assistant Core API with Phase 3 Agentic Actions",
    )

    # Enable CORS for future frontend / local network desktop clients
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    orchestrator = JarvisOrchestrator(brain=brain)

    @app.get("/health", response_model=HealthResponse, tags=["Diagnostics"])
    def get_health():
        """Retrieve live system health, LLM connectivity, and database stats."""
        brain_health = orchestrator.brain.health_check()
        provider_name = brain_health.get("provider", LLM_PROVIDER)
        is_connected = brain_health.get("connected", False)
        active_model = brain_health.get("model", OLLAMA_MODEL)

        # Database Check
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM memories")
                count = cursor.fetchone()[0]
            db_status = f"OK ({count} memories)"
        except Exception as e:
            db_status = f"Error: {e}"

        # Document RAG Check
        try:
            stats = get_index_stats()
            rag_status = f"OK ({stats['file_count']} files, {stats['chunk_count']} chunks)"
        except Exception as e:
            rag_status = f"Unavailable: {e}"

        curr_session = session_manager.default_session

        return HealthResponse(
            status="healthy" if is_connected else "degraded (LLM offline)",
            version=VERSION,
            provider=provider_name,
            model=active_model,
            connected=is_connected,
            database=db_status,
            document_index=rag_status,
            active_project=curr_session.get_current_project(),
            active_tasks=curr_session.list_active_processes(),
        )

    @app.post("/api/chat", response_model=ChatResponse, tags=["Assistant"])
    def chat_endpoint(request: ChatRequest):
        """Process conversational input, deterministic tool commands, or agentic goals."""
        try:
            return orchestrator.process(request.message, session_id=request.session_id)
        except Exception as e:
            logger.error(f"Error in /api/chat: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal processing error: {e}",
            )

    @app.post("/api/plan", response_model=Optional[ActionPlan], tags=["Agentic Actions"])
    def plan_endpoint(request: PlanRequest):
        """Generate a structured, validated ActionPlan without executing it."""
        plan = orchestrator.planner.plan(request.goal, session_id=request.session_id)
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to generate a valid action plan for this goal.",
            )
        return plan

    @app.get("/api/actions", response_model=List[AuditRecord], tags=["Audit History"])
    def get_actions_endpoint(limit: int = Query(50, ge=1, le=200)):
        """Retrieve recent action audit history."""
        return get_audit_records(limit=limit)

    @app.get("/api/actions/{action_id}", response_model=AuditRecord, tags=["Audit History"])
    def get_action_by_id_endpoint(action_id: int):
        """Retrieve details of an individual audited action record."""
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, timestamp, session_id, plan_id, step_id, tool,
                       risk_level, permission_decision, arguments_summary,
                       success, error_code, message
                FROM action_audits
                WHERE id = ?
            """, (action_id,))
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            raise HTTPException(status_code=404, detail=f"Audit record #{action_id} not found.")

        return AuditRecord(
            id=row[0],
            timestamp=row[1],
            session_id=row[2],
            plan_id=row[3],
            step_id=row[4],
            tool=row[5],
            risk_level=row[6],
            permission_decision=row[7],
            arguments_summary=row[8],
            success=bool(row[9]),
            error_code=row[10],
            message=row[11],
        )

    @app.post("/api/actions/{confirmation_id}/confirm", response_model=ChatResponse, tags=["Agentic Actions"])
    def confirm_action_endpoint(confirmation_id: str, session_id: Optional[str] = None):
        """Confirm a pending action step using its confirmation token."""
        conf_details = confirmation_manager.consume_confirmation(confirmation_id)
        if not conf_details:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Confirmation token expired or not found.",
            )

        curr_session = session_manager.get_session(session_id)
        plan = curr_session.pending_plan

        if not plan:
            # Reconstruct single-step plan
            step = ActionStep(
                id=conf_details.step_id,
                tool=conf_details.tool,
                arguments=conf_details.arguments,
                description=conf_details.description,
            )
            plan = ActionPlan(
                id=conf_details.plan_id,
                goal=conf_details.description,
                steps=[step],
                created_at="now",
                session_id=curr_session.session_id,
            )

        res_plan, obs_list, summary = orchestrator.executor.execute_plan(
            plan,
            session_id=curr_session.session_id,
            confirmed_step_id=conf_details.step_id,
        )

        curr_session.pending_plan = None
        curr_session.pending_confirmation_id = None

        return ChatResponse(
            success=(res_plan.status == ActionPlanStatus.COMPLETED),
            intent="action_plan",
            response=summary,
            session_id=curr_session.session_id,
            status=res_plan.status.value,
            action_plan=res_plan,
        )

    @app.post("/api/actions/{confirmation_id}/cancel", tags=["Agentic Actions"])
    def cancel_action_endpoint(confirmation_id: str, session_id: Optional[str] = None):
        """Cancel a pending action confirmation."""
        cancelled = confirmation_manager.cancel_confirmation(confirmation_id)
        curr_session = session_manager.get_session(session_id)
        curr_session.pending_plan = None
        curr_session.pending_confirmation_id = None

        return {
            "success": True,
            "confirmation_id": confirmation_id,
            "message": "Action cancelled." if cancelled else "Confirmation token was not active.",
        }

    @app.get("/api/tools", response_model=List[ToolInfo], tags=["Tools"])
    def list_tools_endpoint():
        """List all approved, registered deterministic tools."""
        tools = []
        for tool in TOOL_REGISTRY.values():
            tools.append(
                ToolInfo(
                    name=tool.name,
                    category=tool.category,
                    description=tool.description,
                    risk_level=tool.risk_level.value if hasattr(tool.risk_level, "value") else str(tool.risk_level),
                )
            )
        return tools

    @app.get("/api/memory", response_model=List[MemoryResponse], tags=["Memory"])
    def get_memories_endpoint(
        q: Optional[str] = Query(None, description="Search query keyword"),
        category: Optional[str] = Query(None, description="Memory category"),
        limit: int = Query(20, ge=1, le=100, description="Maximum memories to return"),
    ):
        """Retrieve or search persistent memories."""
        if q and q.strip():
            mems = search_memories(q.strip(), limit=limit)
        else:
            mems = get_memories(limit=limit, category=category)

        return [
            MemoryResponse(
                id=m["id"],
                content=m["content"],
                category=m.get("category", "general"),
                created_at=m.get("created_at"),
            )
            for m in mems
        ]

    @app.post("/api/memory", tags=["Memory"])
    def create_memory_endpoint(request: MemoryCreateRequest):
        """Explicitly store a new persistent memory."""
        success = save_memory(request.content, category=request.category or "general")
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Memory content cannot be empty.",
            )
        return {"success": True, "message": f"Saved memory: {request.content}"}

    @app.delete("/api/session/{session_id}", tags=["Session"])
    def delete_session_endpoint(session_id: str):
        """Reset or delete session conversational history."""
        deleted = session_manager.delete_session(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "message": "Session reset." if deleted else "Session not found or already cleared.",
        }

    return app


# Default application instance for uvicorn ASGI entrypoint
app = create_app()
