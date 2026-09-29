"""Small deterministic reference/confirmation fast paths shared by all interfaces."""
import re
from app.brain.routing import normalize_request_text
from app.brain.semantic import pending_arguments, clarification

YES = {"yes", "yeah", "yep", "confirm", "go ahead", "proceed", "do it", "continue", "y", "sure", "ok"}
NO = {"no", "nope", "cancel", "stop", "don't", "do not", "never mind", "n", "abort", "reject"}


def contextual_decision(message, session):
    text = normalize_request_text(message).lower().rstrip(".!?")
    state = session.conversation_context
    pending = pending_arguments(session)
    project = (pending or {}).get("arguments", {}).get("project_name") or state.last_project or session.current_project
    def tool(name, **args):
        return {"intent": "tool", "tool": name, "arguments": args}
    if text in {"what's my operating system", "what is my operating system", "what cpu do i have", "what cpu does my laptop have"}:
        return tool("system_information")
    if text == "what python version am i running":
        return tool("python_version")
    if text in {"show raw result", "show the raw result", "show me the full git status", "show full git status"}:
        if "git status" in text:
            return dict(tool("git_status", project_name=project), detailed=True)
        return {"intent": "chat", "answer": state.last_result.get("message", "There is no previous successful tool result in this session.")}
    if text in {"what about tomorrow", "and tomorrow", "tomorrow"} and state.last_location:
        return tool("get_weather", location=state.last_location, when="tomorrow")
    if re.fullmatch(r"(?:run|execute) (?:its|the) tests", text) and project:
        return tool("run_project_tests", project=project)
    if text in {"open it", "open that", "open that folder", "open that folder again", "open the same one", "open it again"}:
        if ("folder" in text or state.last_entity == "folder") and state.active_path:
            return tool("open_folder", path=state.active_path)
        if project:
            return tool("open_project", project_name=project)
        choices = ", ".join(state.recent_entities[-2:])
        return clarification("Which project or folder should I open" + (f": {choices}?" if choices else "?"))
    if text in {"close it", "stop it"} and project:
        return tool("close_project", project_name=project)
    if text in {"open its backend", "open its backend folder", "open the backend", "open the backend folder", "show me its backend", "show me the backend"}:
        return tool("project_folder" if text.startswith("show") else "open_project_folder", project_name=project, folder="backend")
    if text in {"go back to the project root", "open the project root"}:
        return tool("open_project_folder", project_name=project, folder=".")
    if text in {"open previous project", "open the previous project"}:
        return tool("open_project", project_name="previous_project")
    return None


def present_result(message, tool, result, detailed=False):
    if not result.success or detailed or re.search(r"\b(?:full|raw|detailed)\b", message, re.I):
        return result.message
    data = result.data if isinstance(result.data, dict) else {}
    if tool == "git_status" and "branch" in data:
        changed = len(set(data.get("staged", []) + data.get("modified", []) + data.get("untracked", [])))
        return (f"{data.get('project', 'The project')} is on {data.get('branch') or 'a detached HEAD'} with {changed} changed files: "
                f"{len(data.get('staged', []))} staged, {len(data.get('modified', []))} modified and "
                f"{len(data.get('untracked', []))} untracked. "
                f"Remotes: {', '.join(data.get('remotes', [])) or 'none'}. Ask for the full git status to see paths.")
    return result.message
