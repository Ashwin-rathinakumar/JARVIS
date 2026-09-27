"""Context assembly helpers for JARVIS conversations."""
from typing import List, Dict, Any

from app.memory.database import retrieve_relevant_memories
from app.state.session import session


def _format_memories(memories: List[Dict[str, Any]]) -> str:
    if not memories:
        return ""
    lines = ["Relevant saved memories:"]
    for memory in memories:
        lines.append(f"- {memory['content']}")
    return "\n".join(lines)


def _format_project_state() -> str:
    current = session.get_current_project()
    if not current:
        return ""
    return f"Current project key: {current}"


def build_conversation_prompt(message: str, memory_limit: int = 4) -> str:
    """Build compact context for a normal conversational LLM request.

    Persistent memories are retrieved by relevance rather than dumping the
    entire memory database into every prompt. Tool commands never pass through
    this path; this is only used by ``JarvisBrain.ask``.
    """
    sections: List[str] = []

    memories = retrieve_relevant_memories(message, limit=memory_limit)
    memory_text = _format_memories(memories)
    if memory_text:
        sections.append(memory_text)

    project_text = _format_project_state()
    if project_text:
        sections.append(project_text)

    if not sections:
        return message

    context = "\n\n".join(sections)
    return (
        "Use the context below only when it is relevant to the user's request. "
        "Do not mention that context was retrieved unless useful. Never invent memories.\n\n"
        f"{context}\n\n"
        f"User request:\n{message}"
    )
