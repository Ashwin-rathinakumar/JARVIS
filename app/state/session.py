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
    active_path: Optional[str] = None
    active_repository: Optional[str] = None
    previous_project: Optional[str] = None
    last_action: Optional[str] = None
    last_result: Dict[str, Any] = field(default_factory=dict)
    last_entity: Optional[str] = None
    recent_entities: List[str] = field(default_factory=list)

    @property
    def active_project(self):
        return self.last_project

    def snapshot(self):
        return {"active_project": self.last_project, "active_path": self.active_path,
                "active_repository": self.active_repository, "previous_project": self.previous_project,
                "last_tool": self.last_tool, "last_action": self.last_action,
                "last_result": self.last_result, "last_entity": self.last_entity,
                "recent_entities": self.recent_entities[-5:]}

    def record(self, intent: Optional[str], tool: Optional[str], arguments: Optional[Dict[str, Any]] = None) -> None:
        self.last_intent = intent
        self.last_tool = tool
        arguments = arguments or {}
        project = arguments.get("project_name") or arguments.get("project_name_or_path")
        location = arguments.get("location")
        if project:
            if self.last_project and self.last_project != str(project):
                self.previous_project = self.last_project
            self.last_project = str(project)
            self.last_entities["project"] = self.last_project
        if location:
            self.last_location = str(location)
            self.last_entities["location"] = self.last_location

    def observe(self, tool, arguments, result):
        """Only successful results promote entities into working context."""
        if not result.success:
            return
        from app.config.projects import PROJECTS, resolve_project_key
        args = dict(arguments)
        old_project = self.last_project
        project = args.get("project_name") or args.get("project_name_or_path") or args.get("project")
        if not project and tool in {"inspect_project", "project_overview"}:
            project = args.get("path_or_name")
        key = resolve_project_key(project) if project else None
        if key:
            args["project_name"] = PROJECTS[key].get("name", key)
        self.record("project" if project else "tool", tool, args)
        self.last_action = tool
        data = result.data if isinstance(result.data, dict) else {}
        # Never forward arbitrary file contents, credentials or environment output.
        if tool in {"read_text_file", "read_project_file", "ask_documents", "search_project_text"}:
            self.last_result = {"success": True, "message": "Requested content was returned; it is not retained in working context."}
        else:
            self.last_result = {"success": True, "message": result.message[:3500]}
            for name in ("branch", "staged", "modified", "untracked", "remotes", "stack", "path"):
                if name in data:
                    value = data[name]
                    self.last_result[name] = [str(x)[:300] for x in value[:40]] if isinstance(value, list) else str(value)[:1000] if value is not None else None
        if key and (tool == "open_project" or old_project != self.last_project):
            from pathlib import Path
            self.active_path = str(Path(PROJECTS[key]["path"]).resolve())
            self.last_entity = "project"
        if tool.startswith("git_"):
            self.active_repository = self.last_project
        elif key and old_project != self.last_project:
            self.active_repository = None
        if tool in {"open_folder", "project_folder", "open_project_folder"} and data.get("path"):
            self.active_path = data["path"]
            self.last_entity = "folder"
        entity = self.last_project if key else self.active_path if tool == "open_folder" else None
        if entity:
            self.recent_entities = [x for x in self.recent_entities if x != entity][-4:] + [entity]


def observe_tool_result(session_id, tool, arguments, result):
    active = session_manager.get_session(session_id)
    active.conversation_context.observe(tool, arguments, result)
    if result.success and active.conversation_context.last_project:
        active.set_current_project(active.conversation_context.last_project)


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
