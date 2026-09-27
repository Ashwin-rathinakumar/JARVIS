"""Untrusted model plan proposals. Parsing never executes a proposal."""
import json
from dataclasses import dataclass, field
from typing import List, Optional

from app.utils.logger import logger


@dataclass(frozen=True)
class ReasoningPlan:
    objective: str
    steps: List[str] = field(default_factory=list)
    requires_tools: bool = False
    proposed_actions: List[str] = field(default_factory=list)


def parse_reasoning_plan(raw: str) -> Optional[ReasoningPlan]:
    try:
        data = json.loads(raw)
        if data.get("type") != "plan" or not isinstance(data.get("objective"), str):
            return None
        steps = data.get("steps", [])
        actions = data.get("proposed_actions", [])
        if not isinstance(steps, list) or not all(isinstance(item, str) for item in steps):
            return None
        if not isinstance(actions, list) or not all(isinstance(item, str) for item in actions):
            return None
        return ReasoningPlan(data["objective"], steps[:20], bool(data.get("requires_tools", False)), actions[:20])
    except (json.JSONDecodeError, TypeError, AttributeError):
        logger.warning("Reasoning plan parse failure; no actions executed")
        return None
