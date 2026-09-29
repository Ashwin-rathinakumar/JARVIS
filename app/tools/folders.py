"""Scoped folder navigation and bounded project stack metadata."""
import json
import os
import subprocess
from pathlib import Path

from app.tools.git import resolve_git_project, GitFailure
from app.tools.files import is_path_allowed


def _folder(project_name, folder):
    key, root = resolve_git_project(project_name)
    if not isinstance(folder, str) or any(c in folder for c in ":;&|`$<>\r\n\0"):
        raise GitFailure("INVALID_PATH", "Specify a relative folder inside the project.")
    relative = Path(folder)
    if relative.is_absolute() or ".." in relative.parts:
        raise GitFailure("INVALID_PATH", "Folder must remain inside the selected project.")
    target = (root / relative).resolve()
    if folder.lower() in {"backend", "server", "api"} and not target.is_dir():
        matches = [p for p in (root / "backend", root / "server", root / "api") if p.is_dir()]
        if not matches and (root / "requirements.txt").is_file():
            matches = [root]
        if len(matches) != 1:
            raise GitFailure("AMBIGUOUS_FOLDER", "I couldn't identify one backend folder. Specify its relative folder name.")
        target = matches[0].resolve()
    if not target.is_relative_to(root) or not target.is_dir() or not is_path_allowed(target):
        raise GitFailure("INVALID_PATH", "That folder is missing or outside the project.")
    return key, target


def project_folder(project_name: str, folder: str = "backend"):
    try:
        key, target = _folder(project_name, folder)
        return {"success": True, "project": key, "path": str(target), "message": f"The {folder} folder is {target}."}
    except GitFailure as error:
        return {"success": False, "error_code": error.code, "message": error.message}


def open_folder(path: str):
    if not isinstance(path, str) or any(c in path for c in ";&|`$<>\r\n\0"):
        return {"success": False, "message": "Invalid folder path."}
    target = Path(path).resolve()
    downloads = (Path.home() / "Downloads").resolve()
    if not target.is_dir() or not (is_path_allowed(target) or target == downloads):
        return {"success": False, "message": "Folder is missing or outside allowed locations."}
    try:
        if os.name != "nt":
            return {"success": False, "message": "Folder opening is available on Windows only."}
        subprocess.Popen([str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"), str(target)],
                         shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"success": True, "path": str(target), "message": f"Opened folder {target}."}
    except OSError:
        return {"success": False, "message": "Windows could not open that folder."}


def open_project_folder(project_name: str, folder: str = "backend"):
    result = project_folder(project_name, folder)
    if not result["success"]:
        return result
    opened = open_folder(result["path"])
    return dict(opened, project=result["project"])


def project_overview(project_name: str):
    try:
        key, root = resolve_git_project(project_name)
        stack = set()
        for relative in (".", "backend", "server", "api", "frontend"):
            folder = (root / relative).resolve()
            if not folder.is_relative_to(root):
                continue
            for filename in ("requirements.txt", "pyproject.toml", "package.json"):
                file = folder / filename
                if not file.resolve().is_relative_to(root) or not file.is_file() or file.stat().st_size > 128000:
                    continue
                text = file.read_text(encoding="utf-8", errors="replace").lower()
                stack.add("Node.js / JavaScript" if filename == "package.json" else "Python")
                for name in ("fastapi", "flask", "django", "express", "react", "next", "typescript"):
                    if name in text:
                        stack.add(name)
        result = sorted(stack)
        return {"success": True, "project": key, "stack": result,
                "message": f"{key} declares {', '.join(result)} in its project manifests." if result else "No recognized stack manifests were found; the backend technology is unverified."}
    except (GitFailure, OSError) as error:
        return {"success": False, "message": error.message if isinstance(error, GitFailure) else "Unable to inspect project manifests."}
