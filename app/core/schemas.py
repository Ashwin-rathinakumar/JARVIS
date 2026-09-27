from enum import Enum
from typing import Optional, Any, List, Dict
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CONFIRMATION_REQUIRED = "confirmation_required"


class ActionPlanStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CONFIRMATION_REQUIRED = "confirmation_required"


class ActionStep(BaseModel):
    id: str = Field(..., description="Unique step identifier, e.g. step_1")
    tool: str = Field(..., description="Name of the registered tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments or dependency references")
    description: Optional[str] = Field(None, description="Human-readable description of this step")
    risk_level: RiskLevel = Field(RiskLevel.READ_ONLY, description="Risk level computed from tool metadata")
    requires_confirmation: bool = Field(False, description="Whether this step requires user confirmation")
    status: StepStatus = Field(StepStatus.PENDING, description="Execution status")
    result: Optional[Any] = Field(None, description="Execution result or observation")
    error: Optional[str] = Field(None, description="Error message if step failed")


class ActionPlan(BaseModel):
    id: str = Field(..., description="Unique action plan UUID")
    goal: str = Field(..., description="User goal or request being planned")
    steps: List[ActionStep] = Field(default_factory=list, description="Ordered steps in the plan")
    status: ActionPlanStatus = Field(ActionPlanStatus.PENDING, description="Overall plan status")
    created_at: str = Field(..., description="ISO 8601 timestamp of plan creation")
    session_id: Optional[str] = Field(None, description="Associated session ID")
    current_step_index: int = Field(0, description="Index of currently executing step")
    confirmation_id: Optional[str] = Field(None, description="Active pending confirmation ID if paused")


class Observation(BaseModel):
    step_id: str
    tool: str
    success: bool
    summary: str
    data: Optional[Any] = None
    error: Optional[str] = None


class ConfirmationDetails(BaseModel):
    confirmation_id: str
    plan_id: str
    step_id: str
    tool: str
    arguments: Dict[str, Any]
    description: str
    expires_at: float


class AuditRecord(BaseModel):
    id: Optional[int] = None
    timestamp: str
    session_id: Optional[str] = None
    plan_id: Optional[str] = None
    step_id: Optional[str] = None
    tool: str
    risk_level: str
    permission_decision: str
    arguments_summary: str
    success: bool
    error_code: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = "cli"



class ChatRequest(BaseModel):
    message: str = Field(..., description="User message or command")
    session_id: Optional[str] = Field(None, description="Optional conversation session ID")


class ChatResponse(BaseModel):
    success: bool = Field(True, description="Whether the request succeeded")
    intent: str = Field(..., description="Classified intent (e.g. chat, system, file, memory, project, document, action_plan, unknown)")
    response: str = Field(..., description="Assistant response text")
    tool_used: Optional[str] = Field(None, description="Name of the tool executed, if any")
    session_id: str = Field(..., description="Active session ID")
    error: Optional[str] = Field(None, description="Error message if request failed")
    data: Optional[Any] = Field(None, description="Structured tool output data if available")
    status: Optional[str] = Field(None, description="Status code (e.g. confirmation_required, completed, failed)")
    confirmation_id: Optional[str] = Field(None, description="Pending confirmation token if confirmation is required")
    action_plan: Optional[ActionPlan] = Field(None, description="Structured ActionPlan if multi-step planning occurred")


class MemoryCreateRequest(BaseModel):
    content: str = Field(..., description="Information to store")
    category: Optional[str] = Field("general", description="Memory category (preference, project, fact, instruction, general)")


class MemoryResponse(BaseModel):
    id: int
    content: str
    category: str = "general"
    created_at: Optional[str] = None


class ToolInfo(BaseModel):
    name: str
    category: str
    description: str
    risk_level: str = "read_only"


class HealthResponse(BaseModel):
    status: str
    version: str
    provider: str
    model: str
    connected: bool
    database: str
    document_index: str
    active_project: Optional[str] = None
    active_tasks: List[str] = []
