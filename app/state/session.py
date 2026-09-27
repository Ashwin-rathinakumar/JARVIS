import uuid
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from app.config.settings import MAX_CONTEXT_MESSAGES


@dataclass
class ConversationContext:
    """Bounded, non-sensitive context used for deterministic follow-ups."""

    last_intent: Optional[str] = None
    last_tool: Optional[str] = None
    last_project: Optional[str] = None
    last_location: Optional[str] = None
    last_entities: Dict[str, str] = field(default_factory=dict)

    def record(self, intent: Optional[str], tool: Optional[str], arguments: Optional[Dict[str, Any]] = None) -> None:
        self.last_intent = intent
        self.last_tool = tool
        arguments = arguments or {}
        project = arguments.get("project_name") or arguments.get("project_name_or_path")
        location = arguments.get("location")
        if project:
            self.last_project = str(project)
            self.last_entities["project"] = self.last_project
        if location:
            self.last_location = str(location)
            self.last_entities["location"] = self.last_location


class SessionState:
    """Session state for a conversation in JARVIS."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id: str = session_id or str(uuid.uuid4())
        self.current_project: Optional[str] = None
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self.last_intent: Optional[str] = None
        self.last_tool: Optional[str] = None
        self.last_command: Optional[str] = None
        self.last_app: Optional[str] = None
        self.last_argument: Any = None
        self.history: List[Dict[str, str]] = []
        self.pending_plan: Optional[Any] = None
        self.pending_confirmation_id: Optional[str] = None
        self.conversation_context = ConversationContext()

    def set_current_project(self, project_name: str) -> None:
        self.current_project = project_name

    def get_current_project(self) -> Optional[str]:
        return self.current_project

    def clear_current_project(self) -> None:
        self.current_project = None

    def register_process(self, name: str, process: subprocess.Popen) -> None:
        self.active_processes[name] = process

    def get_process(self, name: str) -> Optional[subprocess.Popen]:
        proc = self.active_processes.get(name)
        if proc and proc.poll() is not None:
            # Process has already terminated
            del self.active_processes[name]
            return None
        return proc

    def unregister_process(self, name: str) -> Optional[subprocess.Popen]:
        return self.active_processes.pop(name, None)

    def list_active_processes(self) -> List[str]:
        # Clean up terminated processes
        dead = [k for k, p in self.active_processes.items() if p.poll() is not None]
        for k in dead:
            del self.active_processes[k]
        return list(self.active_processes.keys())

    def set_last_action(
        self,
        intent: Optional[str] = None,
        tool: Optional[str] = None,
        command: Optional[str] = None,
        app: Optional[str] = None,
        argument: Any = None
    ) -> None:
        self.last_intent = intent
        self.last_tool = tool
        self.last_command = command
        self.last_app = app
        self.last_argument = argument

    def add_turn(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        max_bound = max(20, MAX_CONTEXT_MESSAGES * 2)
        if len(self.history) > max_bound:
            self.history = self.history[-max_bound:]

    def add_message(self, role: str, content: str) -> None:
        """Alias for add_turn."""
        self.add_turn(role, content)

    def get_recent_history(self, limit: int = 6) -> List[Dict[str, str]]:
        return self.history[-limit:]

    def get_recent_messages(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """Get recent conversational messages bounded by limit or MAX_CONTEXT_MESSAGES."""
        effective_limit = limit if limit is not None else MAX_CONTEXT_MESSAGES
        return self.history[-effective_limit:]

    def clear(self) -> None:
        self.session_id = str(uuid.uuid4())
        self.current_project = None
        self.active_processes.clear()
        self.last_intent = None
        self.last_tool = None
        self.last_command = None
        self.last_app = None
        self.last_argument = None
        self.history.clear()
        self.pending_plan = None
        self.pending_confirmation_id = None
        self.conversation_context = ConversationContext()


class SessionManager:
    """Manages active conversational sessions by session_id."""

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}
        self._default_session = SessionState()
        self._sessions[self._default_session.session_id] = self._default_session

    @property
    def default_session(self) -> SessionState:
        return self._default_session

    def get_session(self, session_id: Optional[str] = None) -> SessionState:
        """Get or create a session by ID."""
        if not session_id:
            return self._default_session

        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState(session_id=session_id)
        return self._sessions[session_id]

    def delete_session(self, session_id: str) -> bool:
        """Delete or reset a session."""
        if session_id in self._sessions:
            if self._sessions[session_id] is self._default_session:
                self._default_session.clear()
            else:
                del self._sessions[session_id]
            return True
        return False

    def list_sessions(self) -> List[str]:
        return list(self._sessions.keys())


# Global session manager and default active session singleton
session_manager = SessionManager()
session = session_manager.default_session
