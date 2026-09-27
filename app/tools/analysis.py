import os
from pathlib import Path
from typing import Dict, List, Optional

from app.config.projects import PROJECTS, resolve_project_key
from app.state.session import session


def _resolve_target_path(target: Optional[str] = None) -> Optional[Path]:
    """Resolve a target name or use current project / current directory."""
    if not target:
        key = session.get_current_project()
        if key and key in PROJECTS:
            return Path(PROJECTS[key]["path"])
        return Path.cwd()

    # Check if target matches a project
    key = resolve_project_key(target)
    if key and key in PROJECTS:
        return Path(PROJECTS[key]["path"])

    p = Path(target).resolve()
    if p.exists() and p.is_dir():
        return p

    return None


def analyze_project(target: Optional[str] = None) -> str:
    """Analyze a project folder, summarizing file types, size, structure, and configuration."""
    path = _resolve_target_path(target)
    if not path or not path.exists():
        return f"Project directory not found: {target or 'current'}"

    ext_counts: Dict[str, int] = {}
    total_files = 0
    total_dirs = 0
    total_size_bytes = 0

    ignored_dirs = {".git", "venv", "__pycache__", "node_modules", ".idea", ".vscode", "dist", "build"}

    for root, dirs, files in os.walk(path):
        # Filter directories in-place
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
        total_dirs += len(dirs)

        for f in files:
            total_files += 1
            file_path = Path(root) / f
            try:
                total_size_bytes += file_path.stat().st_size
            except Exception:
                pass
            ext = file_path.suffix.lower() or "(no extension)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

    # Key project indicators
    has_git = (path / ".git").exists()
    has_venv = (path / "venv").exists() or (path / ".venv").exists()
    has_readme = any((path / f).exists() for f in ["README.md", "README.txt", "README"])
    has_requirements = (path / "requirements.txt").exists() or (path / "pyproject.toml").exists()

    top_exts = sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:6]
    ext_str = ", ".join(f"{ext}: {cnt}" for ext, cnt in top_exts)

    report = [
        f"--- Project Analysis: {path.name} ---",
        f"Location: {path}",
        f"Total Files: {total_files} | Subdirectories: {total_dirs}",
        f"Total Size: {total_size_bytes / (1024 * 1024):.2f} MB",
        f"Primary File Types: {ext_str or 'None'}",
        f"Git Repository: {'Yes' if has_git else 'No'}",
        f"Virtual Environment: {'Yes' if has_venv else 'No'}",
        f"Documentation (README): {'Yes' if has_readme else 'No'}",
        f"Package Config: {'Yes' if has_requirements else 'No'}",
    ]

    return "\n".join(report)


def find_todos(target: Optional[str] = None) -> str:
    """Find TODO and FIXME tags across project source files."""
    path = _resolve_target_path(target)
    if not path or not path.exists():
        return f"Project directory not found: {target or 'current'}"

    ignored_dirs = {".git", "venv", "__pycache__", "node_modules", "dist", "build"}
    code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".md", ".json", ".sh", ".ps1"}

    findings: List[str] = []

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]

        for f in files:
            file_path = Path(root) / f
            if file_path.suffix.lower() in code_exts:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as file_obj:
                        for line_num, line in enumerate(file_obj, start=1):
                            line_upper = line.upper()
                            if "TODO" in line_upper or "FIXME" in line_upper:
                                rel = file_path.relative_to(path)
                                findings.append(f"  {rel}:{line_num} -> {line.strip()[:80]}")
                                if len(findings) >= 25:
                                    break
                except Exception:
                    pass

        if len(findings) >= 25:
            break

    if not findings:
        return f"No TODO or FIXME comments found in {path.name}."

    header = f"Found TODO/FIXME markers in {path.name} (capped at 25):"
    return header + "\n" + "\n".join(findings)


def get_project_tree(target: Optional[str] = None, max_depth: int = 2) -> str:
    """Render a visual directory tree up to max_depth levels."""
    path = _resolve_target_path(target)
    if not path or not path.exists():
        return f"Project directory not found: {target or 'current'}"

    ignored = {".git", "venv", "__pycache__", "node_modules"}
    lines = [f"{path.name}/"]

    def _walk(curr: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(list(curr.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
            filtered = [e for e in entries if e.name not in ignored and not e.name.startswith(".")]
            for idx, entry in enumerate(filtered[:20]):
                is_last = (idx == len(filtered) - 1)
                connector = "└── " if is_last else "├── "
                sub_prefix = "    " if is_last else "│   "
                if entry.is_dir():
                    lines.append(f"{prefix}{connector}{entry.name}/")
                    _walk(entry, prefix + sub_prefix, depth + 1)
                else:
                    lines.append(f"{prefix}{connector}{entry.name}")
        except Exception:
            pass

    _walk(path, "", 1)
    return "\n".join(lines)
