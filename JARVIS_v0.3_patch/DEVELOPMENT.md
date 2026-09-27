# JARVIS v0.3 Development Update

## Context & Safety Patch

- Added `app/brain/context.py` to assemble compact conversational context.
- Normal LLM chat now retrieves relevant explicit SQLite memories automatically.
- Added lightweight memory relevance scoring without adding embedding dependencies yet.
- Updated project launching to prefer structured argument lists with `shell=False`.
- VS Code launches now detach/suppress child output to avoid terminal log spam.
- Added `.gitignore` and `.env.example`; secrets, virtual environments, runtime databases, logs, caches, and archives are excluded from version control.
- Updated runtime version to v0.3.
- Made project-management tests host-independent by mocking editor/path discovery.
- Test suite: 43 tests passed.

---

# JARVIS Development Worklog

## Overview
This document records the incremental upgrade of **JARVIS** from v0.1 to **v0.2**, detailing bug fixes, architectural modularization, tool expansions, and verification results.

---

## 1. Resolved Issues & Bug Fixes

### A. Project Management & VS Code Discovery (`open keer project`)
- **Symptoms**: Running `open keer project` crashed or threw `[WinError 2] The system cannot find the file specified`. Furthermore, importing `app.brain.router` crashed due to a syntax typo `ddef open_project` and missing imports `shutil`, `os` in `app/tools/projects.py`.
- **Root Causes**:
  1. Syntax error `ddef` on line 26 of `app/tools/projects.py`.
  2. `shutil` and `os` used without being imported.
  3. `run_project` was imported in `router.py` and `registry.py` but never defined in `projects.py`.
  4. On Windows, `shutil.which("code")` often resolves to `code.CMD` or a shell script wrapper. Executing `.cmd` directly via `subprocess.Popen(..., shell=False)` causes Windows WinError 2.
- **Resolution**:
  - Implemented `find_vscode_launcher()`: searches `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe`, `%ProgramFiles%`, and falls back to `shutil.which` with safe Windows shell invocation.
  - Implemented `run_project()` and `stop_project()` with process registration in `SessionState` to ensure JARVIS only stops tasks it initiated.
  - Preserved the external K.E.E.R. project directory (`C:\Users\Ashwin Rathinakumar\Downloads\Forge (1)\keer`) strictly as an external entry without modifying or importing K.E.E.R. code.

### B. Conflicting Session State Modules
- **Symptoms**: `app/brain/state.py` and `app/state/session.py` both defined distinct `SessionState` classes with divergent properties.
- **Resolution**: Unified state into `app/state/session.py` tracking active project, spawned processes, session ID, turn history, and recent actions. Added backward-compatible alias export in `app/brain/state.py`.

### C. Deterministic-First Command Classification
- **Symptoms**: `app/brain/intent.py` made a synchronous HTTP POST request to Ollama for every input string. If Ollama was offline or under load, trivial commands like `system info` or `open calculator` timed out or failed.
- **Resolution**: Implemented `classify_intent_deterministic()` executing regex/prefix patterns in <1ms for applications, projects, system, memory, files, and RAG commands. Ollama is called only for ambiguous queries with a 5-second fallback timeout.

---

## 2. Implemented Features

### Local LLM Provider Abstraction
- Defined abstract `BaseLLMProvider` in `app/brain/providers/base.py`.
- Standardized `OllamaProvider` as primary local model (`qwen2.5:1.5b`), supporting conversation history injection and live health checks.
- Kept `GeminiProvider` as an optional fallback without requiring cloud API keys for startup.

### SQLite Persistent Memory
- Upgraded `app/memory/database.py` with automatic schema migration (`category`, `updated_at`, `metadata` columns added via `PRAGMA table_info`).
- Preserved existing memory entries in `data/jarvis.db`.
- Added search (`search memories <query>`) and removal (`forget memory <id>`).

### Local Document RAG (SQLite FTS5 BM25)
- Document loader supporting `.txt`, `.md`, `.py`, `.json` from `data/documents/`.
- Text chunker with sliding character window and overlap.
- Persistent FTS5 BM25 indexer in `data/documents.db`.
- Grounded query engine (`ask documents <query>`) formatting retrieved chunks with document citations.

### System, File & Analysis Tooling
- System diagnostics: OS, CPU cores, RAM load, Disk free/total, Hostname, Python version.
- Safe file tools: list directory, pattern find, safe text read with 100-line cap, folder/file creation with overwrite protection.
- Project inspection: file type distributions, total size, git/venv status, directory tree, and TODO scanner.

### Dynamic Health & Help System
- `status`: real-time diagnostic reporting Ollama connectivity, SQLite memory count, Document RAG chunks, active project, and background tasks.
- `help`: dynamically generated catalog grouped by tool category directly from `TOOL_REGISTRY`.

---

## 3. Test Coverage & Verification

Automated test suite (`tests/`):
- `tests/test_projects.py`: Alias matching, launcher discovery, mocked project open/run/stop.
- `tests/test_intent.py`: Deterministic intent matching across all command groups.
- `tests/test_database.py`: Safe migration, CRUD memory operations, formatting.
- `tests/test_tools.py`: System diagnostics, safe file operations, application normalization, analysis tools.
- `tests/test_session.py`: Bounded history, process registration, context switching.
- `tests/test_rag.py`: Chunker, FTS5 BM25 indexing and querying.
- `tests/test_router.py`: Command routing and chat fallback.
- `tests/test_provider.py`: Ollama timeout, connection error recovery, and Gemini fallback.

**Test Run Summary**:
```text
Ran 39 tests in 3.151s
OK (39 passed, 0 failures, 0 errors)
```

---

## 4. Architecture Tree

```text
C:\JARVIS
├── .env
├── README.md
├── DEVELOPMENT.md
├── requirements.txt
├── data/
│   ├── jarvis.db              # SQLite persistent memories
│   ├── documents.db           # SQLite FTS5 document index
│   └── documents/             # Target directory for local document RAG
├── logs/
│   └── jarvis.log             # Rotating diagnostic logs
├── app/
│   ├── main.py                # Terminal REPL, banner, status, help
│   ├── brain/
│   │   ├── llm.py             # JarvisBrain provider coordinator
│   │   ├── intent.py          # Deterministic matcher + LLM fallback
│   │   ├── router.py          # Command execution dispatcher
│   │   ├── prompts.py         # System prompt
│   │   ├── permissions.py     # Tool permission classifications
│   │   ├── state.py           # Re-export for backward compatibility
│   │   └── providers/
│   │       ├── base.py        # BaseLLMProvider interface
│   │       ├── ollama.py      # Local Ollama client
│   │       └── gemini.py      # Optional Gemini provider
│   ├── config/
│   │   ├── settings.py        # Centralized settings & path config
│   │   └── projects.py        # Project registry (JARVIS, KEER)
│   ├── memory/
│   │   └── database.py        # SQLite database manager
│   ├── retrieval/
│   │   ├── loader.py          # Document loader
│   │   ├── chunker.py         # Sliding window chunker
│   │   ├── indexer.py         # SQLite FTS5 BM25 storage
│   │   └── rag.py             # Grounded retrieval & Q&A
│   ├── state/
│   │   └── session.py         # Centralized SessionState
│   ├── tools/
│   │   ├── apps.py            # App launcher (Notepad, Calc, Code, etc.)
│   │   ├── projects.py        # Project management & Code launcher
│   │   ├── system.py          # Hardware & OS diagnostics
│   │   ├── files.py           # Safe file operations
│   │   ├── analysis.py        # Project structure & TODO scanner
│   │   └── registry.py        # Centralized tool registry & ToolResult
│   └── utils/
│       └── logger.py          # File and console logger
└── tests/
    ├── test_projects.py
    ├── test_intent.py
    ├── test_database.py
    ├── test_tools.py
    ├── test_session.py
    ├── test_rag.py
    ├── test_router.py
    └── test_provider.py
```

---

## 5. Manual Instructions for User

1. **Ollama Service**: Ensure Ollama is running in the background (`ollama serve`). If Ollama is not active, JARVIS will still start and execute all deterministic local tools seamlessly.
2. **Local Model**: Ensure `qwen2.5:1.5b` is downloaded (`ollama pull qwen2.5:1.5b`).
3. **External Projects**: To register any new personal projects, add an entry to `PROJECTS` in `app/config/projects.py`.
