"""Bounded semantic project-inspection tools for controlled agent runs."""
import subprocess
from pathlib import Path
from typing import Any, Dict

from app.config.projects import PROJECTS, resolve_project_key
from app.config.settings import JARVIS_AGENT_OBSERVATION_CHARS, MAX_FILE_SEARCH_RESULTS


def _project(project: str):
    key = resolve_project_key(project)
    if not key:
        return None, None, {"success": False, "message": f"Unknown registered project '{project}'.", "error_code": "UNKNOWN_PROJECT"}
    return key, Path(PROJECTS[key]["path"]).resolve(), None


def _safe_path(root: Path, relative_path: str):
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def list_project_files(project: str, relative_path: str = ".") -> Dict[str, Any]:
    key, root, error = _project(project)
    if error:
        return error
    target = _safe_path(root, relative_path)
    if target is None or not target.is_dir():
        return {"success": False, "message": "Project path is unsafe or is not a directory.", "error_code": "UNSAFE_PATH"}
    items = sorted(str(item.relative_to(root)) for item in target.iterdir())[:MAX_FILE_SEARCH_RESULTS]
    return {"success": True, "message": "\n".join(items) or "No files found.", "data": {"project": key, "files": items}}


def read_project_file(project: str, relative_path: str, max_lines: int = 200) -> Dict[str, Any]:
    key, root, error = _project(project)
    if error:
        return error
    target = _safe_path(root, relative_path)
    if target is None or not target.is_file() or target.stat().st_size > 512 * 1024:
        return {"success": False, "message": "Project file is unsafe, missing, or too large.", "error_code": "UNSAFE_PATH"}
    content = "".join(target.read_text(encoding="utf-8", errors="replace").splitlines(True)[:max(1, min(max_lines, 500))])
    return {"success": True, "message": content[:JARVIS_AGENT_OBSERVATION_CHARS], "data": {"project": key, "path": relative_path}}


def search_project_text(project: str, query: str) -> Dict[str, Any]:
    key, root, error = _project(project)
    if error:
        return error
    if not query or len(query) > 200:
        return {"success": False, "message": "Search query is empty or too long.", "error_code": "INVALID_ARGUMENTS"}
    matches = []
    for path in root.rglob("*"):
        if len(matches) >= MAX_FILE_SEARCH_RESULTS or not path.is_file() or path.stat().st_size > 512 * 1024:
            continue
        try:
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if query.lower() in line.lower():
                    matches.append(f"{path.relative_to(root)}:{number}: {line[:300]}")
                    if len(matches) >= MAX_FILE_SEARCH_RESULTS:
                        break
        except OSError:
            continue
    return {"success": True, "message": "\n".join(matches) or "No matches found.", "data": {"project": key, "matches": matches}}


def run_project_tests(project: str) -> Dict[str, Any]:
    key, root, error = _project(project)
    if error:
        return error
    config = PROJECTS[key]
    command = config.get("test_command")
    if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
        return {"success": False, "message": f"No trusted test command is registered for {config['name']}.", "error_code": "TEST_COMMAND_UNAVAILABLE"}
    timeout = min(int(config.get("test_timeout", 120)), 300)
    try:
        result = subprocess.run(command, cwd=str(root), capture_output=True, text=True, timeout=timeout, shell=False)
        output = (result.stdout + "\n" + result.stderr).strip()[-JARVIS_AGENT_OBSERVATION_CHARS:]
        return {"success": result.returncode == 0, "message": f"Tests exited with code {result.returncode}.\n{output}",
                "data": {"project": key, "exit_code": result.returncode}, "error_code": None if result.returncode == 0 else "TESTS_FAILED"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"Project tests timed out after {timeout} seconds.", "error_code": "TEST_TIMEOUT"}
