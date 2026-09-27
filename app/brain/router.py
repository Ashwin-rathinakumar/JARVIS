from typing import Optional, Any

from app.brain.intent import classify_intent
from app.tools.registry import execute_tool, TOOL_REGISTRY, ToolResult
from app.state.session import session
from app.utils.logger import logger


def execute_command(command: str, brain: Any = None) -> Optional[str]:
    """
    Route a user input string to the appropriate deterministic tool if applicable.
    Returns the string output of the tool execution, or None if the input is general chat.
    """
    decision = classify_intent(command)

    intent = decision.get("intent")
    tool = decision.get("tool")
    arguments = decision.get("arguments", {})

    if intent != "tool" or not tool:
        return None

    # Handle tools requiring optional brain dependency
    if tool == "ask_documents" and brain is not None:
        arguments["brain"] = brain

    logger.info(f"Routing command to tool '{tool}' with arguments: {arguments}")
    result: ToolResult = execute_tool(tool, arguments)

    session.set_last_action(
        intent="tool",
        tool=tool,
        command=command,
        argument=arguments
    )

    return result.message