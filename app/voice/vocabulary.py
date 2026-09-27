"""Bounded contextual vocabulary hints for speech recognition."""
from typing import Dict, Iterable, List, Optional

from app.config.settings import (
    JARVIS_STT_CUSTOM_VOCABULARY,
    JARVIS_STT_MAX_HINT_CHARS,
    JARVIS_STT_MAX_VOCABULARY_TERMS,
    JARVIS_STT_VOCABULARY_CATEGORIES,
)


TECHNICAL_VOCABULARY: Dict[str, List[str]] = {
    "general": ["JARVIS", "Nemotron", "Ollama"],
    "programming": [
        "Python", "Java", "recursion", "variable", "binary search", "API", "FastAPI",
        "PostgreSQL", "LangChain", "Qdrant", "pytest", "backend", "frontend",
    ],
}


def _project_terms() -> List[str]:
    from app.config.projects import PROJECTS

    names = ["JARVIS"]
    aliases = []
    for key, project in PROJECTS.items():
        names.extend([project.get("name", key), key])
        aliases.extend(project.get("aliases", []))
    return names + aliases


def build_stt_vocabulary(categories: Optional[Iterable[str]] = None,
                         custom_terms: Optional[Iterable[str]] = None,
                         max_terms: int = JARVIS_STT_MAX_VOCABULARY_TERMS,
                         max_chars: int = JARVIS_STT_MAX_HINT_CHARS) -> List[str]:
    """Build priority-ordered, deduplicated hints without conversation history."""
    selected = list(categories) if categories is not None else [item.strip() for item in JARVIS_STT_VOCABULARY_CATEGORIES.split(",")]
    candidates: List[str] = ["JARVIS"]
    if "projects" in selected:
        candidates.extend(_project_terms())
    for category in selected:
        if category != "projects":
            candidates.extend(TECHNICAL_VOCABULARY.get(category, []))
    configured = list(custom_terms) if custom_terms is not None else JARVIS_STT_CUSTOM_VOCABULARY.split(",")
    candidates.extend(configured)

    output, seen, used = [], set(), 0
    for raw in candidates:
        term = " ".join(str(raw).strip().split())
        key = term.casefold().rstrip(".")
        if not term or key in seen:
            continue
        added = len(term) + (2 if output else 0)
        if len(output) >= max(1, max_terms) or used + added > max(1, max_chars):
            break
        output.append(term)
        seen.add(key)
        used += added
    return output


def vocabulary_hint_text(**kwargs) -> str:
    return ", ".join(build_stt_vocabulary(**kwargs))
