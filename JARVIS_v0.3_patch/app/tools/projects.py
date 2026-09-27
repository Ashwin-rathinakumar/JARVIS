import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from app.config.projects import PROJECTS, resolve_project_key
from app.config.settings import DEFAULT_EDITOR
from app.state.session import session
from app.utils.logger import logger


def find_vscode_launcher() -> Optional[Tuple[str, bool]]:
    """
    Locate the VS Code executable or launcher on Windows.
    Returns a tuple of (command_or_path, use_shell).
    Returns None if not found.
    """
    # 1. Custom configured editor if specified
    custom_editor = os.getenv("JARVIS_EDITOR") or DEFAULT_EDITOR
    if custom_editor and custom_editor.lower() not in {"code", "vscode"}:
        custom_path = Path(custom_editor)
        if custom_path.exists():
            return (str(custom_path), False)
        which_custom = shutil.which(custom_editor)
        if which_custom:
            return (which_custom, which_custom.lower().endswith((".cmd", ".bat")))

    # 2. Known standard Windows installation paths for Code.exe
    possible_paths = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft VS Code" / "Code.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft VS Code" / "Code.exe",
    ]

    for p in possible_paths:
        if p.is_file():
            return (str(p), False)

    # 3. Check PATH for code.exe, code.cmd, code
    code_exe = shutil.which("code.exe")
    if code_exe:
        return (code_exe, False)

    code_cmd = shutil.which("code.cmd")
    if code_cmd:
        return (code_cmd, True)

    code_bin = shutil.which("code")
    if code_bin:
        # On Windows, if code is found without extension, check if code.cmd is in same dir
        cmd_candidate = Path(code_bin).with_suffix(".cmd")
        if cmd_candidate.is_file():
            return (str(cmd_candidate), True)
        return (code_bin, True)

    return None


def open_project(project_name: str) -> str:
    """Open a registered project directory in VS Code."""
    key = resolve_project_key(project_name)
    if not key or key not in PROJECTS:
        return f"I don't know the project '{project_name}'. Use 'list projects' to see known projects."

    project = PROJECTS[key]
    path = Path(project["path"])

    if not path.exists():
        return f"Project path does not exist: {path}"

    launcher_info = find_vscode_launcher()
    if not launcher_info:
        return "I couldn't find VS Code on this machine. Please ensure 'code' is on your PATH or configure DEFAULT_EDITOR."

    launcher, use_shell = launcher_info

    try:
        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )

        if use_shell:
            # Launch .cmd/.bat through cmd.exe without enabling shell=True.
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            command = [comspec, "/d", "/s", "/c", launcher, str(path)]
        else:
            command = [launcher, str(path)]

        subprocess.Popen(command, shell=False, **popen_kwargs)

        session.set_current_project(key)
        logger.info(f"Opened project '{project['name']}' at {path}")
        return f"Opened {project['name']} in VS Code."

    except Exception as error:
        logger.error(f"Failed to open project '{project['name']}': {error}")
        return f"Couldn't open {project['name']}: {error}"


def run_project(project_name: Optional[str] = None) -> str:
    """Run the specified project (or currently active project) in a background process."""
    if not project_name:
        key = session.get_current_project()
    else:
        key = resolve_project_key(project_name)

    if not key or key not in PROJECTS:
        return "I don't know which project you mean. Specify a project name or open one first."

    project = PROJECTS[key]
    run_cmd = project.get("run_command")
    if not run_cmd:
        return f"No run command is configured for {project['name']}."

    # Check if already running
    existing_proc = session.get_process(key)
    if existing_proc:
        return f"{project['name']} is already running (PID: {existing_proc.pid})."

    path = Path(project["path"])
    if not path.exists():
        return f"Project directory does not exist: {path}"

    try:
        if isinstance(run_cmd, str):
            # Backward compatibility for older configs. Prefer list commands.
            if os.name == "nt":
                import shlex
                command = shlex.split(run_cmd, posix=False)
            else:
                import shlex
                command = shlex.split(run_cmd)
        else:
            command = list(run_cmd)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(path)

        popen_kwargs = {
            "cwd": str(path),
            "shell": False,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": env,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )

        proc = subprocess.Popen(command, **popen_kwargs)
        session.register_process(key, proc)
        session.set_current_project(key)
        logger.info(f"Started project '{project['name']}' (PID: {proc.pid}) with command: {run_cmd}")
        return f"Started {project['name']} (PID: {proc.pid})."

    except Exception as error:
        logger.error(f"Failed to run project '{project['name']}': {error}")
        return f"Couldn't run {project['name']}: {error}"


def stop_project(project_name: Optional[str] = None) -> str:
    """Stop a project process started by JARVIS."""
    if not project_name:
        key = session.get_current_project()
    else:
        key = resolve_project_key(project_name)

    if not key or key not in PROJECTS:
        return "I don't know which project you mean."

    project = PROJECTS[key]
    proc = session.get_process(key)

    if not proc:
        return f"{project['name']} does not appear to be running (or was not started by JARVIS)."

    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

        session.unregister_process(key)
        logger.info(f"Stopped project '{project['name']}'")
        return f"Stopped {project['name']}."

    except Exception as error:
        logger.error(f"Failed to stop project '{project['name']}': {error}")
        return f"Couldn't stop {project['name']}: {error}"


def list_projects() -> str:
    """List all registered projects."""
    if not PROJECTS:
        return "No projects are configured."

    lines = ["Known projects:"]
    current = session.get_current_project()

    for key, project in PROJECTS.items():
        marker = " (current)" if key == current else ""
        desc = f" - {project.get('description', '')}" if project.get('description') else ""
        lines.append(f"- {project['name']} [{key}]{marker}{desc}")

    return "\n".join(lines)


def get_current_project() -> str:
    """Return the name of the currently active project."""
    current = session.get_current_project()
    if not current or current not in PROJECTS:
        return "No project is currently active."
    return f"Current project is {PROJECTS[current]['name']}."


def get_project_status(project_name: Optional[str] = None) -> str:
    """Check the status of a project."""
    if not project_name:
        key = session.get_current_project()
    else:
        key = resolve_project_key(project_name)

    if not key or key not in PROJECTS:
        return "No project selected or specified."

    project = PROJECTS[key]
    path = Path(project["path"])
    exists = "exists" if path.exists() else "NOT FOUND"
    proc = session.get_process(key)
    run_state = f"Running (PID: {proc.pid})" if proc else "Stopped"

    return f"Project: {project['name']}\nPath: {path} ({exists})\nStatus: {run_state}"