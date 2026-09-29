from dataclasses import dataclass
from typing import Callable, Dict, Any, Optional, List

from app.core.schemas import RiskLevel
from app.brain.permissions import get_risk_level
from app.tools.apps import open_application, close_application
from app.tools.projects import (
    open_project,
    close_project,
    run_project,
    stop_project,
    list_projects,
    get_current_project,
    get_project_status,
    search_projects,
    inspect_project,
)
from app.tools.system import (
    get_system_information,
    get_cpu_info,
    get_memory_info,
    get_disk_info,
    get_hostname,
    get_python_version,
    get_current_directory,
)
from app.tools.weather import get_weather
from app.tools.git import git_status, git_commit, git_push, git_pull, git_commit_push, git_publish
from app.tools.folders import project_folder, open_project_folder, open_folder, project_overview
from app.tools.model import get_model_status
from app.tools.agent_project import list_project_files, read_project_file, search_project_text, run_project_tests
from app.tools.files import (
    list_files,
    find_file,
    search_files,
    read_text_file,
    create_directory,
    create_folder,
    write_text_file,
    create_text_file,
    get_file_info,
)
from app.tools.analysis import (
    analyze_project,
    find_todos,
    get_project_tree,
)
from app.memory.database import (
    save_memory,
    get_memories,
    search_memories,
    forget_memory,
    format_memories_display,
)
from app.retrieval.rag import (
    index_all_documents,
    ask_documents,
    get_document_status,
)
from app.agent.audit import get_recent_actions
from app.utils.logger import logger


@dataclass
class ToolResult:
    """Standardized result container for JARVIS tool execution."""
    success: bool
    message: str
    tool: Optional[str] = None
    data: Any = None
    error_code: Optional[str] = None
    error: Optional[str] = None

    def __str__(self) -> str:
        return self.message


@dataclass
class ToolDefinition:
    """Descriptor for a registered JARVIS tool."""
    name: str
    category: str
    description: str
    function: Callable
    risk_level: RiskLevel = RiskLevel.READ_ONLY


def _remember_wrapper(content: str, category: str = "general") -> str:
    if not content:
        return "Nothing was provided to remember."
    success = save_memory(content, category)
    if success:
        return f"Remembered: {content}"
    return "Failed to save memory."


def _show_memories_wrapper(limit: int = 10, category: Optional[str] = None) -> str:
    mems = get_memories(limit=limit, category=category)
    return format_memories_display(mems)


def _search_memories_wrapper(query: str) -> str:
    mems = search_memories(query)
    if not mems:
        return f"No memories found matching '{query}'."
    return format_memories_display(mems)


def _forget_memory_wrapper(memory_id: int) -> str:
    success = forget_memory(int(memory_id))
    if success:
        return f"Removed memory #{memory_id}."
    return f"No memory found with ID #{memory_id}."


# Central Tool Registry
TOOL_REGISTRY: Dict[str, ToolDefinition] = {}


def register_tool(
    name: str,
    category: str,
    description: str,
    function: Callable,
    risk_level: Optional[RiskLevel] = None,
):
    actual_risk = risk_level if risk_level is not None else get_risk_level(name)
    TOOL_REGISTRY[name] = ToolDefinition(
        name=name,
        category=category,
        description=description,
        function=function,
        risk_level=actual_risk,
    )


# --- Register Applications ---
register_tool("open_application", "Applications", "Open an allowlisted application", open_application, RiskLevel.LOW)
register_tool("close_application", "Applications", "Close a running application safely", close_application, RiskLevel.LOW)

# --- Register Projects ---
def _open_project_scoped(project_name: str = "", project_name_or_path: Optional[str] = None, application: str = "vscode"):
    return open_project(project_name, project_name_or_path, application, track_default_session=False)

register_tool("project_folder", "Projects", "Locate a project subfolder without opening it", project_folder)
register_tool("open_project_folder", "Projects", "Open a folder inside a registered project in Explorer", open_project_folder)
register_tool("project_overview", "Projects", "Read project manifests to identify its declared technology stack", project_overview)
register_tool("open_folder", "Files", "Open a validated folder in Explorer", open_folder)
for _git_function in (git_status, git_commit, git_push, git_pull, git_commit_push, git_publish):
    register_tool(_git_function.__name__, "Projects", "Safe Git workflow for a registered project", _git_function)
register_tool("close_project", "Projects", "Gracefully close a tracked project editor", close_project, RiskLevel.LOW)
register_tool("open_project", "Projects", "Open a project directory in VS Code", _open_project_scoped, RiskLevel.LOW)
register_tool("search_projects", "Projects", "Search for project directories and candidates", search_projects, RiskLevel.READ_ONLY)
register_tool("inspect_project", "Projects", "Inspect project structure and tech stack", inspect_project, RiskLevel.READ_ONLY)
register_tool("run_project", "Projects", "Run a registered project in the background", run_project, RiskLevel.MEDIUM)
register_tool("stop_project", "Projects", "Stop a running project process", stop_project, RiskLevel.MEDIUM)
register_tool("list_projects", "Projects", "List configured projects", list_projects, RiskLevel.READ_ONLY)
register_tool("current_project", "Projects", "Show the currently active project", get_current_project, RiskLevel.READ_ONLY)
register_tool("project_status", "Projects", "Show status of a project", get_project_status, RiskLevel.READ_ONLY)
register_tool("analyze_project", "Projects", "Analyze project file statistics", analyze_project, RiskLevel.READ_ONLY)
register_tool("project_tree", "Projects", "Display directory tree of a project", get_project_tree, RiskLevel.READ_ONLY)
register_tool("find_todos", "Projects", "Search for TODO and FIXME tags", find_todos, RiskLevel.READ_ONLY)

# --- Register System ---
register_tool("system_information", "System", "Display OS, hardware, and runtime info", get_system_information, RiskLevel.READ_ONLY)
register_tool("cpu_info", "System", "Display CPU specs and core count", get_cpu_info, RiskLevel.READ_ONLY)
register_tool("memory_info", "System", "Display RAM usage statistics", get_memory_info, RiskLevel.READ_ONLY)
register_tool("disk_info", "System", "Display drive storage information", get_disk_info, RiskLevel.READ_ONLY)
register_tool("hostname", "System", "Show computer network name", get_hostname, RiskLevel.READ_ONLY)
register_tool("python_version", "System", "Show Python runtime version", get_python_version, RiskLevel.READ_ONLY)
register_tool("current_directory", "System", "Show current working directory", get_current_directory, RiskLevel.READ_ONLY)
register_tool("get_recent_actions", "System", "Display recent audit history of executed actions", get_recent_actions, RiskLevel.READ_ONLY)

# --- Register Current Information ---
register_tool("get_weather", "CurrentInfo", "Retrieve live weather for a location", get_weather, RiskLevel.READ_ONLY)
register_tool("model_status", "System", "Show safe configured model status", get_model_status, RiskLevel.READ_ONLY)
register_tool("list_project_files", "Projects", "List files inside a registered project", list_project_files, RiskLevel.READ_ONLY)
register_tool("read_project_file", "Projects", "Read a bounded file inside a registered project", read_project_file, RiskLevel.READ_ONLY)
register_tool("search_project_text", "Projects", "Search bounded text inside a registered project", search_project_text, RiskLevel.READ_ONLY)
register_tool("run_project_tests", "Projects", "Run a registered project's trusted test command", run_project_tests, RiskLevel.MEDIUM)

# --- Register Files ---
register_tool("list_files", "Files", "List directory contents safely", list_files, RiskLevel.READ_ONLY)
register_tool("find_file", "Files", "Find files matching a glob pattern", find_file, RiskLevel.READ_ONLY)
register_tool("search_files", "Files", "Search files by name or extension", search_files, RiskLevel.READ_ONLY)
register_tool("read_text_file", "Files", "Read text file contents safely", read_text_file, RiskLevel.READ_ONLY)
register_tool("create_directory", "Files", "Create a directory inside allowed workspace", create_directory, RiskLevel.MEDIUM)
register_tool("create_folder", "Files", "Alias for create_directory", create_folder, RiskLevel.MEDIUM)
register_tool("write_text_file", "Files", "Write safe UTF-8 text file", write_text_file, RiskLevel.MEDIUM)
register_tool("create_text_file", "Files", "Alias for write_text_file", create_text_file, RiskLevel.MEDIUM)
register_tool("get_file_info", "Files", "View file metadata and timestamps", get_file_info, RiskLevel.READ_ONLY)

# --- Register Memory ---
register_tool("remember", "Memory", "Save information into SQLite memory", _remember_wrapper, RiskLevel.MEDIUM)
register_tool("show_memories", "Memory", "Display saved memories", _show_memories_wrapper, RiskLevel.READ_ONLY)
register_tool("search_memories", "Memory", "Search memories by keyword", _search_memories_wrapper, RiskLevel.READ_ONLY)
register_tool("forget_memory", "Memory", "Remove a memory by ID", _forget_memory_wrapper, RiskLevel.MEDIUM)

# --- Register Documents / RAG ---
register_tool("index_documents", "Documents", "Index documents for RAG search", index_all_documents, RiskLevel.READ_ONLY)
register_tool("document_status", "Documents", "Check indexed documents statistics", get_document_status, RiskLevel.READ_ONLY)
register_tool("ask_documents", "Documents", "Query documents with hybrid search", ask_documents, RiskLevel.READ_ONLY)


def get_tool(name: str) -> Optional[ToolDefinition]:
    return TOOL_REGISTRY.get(name)


def list_tools() -> Dict[str, List[ToolDefinition]]:
    categories: Dict[str, List[ToolDefinition]] = {}
    for tool in TOOL_REGISTRY.values():
        categories.setdefault(tool.category, []).append(tool)
    return categories


def execute_tool(tool_name: str, arguments: dict) -> ToolResult:
    """Execute a registered tool safely with argument validation and error catching."""
    tool_def = TOOL_REGISTRY.get(tool_name)
    if not tool_def:
        logger.warning(f"Attempted to execute unknown tool: {tool_name}")
        return ToolResult(
            success=False,
            tool=tool_name,
            message=f"I don't recognize the tool '{tool_name}'.",
            error_code="UNKNOWN_TOOL",
            error="Unknown tool"
        )

    try:
        raw_res = tool_def.function(**arguments)

        if isinstance(raw_res, ToolResult):
            return raw_res

        data = None
        if isinstance(raw_res, dict):
            data = raw_res
            msg = raw_res.get("message", str(raw_res))
            if "success" in raw_res and not raw_res["success"]:
                return ToolResult(
                    success=False,
                    tool=tool_name,
                    message=msg,
                    data=data,
                    error_code=raw_res.get("error_code", "EXECUTION_FAILED"),
                    error=raw_res.get("error", msg)
                )
        else:
            msg = str(raw_res)

        if tool_name == "open_project" and not msg.startswith("Opened "):
            return ToolResult(success=False, tool=tool_name, message=msg, data=data,
                              error_code="PROJECT_OPEN_FAILED", error=msg)
        if msg.startswith(("Project directory not found", "I don't know the project", "No run command is configured")):
            return ToolResult(success=False, tool=tool_name, message=msg, data=data,
                              error_code="PROJECT_ACTION_FAILED", error=msg)

        # Semantic check for access denied / error strings
        if msg.startswith("Access denied"):
            return ToolResult(
                success=False,
                tool=tool_name,
                message=msg,
                data=data,
                error_code="PATH_NOT_ALLOWED",
                error=msg
            )
        elif msg.startswith("Error") or msg.startswith("Unable to") or msg.startswith("Failed to"):
            return ToolResult(
                success=False,
                tool=tool_name,
                message=msg,
                data=data,
                error_code="TOOL_EXECUTION_ERROR",
                error=msg
            )

        logger.info(f"Executed tool '{tool_name}' successfully")
        return ToolResult(
            success=True,
            tool=tool_name,
            message=msg,
            data=data or raw_res
        )

    except TypeError as error:
        logger.error(f"Argument error in tool '{tool_name}': {error}")
        return ToolResult(
            success=False,
            tool=tool_name,
            message=f"Invalid arguments for {tool_name}: {error}",
            error_code="INVALID_ARGUMENTS",
            error=str(error)
        )

    except Exception as error:
        logger.error(f"Execution error in tool '{tool_name}': {error}")
        return ToolResult(
            success=False,
            tool=tool_name,
            message=f"Tool execution failed: {error}",
            error_code="UNCAUGHT_TOOL_ERROR",
            error=str(error)
        )
