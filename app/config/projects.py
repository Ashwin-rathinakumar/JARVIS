from typing import Optional, Dict, Any

PROJECTS: Dict[str, Dict[str, Any]] = {
    "jarvis": {
        "name": "JARVIS",
        "path": r"C:\JARVIS",
        "aliases": ["jarvis", "j.a.r.v.i.s", "jarvis assistant"],
        "run_command": [
            r".\venv\Scripts\python.exe",
            "-m",
            "app.main",
        ],
        "stop_command": None,
        "description": "Local-first personal AI assistant",
    },
    "keer": {
        "name": "K.E.E.R.",
        "path": r"C:\Users\Ashwin Rathinakumar\Downloads\Forge (1)\keer",
        "aliases": [
            "keer", "k.e.e.r", "k e e r", "k-e-e-r", "forge",
            "key", "ker", "k-e-r", "k e r", "ker er",
        ],
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
        "stop_command": None,
        "description": "K.E.E.R. project",
    },
    "sentinel": {
        "name": "Sentinel AI",
        "path": r"C:\Users\Ashwin Rathinakumar\Downloads\SenitalAI_complete_modified_project\SenitalAI",
        "aliases": ["sentinel", "sentinel ai", "sentinal ai", "senital ai", "senitalai"],
        "run_command": None,
        "test_command": ["python", "-m", "pytest", "tests", "-q"],
        "test_timeout": 120,
        "stop_command": None,
        "description": "Sentinel AI project",
    },
    "streetlight": {
        "name": "Streetlight Fault Reporting System",
        "path": r"C:\Users\Ashwin Rathinakumar\streetlight-backend",
        "aliases": ["streetlight", "streetlight system", "streetlight backend", "streetlight fault reporting system"],
        "run_command": None,
        "stop_command": None,
        "description": "Streetlight management project",
    },
}

PROJECT_ALIASES: Dict[str, str] = {
    "j.a.r.v.i.s": "jarvis",
    "jarvis": "jarvis",
    "k.e.e.r": "keer",
    "k.e.e.r.": "keer",
    "keer": "keer",
    "forge": "keer",
    "key": "keer",
    "ker": "keer",
    "k-e-r": "keer",
    "k e r": "keer",
    "sentinel": "sentinel",
    "sentinel ai": "sentinel",
    "streetlight": "streetlight",
    "streetlight system": "streetlight",
}


def resolve_project_key(name: str) -> Optional[str]:
    """Resolve a user-provided project name or alias to its canonical project key via ProjectResolver."""
    if not name:
        return None
    from app.projects.resolver import project_resolver
    res = project_resolver.resolve(name)
    if res.matched:
        return res.project_key
    return None
