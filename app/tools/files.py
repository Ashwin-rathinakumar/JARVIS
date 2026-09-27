import os
import time
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.config.settings import (
    JARVIS_ALLOWED_PATHS,
    BASE_DIR,
    WORKSPACE_DIR,
    MAX_FILE_SEARCH_RESULTS,
    MAX_WRITE_SIZE_KB,
)
from app.brain.permissions import BLOCKED_EXTENSIONS, BLOCKED_DIRECTORIES
from app.utils.logger import logger


def is_path_allowed(target_path: Path) -> bool:
    """
    Check if the target path is inside allowed directories.
    Prevents path traversal outside permitted roots.
    """
    try:
        resolved = target_path.resolve()
        allowed_roots = list(JARVIS_ALLOWED_PATHS)
        # Allow system temp directory for testing/transient files
        allowed_roots.append(Path(tempfile.gettempdir()).resolve())

        # Automatically include registered project paths from PROJECTS
        try:
            from app.config.projects import PROJECTS
            for proj in PROJECTS.values():
                p = proj.get("path")
                if p:
                    allowed_roots.append(Path(p).resolve())
        except Exception:
            pass

        for root in allowed_roots:
            r = root.resolve()
            if resolved == r or r in resolved.parents:
                return True
        return False
    except Exception:
        return False


def _resolve_target_dir(directory: str = ".", is_mutation: bool = False) -> Path:
    """Resolve directory or file path string to Path, defaulting creation/mutation operations to WORKSPACE_DIR."""
    norm = directory.strip().lower() if directory else ""

    if not norm:
        if is_mutation:
            return WORKSPACE_DIR.resolve()
        return BASE_DIR.resolve() if BASE_DIR.exists() else Path.cwd().resolve()

    if norm in {
        ".",
        "current directory",
        "the current directory",
        "this directory",
        "this folder",
        "current folder",
        "the folder",
        "the project",
        "project",
        "the project directory",
        "project directory",
        "project root",
        "the project root",
        "here",
    }:
        if is_mutation:
            return WORKSPACE_DIR.resolve()
        return BASE_DIR.resolve() if BASE_DIR.exists() else Path.cwd().resolve()

    if norm in {"workspace", "the workspace", "workspace folder", "workspace directory"}:
        return WORKSPACE_DIR.resolve()

    target = Path(directory)
    if target.is_absolute():
        return target.resolve()

    # Relative path resolution
    if is_mutation:
        parts = [p.lower() for p in target.parts]
        if parts and parts[0] in {"workspace", WORKSPACE_DIR.name.lower()}:
            return (BASE_DIR / target).resolve()
        else:
            return (WORKSPACE_DIR / target).resolve()

    return (BASE_DIR / target).resolve()


def list_files(directory: str = ".") -> str:
    """List files and directories within a given directory."""
    path = _resolve_target_dir(directory, is_mutation=False)

    if not is_path_allowed(path):
        return f"Access denied: '{directory}' is outside permitted paths."

    if not path.exists():
        return f"Path does not exist: {directory}"

    if not path.is_dir():
        return f"Not a directory: {directory}"

    try:
        items = sorted(list(path.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
        if not items:
            return f"Directory is empty: {directory}"

        results = [f"Contents of {path}:"]
        for item in items[:50]:  # Cap at 50 to avoid flooding output
            if item.is_dir():
                results.append(f"  [DIR]  {item.name}/")
            else:
                size_kb = item.stat().st_size / 1024
                results.append(f"  [FILE] {item.name:<30} ({size_kb:.1f} KB)")

        if len(items) > 50:
            results.append(f"  ... and {len(items) - 50} more items.")

        return "\n".join(results)

    except Exception as error:
        return f"Error listing directory {directory}: {error}"


def find_file(pattern: str, directory: str = ".") -> str:
    """Search for files matching a glob pattern (e.g. '*.py') within a directory."""
    path = _resolve_target_dir(directory, is_mutation=False)

    if not is_path_allowed(path):
        return f"Access denied: '{directory}' is outside permitted paths."

    if not path.exists() or not path.is_dir():
        return f"Directory does not exist: {directory}"

    try:
        matches = list(path.glob(f"**/{pattern}"))
        if not matches:
            return f"No files matching '{pattern}' found in {path.name}."

        results = [f"Matches for '{pattern}' in {path}:"]
        for m in matches[:30]:
            rel_path = m.relative_to(path)
            results.append(f"  - {rel_path}")

        if len(matches) > 30:
            results.append(f"  ... and {len(matches) - 30} more matches.")

        return "\n".join(results)

    except Exception as error:
        return f"Error searching for '{pattern}': {error}"


def search_files(query: str, directory: str = ".", extension: Optional[str] = None) -> str:
    """
    Search files by partial name or extension within permitted roots.
    """
    path = _resolve_target_dir(directory, is_mutation=False)

    if not is_path_allowed(path):
        return f"Access denied: '{directory}' is outside permitted paths."

    if not path.exists() or not path.is_dir():
        return f"Directory does not exist: {directory}"

    query_lower = query.lower().strip()
    ext_lower = extension.lower().strip() if extension else None
    if ext_lower and not ext_lower.startswith("."):
        ext_lower = f".{ext_lower}"

    results = []
    try:
        for root, dirs, files in os.walk(path):
            # Prune noisy directories
            dirs[:] = [d for d in dirs if d.lower() not in {"venv", ".venv", ".git", "node_modules", "__pycache__"}]

            for f in files:
                f_lower = f.lower()
                if ext_lower and not f_lower.endswith(ext_lower):
                    continue
                if query_lower and query_lower not in f_lower:
                    continue

                full_file = Path(root) / f
                rel = full_file.relative_to(path)
                size_kb = full_file.stat().st_size / 1024
                results.append((str(rel), size_kb, str(full_file)))

                if len(results) >= MAX_FILE_SEARCH_RESULTS:
                    break
            if len(results) >= MAX_FILE_SEARCH_RESULTS:
                break

        if not results:
            return f"No files found matching '{query}' in {path.name}."

        lines = [f"Found {len(results)} matching files in {path}:"]
        for rel_name, size_kb, _ in results:
            lines.append(f"  - {rel_name:<35} ({size_kb:.1f} KB)")
        return "\n".join(lines)

    except Exception as error:
        return f"Error during file search: {error}"


def read_text_file(filepath: str, max_lines: int = 100) -> str:
    """Read contents of a text file safely with a line limit."""
    path = _resolve_target_dir(filepath, is_mutation=False)

    if not is_path_allowed(path):
        return f"Access denied: '{filepath}' is outside permitted paths."

    if not path.exists():
        return f"File does not exist: {filepath}"

    if not path.is_file():
        return f"Target is not a file: {filepath}"

    # Check file size (limit to 2MB to prevent memory issues)
    if path.stat().st_size > 2 * 1024 * 1024:
        return f"File is too large to read safely ({path.stat().st_size / 1024 / 1024:.2f} MB)."

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = []
            for i in range(max_lines):
                line = f.readline()
                if not line:
                    break
                lines.append(line.rstrip())

            has_more = f.readline() != ""

        content = "\n".join(lines)
        if has_more:
            content += f"\n\n[... truncated after {max_lines} lines]"

        return f"--- Content of {path.name} ---\n{content}"

    except Exception as error:
        return f"Error reading file {filepath}: {error}"


def create_directory(folder_path: str) -> str:
    """Safely create a new directory inside permitted workspace roots."""
    path = _resolve_target_dir(folder_path, is_mutation=True)

    if not is_path_allowed(path):
        return f"Access denied: '{folder_path}' is outside permitted paths."

    if path.exists():
        return f"Directory already exists: {folder_path}"

    try:
        path.mkdir(parents=True, exist_ok=False)
        logger.info(f"Created directory: {path}")
        return f"Created folder: {path}"
    except Exception as error:
        return f"Unable to create directory '{folder_path}': {error}"


def create_folder(folder_path: str) -> str:
    """Alias for create_directory."""
    return create_directory(folder_path)


def write_text_file(filepath: str, content: str = "", overwrite: bool = False) -> str:
    """
    Safely write a UTF-8 text file. Refuses executable formats and protected paths.
    """
    path = _resolve_target_dir(filepath, is_mutation=True)

    if not is_path_allowed(path):
        return f"Access denied: '{filepath}' is outside permitted paths."

    # Validate blocked extensions
    if path.suffix.lower() in BLOCKED_EXTENSIONS:
        return f"Access denied: Writing executable or script files ({path.suffix}) is strictly blocked."

    # Validate forbidden directories
    parts_lower = [p.lower() for p in path.parts]
    if any(blocked in parts_lower for blocked in BLOCKED_DIRECTORIES):
        return f"Access denied: Writing inside protected directories is prohibited."

    # Validate size limit
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > MAX_WRITE_SIZE_KB * 1024:
        return f"File content exceeds maximum permitted write size ({MAX_WRITE_SIZE_KB} KB)."

    if path.exists() and not overwrite:
        return f"File already exists: {filepath}. Set overwrite=True to replace it."

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"Wrote file: {path} (overwrite={overwrite}, size={len(content_bytes)} bytes)")
        return f"Created file: {path}"

    except Exception as error:
        return f"Unable to write file '{filepath}': {error}"


def create_text_file(filepath: str, content: str = "", overwrite: bool = False) -> str:
    """Alias for write_text_file."""
    return write_text_file(filepath, content, overwrite=overwrite)


def get_file_info(filepath: str) -> str:
    """Get metadata for a specific file or folder."""
    path = _resolve_target_dir(filepath)

    if not is_path_allowed(path):
        return f"Access denied: '{filepath}' is outside permitted paths."

    if not path.exists():
        return f"Path does not exist: {filepath}"

    try:
        stat = path.stat()
        mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
        ctime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_ctime))
        item_type = "Directory" if path.is_dir() else "File"
        size_str = f"{stat.st_size / 1024:.2f} KB" if path.is_file() else "N/A"
        ext = path.suffix if path.is_file() else "N/A"

        return (
            f"Name: {path.name}\n"
            f"Type: {item_type}\n"
            f"Extension: {ext}\n"
            f"Path: {path}\n"
            f"Size: {size_str}\n"
            f"Created: {ctime}\n"
            f"Last Modified: {mtime}\n"
            f"Readable: Yes"
        )
    except Exception as error:
        return f"Error getting info for '{filepath}': {error}"