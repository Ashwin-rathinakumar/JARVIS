# JARVIS

**JARVIS** is a local-first personal AI assistant and agent system running on Windows 11. Designed to operate without requiring paid cloud APIs, JARVIS pairs deterministic local tool routing with local LLM reasoning (via Ollama) to manage local applications, inspect system hardware, run project workflows, persist memories, and search local documents.

---

## Key Features

- **Local-First & Private**: Powered by local Ollama models (`qwen2.5:1.5b` by default). No external cloud API keys required.
- **Deterministic-First Command Router**: Executes known system, application, project, memory, and file commands in <2ms without incurring LLM latency.
- **Robust VS Code & Project Management**:
  - Automatically discovers VS Code via Windows `LOCALAPPDATA`, `ProgramFiles`, or PATH.
  - Supports external project registration, opening, background running, and isolated process stopping.
  - Strictly respects project isolation (e.g. K.E.E.R. integration boundaries).
- **Persistent SQLite Memory**: Stores user preferences and facts across sessions with automatic schema migration and full-text keyword search.
- **Local Document RAG**: Indexes local files (`.txt`, `.md`, `.py`, `.json`) using SQLite FTS5 (BM25 ranking) with grounded citations.
- **Safe Tool Execution**: Structured argument validation with protected process guards and non-destructive file operations.

---

## Architecture

```text
User Input
    │
    ▼
Deterministic Intent Matcher (app/brain/intent.py)
    ├─► Match Found: Centralized Tool Registry (app/tools/registry.py)
    │     ├── Applications: Notepad, Calculator, VS Code, Browser, Paint, Explorer
    │     ├── Projects: Open, Run, Stop, Status, Analyze, Tree, Find TODOs
    │     ├── System: OS, CPU, RAM, Disk space, Hostname, Python version
    │     ├── Files: List, Find, Read, Create folder, Create text file
    │     ├── Memory: Save, Show, Search, Forget (SQLite: data/jarvis.db)
    │     └── Documents RAG: Index, Status, Ask (FTS5 BM25: data/documents.db)
    │
    └─► Ambiguous / Chat: Local LLM Brain (app/brain/llm.py)
          ├── Primary Provider: Ollama (qwen2.5:1.5b)
          └── Optional Provider: Gemini (requires GEMINI_API_KEY)
```

---

## Installation & Setup

### 1. Prerequisites
- **Windows 11** (or Windows 10)
- **Python 3.12+**
- **Ollama** installed and running

### 2. Ollama Setup
1. Download Ollama from [https://ollama.com/download](https://ollama.com/download)
2. Start Ollama and pull the default model:
   ```powershell
   ollama pull qwen2.5:1.5b
   ```

### 3. Clone / Open JARVIS
```powershell
cd C:\JARVIS
```

### 4. Activate Virtual Environment & Install Dependencies
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## How to Run

Launch the interactive terminal interface:

```powershell
.\venv\Scripts\python.exe -m app.main
```

### Startup Banner:
```text
=======================================================
             JARVIS v0.3
       Local-First Personal AI Assistant
=======================================================
Provider : Ollama
Model    : qwen2.5:1.5b
Status   : Ready
Type 'help' for commands or 'exit' to shut down.
=======================================================

YOU > 
```

---

## Command Reference

### Applications
| Command | Action |
|---|---|
| `open calculator` | Launches Windows Calculator |
| `open notepad` | Launches Notepad |
| `open vscode` | Launches Visual Studio Code |
| `open browser` | Launches default browser |
| `open paint` | Launches MS Paint |
| `close calculator` | Closes Calculator process |

### Projects
| Command | Action |
|---|---|
| `list projects` | Lists all registered projects |
| `open jarvis project` | Opens JARVIS directory in VS Code |
| `open keer project` | Opens external K.E.E.R. directory in VS Code |
| `current project` | Displays active project context |
| `run project` | Starts background run command for project |
| `stop project` | Terminates project process started by JARVIS |
| `project status` | Displays path and running state of active project |
| `analyze current project` | Summarizes file types, size, git status, and configs |
| `project tree` | Displays visual folder hierarchy |
| `find todos` | Scans project source files for `TODO` and `FIXME` comments |

### System Diagnostics
| Command | Action |
|---|---|
| `system info` | Displays OS, CPU architecture, disk space, and Python version |
| `cpu info` | Displays processor specs and logical core counts |
| `memory info` | Displays RAM load, total, used, and available memory |
| `disk info` | Displays drive capacity, usage percentage, and free space |
| `hostname` | Shows machine network node name |

### Persistent Memory
| Command | Action |
|---|---|
| `remember that <info>` | Saves explicit fact to SQLite database |
| `show memories` | Displays all saved memories |
| `search memories <term>` | Searches memory records by keyword |
| `forget memory <id>` | Deletes memory entry by ID |

### Local Document RAG
| Command | Action |
|---|---|
| `index documents` | Chunks and indexes all files in `data/documents/` |
| `document status` | Displays count of indexed documents and chunks |
| `ask documents <query>` | Retrieves relevant chunks and synthesizes answer with citations |

### General / Utilities
| Command | Action |
|---|---|
| `status` | Live diagnostic check of LLM, Database, RAG, and processes |
| `help` | Interactive capabilities catalog |
| `clear` | Clears terminal screen |
| `exit` / `quit` | Gracefully shuts down JARVIS |

---

## Project Configuration

Projects are registered in [`app/config/projects.py`](file:///C:/JARVIS/app/config/projects.py):

```python
PROJECTS = {
    "jarvis": {
        "name": "JARVIS",
        "path": r"C:\JARVIS",
        "run_command": r".\venv\Scripts\python.exe -m app.main",
        "stop_command": None,
    },
    "keer": {
        "name": "K.E.E.R.",
        "path": r"C:\Users\Ashwin Rathinakumar\Downloads\Forge (1)\keer",
        "run_command": None,
        "stop_command": None,
    },
}
```

---

## Testing

Run the automated test suite with Python's built-in test runner:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

---

## Troubleshooting

- **Ollama Offline**: If Ollama is not running, JARVIS displays `Status: Ready (Local tools only - LLM offline)`. All deterministic tools (`open ...`, `remember`, `system info`, `projects`) remain 100% functional. To enable reasoning, start Ollama via `ollama serve`.
- **VS Code Discovery**: If VS Code is not detected automatically, set `DEFAULT_EDITOR` in `.env` to the full path of `Code.exe`.
- **Database Location**: SQLite database is stored at `data/jarvis.db`. Schema migrations run automatically upon startup.
