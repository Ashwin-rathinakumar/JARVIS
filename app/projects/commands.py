"""Project-context parsing; aliases are never applied to conversational text."""
from dataclasses import dataclass
import re
from app.projects.resolver import extract_project_candidate


@dataclass(frozen=True)
class ProjectCommand:
    action: str
    candidate: str | None
    normalized_command: str


def parse_project_command(text: str) -> ProjectCommand | None:
    normalized = re.sub(r"^(open|launch|close)\s*[,.:;!?]+\s*", r"\1 ", text.strip(), flags=re.I)
    match = re.fullmatch(r"(open|launch|close)\s+(.+)", normalized, flags=re.I)
    if not match:
        return None
    return ProjectCommand("close" if match[1].lower() == "close" else "open",
                          extract_project_candidate(normalized), normalized)
