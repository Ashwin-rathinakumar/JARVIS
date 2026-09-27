import re
from typing import Dict, Any, Optional

from app.config.projects import resolve_project_key
from app.brain.routing import (
    RouteCategory,
    category_for_tool,
    general_route_category,
    normalize_request_text,
    parse_weather_request,
)
from app.utils.logger import logger


def _normalize_dir_arg(target: Optional[str]) -> str:
    """Normalize user natural language directory references to standard format."""
    if not target:
        return "."
    t = target.strip().rstrip("?").strip().lower()
    if t in {
        "",
        ".",
        "current directory",
        "the current directory",
        "this directory",
        "this folder",
        "current folder",
        "the folder",
        "the project",
        "project",
        "the project directory",
        "project directory",
        "project root",
        "the project root",
        "here",
    }:
        return "."
    return target.strip().rstrip("?").strip()


def classify_intent_deterministic(message: str) -> Optional[Dict[str, Any]]:
    """
    Fast, deterministic intent classifier for standard assistant commands.
    Returns None if the message cannot be deterministically matched.
    """
    text = normalize_request_text(message)
    if not text:
        return None

    # Normalize harmless command punctuation immediately following command verb (e.g. "Open, Sentinel AI project." -> "open sentinel ai project.")
    cleaned_command = re.sub(
        r"^(open|launch|start|run|stop|terminate|kill|inspect|status|analyze)\s*[,.:;]\s*",
        r"\1 ",
        text,
        flags=re.IGNORECASE
    )
    lower = cleaned_command.lower().strip()

    # -------------------------------------------------------------
    # 1. Projects
    # -------------------------------------------------------------
    # List projects
    if lower.rstrip(".!?") in {
        "list projects", "list my projects", "projects", "show projects", "show my projects",
        "what projects do you know", "what projects are available", "what projects do i have",
    }:
        return {"intent": "tool", "tool": "list_projects", "arguments": {}}

    # Current project
    if lower.rstrip(".!?") in {
        "current project", "what is my current project", "what project am i working on",
        "active project", "show current project",
    }:
        return {"intent": "tool", "tool": "current_project", "arguments": {}}

    # Project status
    m = re.match(r"^(?:project\s+status|status\s+of\s+project)(?:\s+(.+))?$", lower)
    if m:
        proj = m.group(1).strip() if m.group(1) else None
        return {"intent": "tool", "tool": "project_status", "arguments": {"project_name": proj}}

    # Registered test commands are executed only after the normal permission check.
    m = re.fullmatch(r"(?:run|execute)\s+(?:the\s+)?tests\s+(?:for|of)\s+(.+?)[.!?]?", cleaned_command, re.IGNORECASE)
    if m:
        from app.projects.resolver import project_resolver
        candidate = m.group(1).strip().rstrip(".!?")
        resolved = project_resolver.resolve(candidate)
        return {"intent": "tool", "tool": "run_project_tests",
                "arguments": {"project": resolved.canonical_name if resolved.matched else candidate}}

    from app.projects.commands import parse_project_command
    from app.projects.resolver import project_resolver, normalize_project_name
    command = parse_project_command(text)
    if command:
        cand = command.candidate
        if cand:
            res = project_resolver.resolve(cand)
            generic_app = cand.lower().rstrip(".!?") in {
                "notepad", "calculator", "calc", "browser", "explorer", "paint", "vscode", "cmd", "terminal"
            }
            if res.matched or res.ambiguous or not (generic_app and "project" not in lower and "repo" not in lower):
                logger.debug("Project command raw=%r normalized=%r intent=project operation=%s candidate=%r normalized_candidate=%r canonical=%r",
                             text, command.normalized_command, command.action, cand, normalize_project_name(cand), res.canonical_name)
                return {"intent": "tool", "tool": command.action + "_project",
                        "arguments": {"project_name": res.canonical_name if res.matched else cand}}
        elif "project" in lower or "repo" in lower:
            return {"intent": "clarification", "tool": None,
                    "arguments": {"message": "Please specify a registered project name."}}

    # Run project
    m = re.match(r"^(?:run|start|execute)(?:\s+project)?(?:\s+(.+))?$", lower)
    if m:
        from app.projects.resolver import extract_project_candidate, project_resolver
        cand = extract_project_candidate(text)
        if cand:
            res = project_resolver.resolve(cand)
            return {"intent": "tool", "tool": "run_project", "arguments": {"project_name": res.canonical_name or cand}}
        elif "project" in lower:
            return {"intent": "tool", "tool": "run_project", "arguments": {"project_name": None}}

    # Stop project
    m = re.match(r"^(?:stop|terminate|kill)(?:\s+project)?(?:\s+(.+))?$", lower)
    if m:
        from app.projects.resolver import extract_project_candidate, project_resolver
        cand = extract_project_candidate(text)
        if cand:
            res = project_resolver.resolve(cand)
            return {"intent": "tool", "tool": "stop_project", "arguments": {"project_name": res.canonical_name or cand}}
        elif "project" in lower:
            return {"intent": "tool", "tool": "stop_project", "arguments": {"project_name": None}}

    # Project analysis
    if lower in {"analyze current project", "analyze project", "project stats"}:
        return {"intent": "tool", "tool": "analyze_project", "arguments": {}}
    m = re.match(r"^analyze\s+(?:project\s+)?(.+)$", lower)
    if m:
        from app.projects.resolver import extract_project_candidate, project_resolver
        cand = extract_project_candidate(text) or m.group(1).strip()
        return {"intent": "tool", "tool": "analyze_project", "arguments": {"target": cand}}

    if lower in {"project tree", "project structure", "show project structure"}:
        return {"intent": "tool", "tool": "project_tree", "arguments": {}}

    if lower in {"find todos", "find todo", "search todos", "list todos"}:
        return {"intent": "tool", "tool": "find_todos", "arguments": {}}

    # -------------------------------------------------------------
    # 2. Applications
    # -------------------------------------------------------------
    # Open application
    m = re.match(r"^(?:open|launch|start|bring\s+up)\s+(?:the\s+)?(?:application\s+)?(.+)$", lower)
    if m:
        app_target = m.group(1).strip()
        # Avoid stealing project commands if explicitly containing 'project'
        if not ("project" in app_target and resolve_project_key(app_target)):
            return {"intent": "tool", "tool": "open_application", "arguments": {"app": app_target}}

    # Close application
    m = re.match(r"^(?:close|quit|shut\s+down|exit|terminate)\s+(?:the\s+)?(?:application\s+)?(.+)$", lower)
    if m:
        app_target = m.group(1).strip()
        if app_target not in {"jarvis", "system"}:
            return {"intent": "tool", "tool": "close_application", "arguments": {"app": app_target}}

    # -------------------------------------------------------------
    # 3. System Information
    # -------------------------------------------------------------
    system_command = lower.rstrip(".!?").strip()
    if system_command in {"what model are you using", "which model are you using", "model status", "show model status"}:
        return {"intent": "tool", "tool": "model_status", "arguments": {}}
    if system_command in {
        "show system info",
        "show system information",
        "show my system info",
        "show my system information",
        "system info",
        "system information",
        "tell me about my system",
        "pc info",
        "computer info",
        "specs",
        "system specs",
        "laptop info",
        "laptop information",
        "give me the system information of my laptop",
        "give me system info",
    } or re.match(r"^(?:give\s+me\s+(?:the\s+)?)?system\s+info(?:rmation)?(?:\s+(?:of|about|for)\s+(?:my\s+)?(?:laptop|pc|computer|system))?$", system_command) or re.match(
        r"^(?:what|which)\s+(?:operating\s+system|os)\s+(?:am\s+i|is\s+(?:this|my)\s+(?:computer|pc|machine))\s+(?:running|using)$",
        system_command,
    ) or re.match(
        r"^how\s+much\s+(?:free\s+)?(?:disk|drive|storage)\s+space\s+(?:do\s+i\s+have|i\s+have|is\s+(?:available|free))$",
        system_command,
    ) or re.match(
        r"^how\s+many\s+cpu\s+cores\s+(?:are\s+there|does\s+(?:this|my)\s+(?:computer|pc|machine)\s+have)$",
        system_command,
    ) or re.match(
        r"^what\s+(?:version\s+of\s+python|python\s+version)\s+is\s+installed$",
        system_command,
    ) or system_command in {
        "show my machine specs", "show machine specs", "what's my computer name",
        "what is my computer name", "what's my hostname", "what is my hostname",
    }:
        return {"intent": "tool", "tool": "system_information", "arguments": {}}

    if lower in {"cpu info", "cpu", "processor info"}:
        return {"intent": "tool", "tool": "cpu_info", "arguments": {}}

    if lower in {"memory info", "ram info", "ram"}:
        return {"intent": "tool", "tool": "memory_info", "arguments": {}}

    if lower in {"disk info", "storage info", "drive info", "disk space"}:
        return {"intent": "tool", "tool": "disk_info", "arguments": {}}

    if lower in {"hostname", "computer name"}:
        return {"intent": "tool", "tool": "hostname", "arguments": {}}

    if lower in {"python version", "python"}:
        return {"intent": "tool", "tool": "python_version", "arguments": {}}

    if lower in {"current directory", "pwd", "cwd", "working directory"}:
        return {"intent": "tool", "tool": "current_directory", "arguments": {}}

    # -------------------------------------------------------------
    # 4. Current information (explicit live-data requests)
    # -------------------------------------------------------------
    weather = parse_weather_request(text)
    if weather:
        if not weather.location:
            return {
                "intent": "clarification",
                "tool": None,
                "arguments": {"message": "Which location would you like the weather for?"},
                "route_category": RouteCategory.CURRENT_INFO.value,
                "confidence": 1.0,
                "reason": "explicit_weather_request_missing_location",
            }
        return {
            "intent": "tool",
            "tool": "get_weather",
            "arguments": {"location": weather.location, "when": weather.when},
        }

    # -------------------------------------------------------------
    # 5. Memory
    # -------------------------------------------------------------
    m = re.match(r"^remember\s+that\s+(.+)$", lower) or re.match(r"^remember\s+(.+)$", lower)
    if m:
        # Preserve original case for the memory content
        prefix_len = len(text) - len(m.group(1))
        content = text[prefix_len:].strip()
        return {"intent": "tool", "tool": "remember", "arguments": {"content": content}}

    if lower in {"show memories", "memories", "list memories", "what do you remember", "what have you remembered"}:
        return {"intent": "tool", "tool": "show_memories", "arguments": {}}

    m = re.match(r"^search\s+memories\s+(?:for\s+)?(.+)$", lower)
    if m:
        return {"intent": "tool", "tool": "search_memories", "arguments": {"query": m.group(1).strip()}}

    m = re.match(r"^forget\s+memory\s+(?:#)?(\d+)$", lower)
    if m:
        return {"intent": "tool", "tool": "forget_memory", "arguments": {"memory_id": int(m.group(1))}}

    # -------------------------------------------------------------
    # 6. Local Document RAG
    # -------------------------------------------------------------
    if lower in {"index documents", "index document"}:
        return {"intent": "tool", "tool": "index_documents", "arguments": {}}

    if lower in {"document status", "documents status", "rag status"}:
        return {"intent": "tool", "tool": "document_status", "arguments": {}}

    m = re.match(r"^ask\s+documents?\s+(.+)$", text, re.IGNORECASE)
    if m:
        return {"intent": "tool", "tool": "ask_documents", "arguments": {"query": m.group(1).strip()}}

    # -------------------------------------------------------------
    # 7. File Operations
    # -------------------------------------------------------------
    # Exact shortcuts
    if lower in {
        "list files",
        "list the files",
        "show files",
        "show the files",
        "show me files",
        "show me the files",
        "list all files",
        "show all files",
        "files",
        "dir",
        "ls",
    }:
        return {"intent": "tool", "tool": "list_files", "arguments": {"directory": "."}}

    # "list/show (me) (the/all) files/folder/directory (in ...)"
    m = re.match(
        r"^(?:list|show|display)(?:\s+me)?(?:\s+the|\s+all)?\s+(?:files|directory|folder|contents)(?:\s+(?:in|of|for)\s+|\s+)?(.*)?$",
        lower
    )
    if m:
        raw_d = m.group(1).strip() if m.group(1) else "."
        d = _normalize_dir_arg(raw_d)
        return {"intent": "tool", "tool": "list_files", "arguments": {"directory": d}}

    # Natural questions: "what files are in this folder?", "what files are in the project?", etc.
    m = re.match(
        r"^(?:what|which)\s+files\s+are\s+(?:there\s+)?in\s+(.+?)(?:\?)?$",
        lower
    )
    if m:
        raw_d = m.group(1).strip()
        d = _normalize_dir_arg(raw_d)
        return {"intent": "tool", "tool": "list_files", "arguments": {"directory": d}}

    # "find file <pattern>", "find files <pattern>", "search for file <pattern>"
    m = re.match(r"^(?:find|search(?:\s+for)?)\s+files?\s+(.+)$", lower)
    if m:
        return {"intent": "tool", "tool": "find_file", "arguments": {"pattern": m.group(1).strip()}}

    # "read file <path>", "read text file <path>", "show file <path>", "view file <path>"
    m = re.match(r"^(?:read|view|cat)\s+(?:text\s+)?file\s+(.+)$", text, re.IGNORECASE)
    if m:
        return {"intent": "tool", "tool": "read_text_file", "arguments": {"filepath": m.group(1).strip()}}

    return None


def classify_intent(user_message: str) -> dict:
    """
    Two-stage routing: select only explicit deterministic capabilities, then
    default ordinary language to the general assistant. The LLM answers chat;
    it does not invent or select executable tool calls.
    """
    normalized = normalize_request_text(user_message)
    deterministic_result = classify_intent_deterministic(user_message)
    if deterministic_result is not None:
        tool = deterministic_result.get("tool")
        if tool:
            deterministic_result.setdefault("route_category", category_for_tool(tool).value)
        deterministic_result.setdefault("confidence", 1.0)
        deterministic_result.setdefault("reason", "explicit_deterministic_match")
        logger.debug(
            "Routing transcript=%r normalized=%r category=%s intent=%s tool=%s arguments=%r confidence=%s reason=%s",
            user_message, normalized, deterministic_result.get("route_category"),
            deterministic_result.get("intent"), tool, deterministic_result.get("arguments"),
            deterministic_result.get("confidence"), deterministic_result.get("reason"),
        )
        return deterministic_result

    category = general_route_category(user_message)
    decision = {
        "intent": "chat",
        "tool": None,
        "arguments": {"message": user_message},
        "route_category": category.value,
        "confidence": 1.0,
        "reason": "no_explicit_tool_required",
    }
    logger.debug(
        "Routing transcript=%r normalized=%r category=%s intent=chat tool=None arguments={} confidence=1.0 reason=%s",
        user_message, normalized, category.value, decision["reason"],
    )
    return decision
