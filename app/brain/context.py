from typing import List, Dict, Any

from app.memory.database import get_relevant_memories
from app.state.session import session
from app.config.projects import PROJECTS


def _format_memories(memories: List[Dict[str, Any]]) -> str:
    if not memories:
        return ""

    lines = ["Relevant saved memories (user facts/preferences):"]
    for memory in memories:
        lines.append(f"- User memory: {memory['content']}")

    return "\n".join(lines)


def _format_project_context() -> str:
    current = session.get_current_project()

    if not current:
        return ""

    project = PROJECTS.get(current)

    if not project:
        return ""

    return (
        "Current project context:\n"
        f"- Project: {project.get('name', current)}\n"
        f"- Path: {project.get('path', 'Unknown')}"
    )


def build_context(user_message: str) -> str:
    """
    Build compact contextual information for normal JARVIS conversation.

    Context currently contains:
    - relevant persistent memories
    - current active project

    Conversation history is handled separately by JarvisBrain/provider.
    """

    sections = []

    memories = get_relevant_memories(
        user_message,
        limit=3,
    )

    memory_context = _format_memories(memories)

    if memory_context:
        sections.append(memory_context)

    project_context = _format_project_context()

    if project_context:
        sections.append(project_context)

    if not sections:
        return user_message

    context = "\n\n".join(sections)

    return f"""
The following information may be useful when answering the user.
Use it only when relevant.
Do not invent facts that are not present here.

{context}

User request:
{user_message}
""".strip()