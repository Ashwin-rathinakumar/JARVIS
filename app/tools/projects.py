import os
import time
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any

from app.config.projects import PROJECTS
from app.config.settings import JARVIS_ALLOWED_PATHS, BASE_DIR
from app.state.session import session
from app.utils.logger import logger
from app.tools.files import is_path_allowed


from app.projects.resolver import project_resolver
from app.projects.lifecycle import project_lifecycle

# ---------------------------------------------------------
# PROJECT NAME RESOLUTION
# ---------------------------------------------------------

def resolve_project_key(project_name: str) -> Optional[str]:
    """
    Resolve a user-supplied project name to a key in PROJECTS via ProjectResolver.
    """
    if not project_name:
        return None
    res = project_resolver.resolve(project_name)
    if res.matched:
        return res.project_key
    return None


# ---------------------------------------------------------
# VS CODE DISCOVERY
# ---------------------------------------------------------

def find_vscode_launcher() -> Tuple[Optional[str], bool]:
    """
    Locate VS Code. Prefer actual Code.exe executable.
    """
    possible_paths = [
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "Microsoft VS Code"
        / "Code.exe",

        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft VS Code"
        / "Code.exe",

        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft VS Code"
        / "Code.exe",
    ]

    for candidate in possible_paths:
        if candidate.exists():
            return str(candidate), False

    launcher = shutil.which("code")
    if launcher:
        if Path(launcher).suffix.lower() in {".cmd", ".bat"}:
            native = Path(launcher).resolve().parent.parent / "Code.exe"
            if native.is_file():
                return str(native), False
            return launcher, True
        return launcher, False

    launcher = shutil.which("code.cmd")
    if launcher:
        return launcher, True

    return None, False


def _windows_process_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


# ---------------------------------------------------------
# SEARCH PROJECTS & DISCOVERY
# ---------------------------------------------------------

def search_projects(query: str = "") -> Dict[str, Any]:
    """
    Search for projects across registered registry and allowed workspace directories.
    Handles ambiguity when multiple projects match.
    """
    query_lower = query.lower().strip() if query else ""
    matches = []

    # 1. Search registered PROJECTS
    for key, project in PROJECTS.items():
        name = project.get("name", key)
        path = project.get("path", "")
        aliases = [a.lower() for a in project.get("aliases", [])]

        if not query_lower or query_lower in key.lower() or query_lower in name.lower() or any(query_lower in a for a in aliases):
            matches.append({
                "name": name,
                "key": key,
                "path": str(Path(path).resolve()) if path else "",
                "source": "registered",
            })

    # An exact registered identity takes precedence over similarly named
    # workspace archive folders (e.g. JARVIS versus JARVIS_v0.3_patch).
    from app.projects.resolver import ProjectResolver
    resolved = ProjectResolver(PROJECTS).resolve(query) if query else None
    if resolved and resolved.matched and resolved.match_type in {"exact_canonical", "exact_normalized", "explicit_alias"}:
        project = PROJECTS[resolved.project_key]
        chosen = {"name": project.get("name", resolved.project_key), "key": resolved.project_key,
                  "path": str(Path(project["path"]).resolve()), "source": "registered"}
        return {"matches": [chosen], "path": chosen["path"], "name": chosen["name"],
                "message": f"Found project '{chosen['name']}' at {chosen['path']}"}

    # 2. Search filesystem in JARVIS_ALLOWED_PATHS
    for root_dir in JARVIS_ALLOWED_PATHS:
        r_path = Path(root_dir).resolve()
        if not r_path.exists():
            continue

        # Inspect immediate child subdirectories for project markers
        try:
            for child in r_path.iterdir():
                if child.is_dir() and child.name.lower() not in {"venv", ".venv", ".git", "node_modules", "logs", "data"}:
                    if not query_lower or query_lower in child.name.lower():
                        # Check if already added
                        child_resolved = str(child.resolve())
                        if not any(m["path"] == child_resolved for m in matches):
                            matches.append({
                                "name": child.name,
                                "key": child.name.lower(),
                                "path": child_resolved,
                                "source": "workspace",
                            })
        except Exception:
            pass

    if not matches:
        msg = f"No projects found matching '{query}'." if query else "No projects found."
        return {"matches": [], "path": None, "message": msg}

    if len(matches) == 1:
        chosen = matches[0]
        msg = f"Found project '{chosen['name']}' at {chosen['path']}"
        return {"matches": matches, "path": chosen["path"], "name": chosen["name"], "message": msg}

    # Ambiguity case: multiple projects found
    lines = [f"I found {len(matches)} matching projects:"]
    for idx, m in enumerate(matches, 1):
        lines.append(f"{idx}. {m['name']} ({m['path']})")
    lines.append("Which one would you like to use?")
    msg = "\n".join(lines)
    # Stop dependent plans here: exposing the first path would let a planner
    # open it despite the clarification question in the message.
    return {"success": False, "matches": matches, "path": None, "ambiguous": True, "message": msg}


# ---------------------------------------------------------
# INSPECT PROJECT
# ---------------------------------------------------------

def inspect_project(path_or_name: str) -> str:
    """
    Inspect project structure, tech stack/language, git status, and key files.
    """
    target_path = None

    # Check registered project key first
    key = resolve_project_key(path_or_name)
    if key and key in PROJECTS:
        target_path = Path(PROJECTS[key]["path"]).resolve()
    else:
        p = Path(path_or_name)
        if not p.is_absolute():
            p = (BASE_DIR / p).resolve()
        target_path = p.resolve()

    if not target_path.exists():
        # Try searching by query
        search_res = search_projects(path_or_name)
        if search_res.get("path") and Path(search_res["path"]).exists():
            target_path = Path(search_res["path"]).resolve()
        else:
            return f"Project directory not found: {path_or_name}"

    if not is_path_allowed(target_path):
        return f"Access denied: '{target_path}' is outside permitted directories."

    # Identify project type & languages
    indicators = []
    if (target_path / "requirements.txt").exists() or (target_path / "pyproject.toml").exists() or (target_path / "setup.py").exists():
        indicators.append("Python")
    if (target_path / "package.json").exists():
        indicators.append("Node.js / JavaScript")
    if (target_path / "tsconfig.json").exists():
        indicators.append("TypeScript")
    if (target_path / "pom.xml").exists() or (target_path / "build.gradle").exists():
        indicators.append("Java")
    if (target_path / "platformio.ini").exists():
        indicators.append("PlatformIO / C++")
    if (target_path / "Cargo.toml").exists():
        indicators.append("Rust")

    tech_stack = ", ".join(indicators) if indicators else "Generic / Unknown"
    has_git = (target_path / ".git").exists()

    # Inspect top-level files
    top_files = []
    dir_count = 0
    file_count = 0
    try:
        for item in sorted(target_path.iterdir()):
            if item.name.lower() in {"venv", ".venv", ".git", "node_modules", "__pycache__"}:
                continue
            if item.is_dir():
                dir_count += 1
            else:
                file_count += 1
                if len(top_files) < 10:
                    top_files.append(item.name)
    except Exception as e:
        return f"Error inspecting {target_path}: {e}"

    stat = target_path.stat()
    mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))

    lines = [
        f"Project Inspection: {target_path.name}",
        f"Path: {target_path}",
        f"Tech Stack: {tech_stack}",
        f"Git Repository: {'Yes' if has_git else 'No'}",
        f"Top-level Structure: {file_count} files, {dir_count} directories",
        f"Key Files: {', '.join(top_files) if top_files else 'None'}",
        f"Last Modified: {mtime}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------
# LIST PROJECTS
# ---------------------------------------------------------

def list_projects() -> str:
    if not PROJECTS:
        return "No projects are currently configured."

    lines = ["Known Projects:"]
    for key, project in PROJECTS.items():
        name = project.get("name", key)
        path = project.get("path", "Unknown")
        lines.append(f"- {name} [{key}] -> {path}")

    return "\n".join(lines)


# ---------------------------------------------------------
# OPEN PROJECT
# ---------------------------------------------------------

def open_project(project_name: str = "", project_name_or_path: Optional[str] = None, application: str = "vscode", track_default_session: bool = True) -> str:
    """
    Open a registered project or validated path in VS Code.
    """
    target_str = project_name_or_path or project_name
    if not target_str or target_str.strip().lower() in {"", "new project", "project", "a new project", "my project"}:
        return "I couldn't determine which project you want to open. Please specify a project name."

    from app.projects.resolver import extract_project_candidate
    clean_target = extract_project_candidate(target_str) or target_str
    path = None
    display_name = clean_target

    # 1. Resolve registered project
    resolution = project_resolver.resolve(target_str)
    if resolution.ambiguous:
        return resolution.message or "Multiple matching projects found. Please specify."

    if resolution.matched and resolution.project_key in PROJECTS:
        project_key = resolution.project_key
        project = PROJECTS[project_key]
        display_name = project.get("name", project_key)
        path = Path(project["path"]).resolve()
    else:
        # Planner dependencies may contain an exact registered root. No guessed
        # paths or discovered unregistered directories become launch targets.
        matches = [k for k, p in PROJECTS.items()
                   if Path(target_str).is_absolute() and Path(target_str).resolve() == Path(p["path"]).resolve()]
        if len(matches) != 1:
            return f"I don't know the project '{target_str}'."
        project_key = matches[0]
        project = PROJECTS[project_key]
        display_name = project.get("name", project_key)
        path = Path(project["path"]).resolve()

    if not path or not path.is_dir():
        return f"Project directory not found: {path or target_str}"

    if not is_path_allowed(path):
        return f"Access denied: '{path}' is outside permitted directories."

    launcher, use_shell = find_vscode_launcher()
    if not launcher:
        return "VS Code could not be found on this machine."

    try:
        if use_shell or Path(launcher).suffix.lower() in {".cmd", ".bat"}:
            return "Failed to open project: a native VS Code executable is required for safe tracking."
        previous = project_lifecycle.status(project_key)
        if previous is not None and previous.process.poll() is None and previous.open is not False:
            if project_lifecycle.wait_until_open(project_key):
                return f"Opened {display_name} in VS Code previously; its tracked instance is still active."
            return f"Failed to open {display_name}: {project_lifecycle.startup_failure(project_key)}"
        profile = project_lifecycle.new_profile()
        command = [launcher, "--new-window", "--user-data-dir", str(profile), str(path)]
        logger.debug("Project execution operation=open key=%s registered_path=%s permission=allowed", project_key, path)
        proc = subprocess.Popen(
            command, shell=False, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )
        project_lifecycle.track(project_key, display_name, path, profile, proc)
        if not project_lifecycle.wait_until_open(project_key):
            return f"Failed to open {display_name}: {project_lifecycle.startup_failure(project_key)}"

        if track_default_session:
            session.set_current_project(project_key or display_name)
        return f"Opened {display_name} in VS Code."

    except Exception as error:
        logger.exception("Failed to open project %s", target_str)
        return f"Failed to open {display_name} in VS Code: {error}"


def close_project(project_name: str) -> dict:
    resolution = project_resolver.resolve(project_name)
    if not resolution.matched:
        return {"success": False, "message": resolution.message or f"I don't know the project '{project_name}'."}
    project = PROJECTS[resolution.project_key]
    path = Path(project["path"]).resolve()
    if not is_path_allowed(path):
        return {"success": False, "message": "Access denied: project root is outside permitted directories."}
    try:
        success, detail = project_lifecycle.close(resolution.project_key, path)
        message = f"Closed {project['name']}." if success else f"{project['name']}: {detail}"
        logger.debug("Project execution operation=close key=%s registered_path=%s success=%s result=%s",
                     resolution.project_key, path, success, message)
        return {"success": success, "message": message}
    except Exception as error:
        logger.exception("Scoped editor close failed")
        return {"success": False, "message": f"Failed to close {project['name']}: {error}"}


# ---------------------------------------------------------
# RUN PROJECT
# ---------------------------------------------------------

def run_project(project_name: str) -> str:
    project_key = resolve_project_key(project_name)
    if not project_key or project_key not in PROJECTS:
        return f"I don't know the project '{project_name}'."

    project = PROJECTS[project_key]
    path = Path(project["path"]).resolve()

    if not path.exists():
        return f"Project directory not found: {path}"

    run_cmd = project.get("run_command")
    if not run_cmd:
        return f"No run command is configured for {project['name']}."

    existing_process = session.get_process(project_key)
    if existing_process:
        return f"{project['name']} is already running (PID: {existing_process.pid})."

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(path)

    try:
        proc = subprocess.Popen(
            run_cmd,
            cwd=str(path),
            env=environment,
            shell=False,
            stdout=None,
            stderr=None,
            stdin=None,
            creationflags=_windows_process_flags(),
        )

        session.register_process(project_key, proc)
        session.set_current_project(project_key)
        return f"Started {project['name']} (PID: {proc.pid})."

    except FileNotFoundError as error:
        return f"Could not start {project['name']}. Executable not found: {error}"
    except Exception as error:
        logger.exception("Failed to run project %s", project_key)
        return f"Failed to start {project['name']}: {error}"


# ---------------------------------------------------------
# STOP PROJECT
# ---------------------------------------------------------

def stop_project(project_name: str) -> str:
    project_key = resolve_project_key(project_name)
    if not project_key or project_key not in PROJECTS:
        return f"I don't know the project '{project_name}'."

    project = PROJECTS[project_key]
    proc = session.get_process(project_key)
    if not proc:
        return f"{project['name']} is not currently running under JARVIS."

    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Project %s did not terminate gracefully. Killing process.", project_key)
            proc.kill()
            proc.wait(timeout=5)

        session.unregister_process(project_key)
        return f"Stopped {project['name']}."

    except Exception as error:
        logger.exception("Failed to stop project %s", project_key)
        return f"Failed to stop {project['name']}: {error}"


# ---------------------------------------------------------
# PROJECT STATUS & CURRENT PROJECT
# ---------------------------------------------------------

def get_project_status(project_name: str) -> str:
    project_key = resolve_project_key(project_name)
    if not project_key or project_key not in PROJECTS:
        return f"I don't know the project '{project_name}'."

    project = PROJECTS[project_key]
    editor = project_lifecycle.status(project_key)
    editor_info = (f"registered=True, exists={Path(project['path']).is_dir()}, "
                   f"opened_by_jarvis={bool(editor and editor.opened_by_jarvis)}, "
                   f"editor_open={editor.open if editor else 'unknown'}")
    proc = session.get_process(project_key)
    if not proc:
        return f"{project['name']}: {editor_info}; background process is not running."

    return f"{project['name']} is running (PID: {proc.pid})."


def get_current_project() -> str:
    project_key = session.get_current_project()
    if not project_key:
        return "No project is currently active."

    project = PROJECTS.get(project_key)
    if not project:
        return f"Current project is {project_key}."

    return f"Current project is {project['name']}."


def current_project() -> str:
    return get_current_project()
