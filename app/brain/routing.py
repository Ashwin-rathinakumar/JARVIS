"""Deterministic request analysis shared by text and voice routing."""
from dataclasses import dataclass
from enum import Enum
import re
from typing import Optional


class RouteCategory(str, Enum):
    GENERAL_CHAT = "GENERAL_CHAT"
    GENERAL_KNOWLEDGE = "GENERAL_KNOWLEDGE"
    CURRENT_INFO = "CURRENT_INFO"
    PROJECT_ACTION = "PROJECT_ACTION"
    PROJECT_QUERY = "PROJECT_QUERY"
    SYSTEM_ACTION = "SYSTEM_ACTION"
    FILE_ACTION = "FILE_ACTION"
    MEMORY_ACTION = "MEMORY_ACTION"
    OTHER_TOOL_ACTION = "OTHER_TOOL_ACTION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class WeatherRequest:
    location: Optional[str]
    when: str = "current"


def normalize_request_text(message: str) -> str:
    """Remove only anchored conversational wrappers; preserve request content."""
    text = (message or "").strip()
    text = re.sub(r"^(?:first|second|third|next)\s*[,.:;-]\s*", "", text, flags=re.I)
    text = re.sub(r"^(?:(?:hey|hi|hello)\s+)?jarvis\s*[,.:;-]?\s*", "", text, flags=re.I)
    text = re.sub(r"^(?:please\s+)?(?:can|could|would|will)\s+you\s+", "", text, flags=re.I)
    text = re.sub(r"^(?:please\s+)?tell\s+me\s+", "", text, flags=re.I)
    text = re.sub(r"\s+(?:for\s+me|please)\s*([.!?]*)$", r"\1", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def parse_weather_request(message: str) -> Optional[WeatherRequest]:
    """Recognize explicit weather questions and extract a free-form location."""
    text = normalize_request_text(message).strip()
    clean = text.rstrip(".!?").strip()
    lower = clean.lower()

    patterns = (
        r"^(?:what(?:'s| is)\s+)?(?:the\s+)?weather(?:\s+like)?(?:\s+(?:in|at|for)\s+(?P<location>.+?))?(?:\s+(?:today|tomorrow))?$",
        r"^how(?:'s| is)\s+(?:the\s+)?weather(?:\s+(?:in|at|for)\s+(?P<location>.+))?$",
        r"^how\s+(?:the\s+)?weather\s+is(?:\s+(?:in|at|for)\s+(?P<location>.+))?$",
        r"^(?:what(?:'s| is)\s+)?(?:the\s+)?temperature(?:\s+(?:in|at|for)\s+(?P<location>.+))?$",
        r"^(?:what(?:'s| is)\s+)?(?:the\s+)?forecast(?:\s+(?:in|at|for)\s+(?P<location>.+))?$",
        r"^is\s+it\s+raining(?:\s+(?:in|at)\s+(?P<location>.+))?$",
        r"^will\s+it\s+rain(?:\s+(?:in|at)\s+(?P<location>.+?))?(?:\s+(?:today|tomorrow))?$",
    )
    match = next((m for pattern in patterns if (m := re.fullmatch(pattern, lower, flags=re.I))), None)
    if not match:
        return None

    location = match.groupdict().get("location")
    if location:
        # Recover casing from the original normalized text using the matched span.
        start, end = match.span("location")
        location = clean[start:end]
        location = re.sub(r"\s+(?:today|tomorrow|right\s+now)$", "", location, flags=re.I)
        location = location.strip(" ,.!?") or None

    when = "tomorrow" if re.search(r"\btomorrow\b", lower) else (
        "today" if re.search(r"\btoday\b", lower) else "current"
    )
    return WeatherRequest(location=location, when=when)


def general_route_category(message: str) -> RouteCategory:
    normalized = normalize_request_text(message).lower()
    if re.match(r"^(?:what|who|why|how|when|where)\b", normalized) or re.match(
        r"^(?:explain|describe|define|about|tell\s+me\s+about)\b", normalized
    ):
        return RouteCategory.GENERAL_KNOWLEDGE
    return RouteCategory.GENERAL_CHAT


def category_for_tool(tool: str) -> RouteCategory:
    if tool in {"open_project", "close_project", "run_project", "stop_project"}:
        return RouteCategory.PROJECT_ACTION
    if tool in {"list_projects", "current_project", "project_status", "search_projects", "inspect_project"}:
        return RouteCategory.PROJECT_QUERY
    if tool in {
        "system_information", "cpu_info", "memory_info", "disk_info",
        "hostname", "python_version", "current_directory", "model_status", "open_application", "close_application",
    }:
        return RouteCategory.SYSTEM_ACTION
    if tool in {"list_files", "find_file", "search_files", "read_text_file", "get_file_info",
                "create_directory", "create_folder", "write_text_file", "create_text_file"}:
        return RouteCategory.FILE_ACTION
    if tool in {"remember", "show_memories", "search_memories", "forget_memory"}:
        return RouteCategory.MEMORY_ACTION
    if tool == "get_weather":
        return RouteCategory.CURRENT_INFO
    return RouteCategory.OTHER_TOOL_ACTION
