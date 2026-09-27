from typing import Optional, Dict, Any

PROJECTS: Dict[str, Dict[str, Any]] = {
    "jarvis": {
        "name": "JARVIS",
        "path": r"C:\JARVIS",
        "run_command": [r".\venv\Scripts\python.exe", "-m", "app.main"],
        "stop_command": None,
        "description": "Local-first personal AI assistant",
    },
    "keer": {
    "name": "K.E.E.R.",
    "path": r"C:\Users\Ashwin Rathinakumar\Downloads\Forge (1)\keer",
    "run_command": [
        "python",
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ],
},
}

PROJECT_ALIASES: Dict[str, str] = {
    "j.a.r.v.i.s": "jarvis",
    "jarvis project": "jarvis",
    "my jarvis project": "jarvis",
    "jarvis": "jarvis",
    "k.e.e.r": "keer",
    "k.e.e.r.": "keer",
    "keer project": "keer",
    "my keer project": "keer",
    "keer": "keer",
}


def resolve_project_key(name: str) -> Optional[str]:
    """Resolve a user-provided project name or alias to its canonical project key."""
    if not name:
        return None
    cleaned = name.lower().strip()
    if cleaned in PROJECTS:
        return cleaned
    if cleaned in PROJECT_ALIASES:
        return PROJECT_ALIASES[cleaned]
    # Check if any alias is contained
    for alias, key in PROJECT_ALIASES.items():
        if alias in cleaned:
            return key
    return None