from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from app.core.schemas import RiskLevel, PermissionDecision
from app.config.settings import JARVIS_ALLOWED_PATHS, BASE_DIR
from app.utils.logger import logger

# Explicit Tool Risk Classifications
TOOL_RISK_MAP: Dict[str, RiskLevel] = {
    # READ_ONLY: Safe queries & introspection
    "system_information": RiskLevel.READ_ONLY,
    "cpu_info": RiskLevel.READ_ONLY,
    "memory_info": RiskLevel.READ_ONLY,
    "disk_info": RiskLevel.READ_ONLY,
    "hostname": RiskLevel.READ_ONLY,
    "python_version": RiskLevel.READ_ONLY,
    "current_directory": RiskLevel.READ_ONLY,
    "show_memories": RiskLevel.READ_ONLY,
    "search_memories": RiskLevel.READ_ONLY,
    "list_projects": RiskLevel.READ_ONLY,
    "current_project": RiskLevel.READ_ONLY,
    "project_status": RiskLevel.READ_ONLY,
    "analyze_project": RiskLevel.READ_ONLY,
    "project_tree": RiskLevel.READ_ONLY,
    "find_todos": RiskLevel.READ_ONLY,
    "search_projects": RiskLevel.READ_ONLY,
    "inspect_project": RiskLevel.READ_ONLY,
    "list_files": RiskLevel.READ_ONLY,
    "find_file": RiskLevel.READ_ONLY,
    "search_files": RiskLevel.READ_ONLY,
    "read_text_file": RiskLevel.READ_ONLY,
    "get_file_info": RiskLevel.READ_ONLY,
    "index_documents": RiskLevel.READ_ONLY,
    "document_status": RiskLevel.READ_ONLY,
    "ask_documents": RiskLevel.READ_ONLY,
    "get_recent_actions": RiskLevel.READ_ONLY,
    "get_weather": RiskLevel.READ_ONLY,
    "model_status": RiskLevel.READ_ONLY,
    "list_project_files": RiskLevel.READ_ONLY,
    "read_project_file": RiskLevel.READ_ONLY,
    "search_project_text": RiskLevel.READ_ONLY,
    "run_project_tests": RiskLevel.MEDIUM,

    # LOW: Safe allowlisted app / project opening / memory storing
    "open_application": RiskLevel.LOW,
    "close_application": RiskLevel.LOW,
    "open_project": RiskLevel.LOW,
    "close_project": RiskLevel.LOW,
    "remember": RiskLevel.LOW,

    # MEDIUM: State modification (folders, files, memory records, project background processes)
    "create_folder": RiskLevel.MEDIUM,
    "create_directory": RiskLevel.MEDIUM,
    "create_text_file": RiskLevel.MEDIUM,
    "write_text_file": RiskLevel.MEDIUM,
    "forget_memory": RiskLevel.MEDIUM,
    "run_project": RiskLevel.MEDIUM,
    "stop_project": RiskLevel.MEDIUM,

    # HIGH / BLOCKED: Destructive or arbitrary execution
    "delete_file": RiskLevel.BLOCKED,
    "format_disk": RiskLevel.BLOCKED,
    "disable_security": RiskLevel.BLOCKED,
    "raw_shell": RiskLevel.BLOCKED,
    "eval_code": RiskLevel.BLOCKED,
    "cmd": RiskLevel.BLOCKED,
    "powershell": RiskLevel.BLOCKED,
    "system_exec": RiskLevel.BLOCKED,
}

BLOCKED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".scr", ".com",
    ".dll", ".jar", ".msi", ".pyc", ".sh", ".bash"
}

BLOCKED_DIRECTORIES = {
    "venv", ".venv", ".git", "node_modules", "system32", "windows"
}


def get_risk_level(tool_name: str) -> RiskLevel:
    """Retrieve explicit risk level for a tool from policy mapping."""
    return TOOL_RISK_MAP.get(tool_name, RiskLevel.BLOCKED)


# Backward compatibility helpers
SAFE_TOOLS = {k for k, v in TOOL_RISK_MAP.items() if v in {RiskLevel.READ_ONLY, RiskLevel.LOW}}
CONFIRM_TOOLS = {k for k, v in TOOL_RISK_MAP.items() if v == RiskLevel.MEDIUM}
RESTRICTED_TOOLS = {k for k, v in TOOL_RISK_MAP.items() if v in {RiskLevel.HIGH, RiskLevel.BLOCKED}}


def get_permission_level(tool_name: str) -> str:
    risk = get_risk_level(tool_name)
    if risk in {RiskLevel.READ_ONLY, RiskLevel.LOW}:
        return "safe"
    if risk == RiskLevel.MEDIUM:
        return "confirm"
    return "restricted"


class PermissionEngine:
    """Deterministic security and policy evaluator for JARVIS actions."""

    @staticmethod
    def evaluate(
        tool_name: str,
        arguments: Dict[str, Any],
        confirmed: bool = False,
    ) -> Tuple[PermissionDecision, Optional[str]]:
        """
        Evaluate tool execution against deterministic security policies.

        Returns (PermissionDecision, reason_if_denied_or_confirmed).
        """
        risk = get_risk_level(tool_name)

        # 1. Blocked Tools
        if risk == RiskLevel.BLOCKED:
            logger.warning(f"Permission denied: Tool '{tool_name}' is blocked by security policy.")
            return PermissionDecision.DENY, f"Tool '{tool_name}' is blocked by security policy."

        # 2. File and Path Validation
        # Check target filepath or directory arguments
        for key in ["filepath", "directory", "folder_path", "path"]:
            if key in arguments and isinstance(arguments[key], str):
                target_str = arguments[key]
                # Check for path traversal attempts with ..
                if ".." in target_str:
                    logger.warning(f"Permission denied: Path traversal detected in '{target_str}'.")
                    return PermissionDecision.DENY, f"Access denied: Path traversal detected in '{target_str}'."

                # If write operation, validate forbidden extension
                if tool_name in {"write_text_file", "create_text_file"}:
                    target_path = Path(target_str)
                    if target_path.suffix.lower() in BLOCKED_EXTENSIONS:
                        logger.warning(f"Permission denied: Writing executable/script file '{target_str}' is prohibited.")
                        return PermissionDecision.DENY, f"Writing executable/script files ({target_path.suffix}) is strictly blocked."

                    # Check forbidden directory write
                    parts_lower = [p.lower() for p in target_path.parts]
                    if any(blocked in parts_lower for blocked in BLOCKED_DIRECTORIES):
                        logger.warning(f"Permission denied: Writing inside protected folder in '{target_str}'.")
                        return PermissionDecision.DENY, f"Writing inside protected system/environment folders is prohibited."

        # 3. Application Launching Validation
        if tool_name == "open_application":
            app_arg = str(arguments.get("app", "")).lower().strip()
            # Prevent shell smuggling
            if any(ch in app_arg for ch in [";", "&", "|", "`", "$", ">", "<", "\n"]):
                logger.warning(f"Permission denied: Shell character in application argument: '{app_arg}'")
                return PermissionDecision.DENY, "Shell syntax in application argument is prohibited."

        # 4. Decision by Risk Level
        if risk == RiskLevel.READ_ONLY:
            return PermissionDecision.ALLOW, None

        if risk == RiskLevel.LOW:
            return PermissionDecision.ALLOW, None

        if risk == RiskLevel.MEDIUM:
            if confirmed:
                return PermissionDecision.ALLOW, None
            return PermissionDecision.CONFIRM, f"Action '{tool_name}' requires confirmation."

        if risk == RiskLevel.HIGH:
            if confirmed:
                return PermissionDecision.ALLOW, None
            return PermissionDecision.CONFIRM, f"High-risk action '{tool_name}' requires confirmation."

        return PermissionDecision.DENY, f"Unknown risk classification for '{tool_name}'."
