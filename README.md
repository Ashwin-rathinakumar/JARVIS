# JARVIS

**JARVIS** is a modular, local-first personal AI assistant and agent system running on Windows 11. Designed to operate without requiring paid cloud APIs, JARVIS combines deterministic local tool routing with local LLM reasoning (via Ollama) to manage local applications, inspect system hardware, plan and execute multi-step workflows safely, persist memories, search local documents via hybrid RAG, and serve a unified Core REST API.

---

## Key Features

### Contextual reasoning (v0.9)

JARVIS supports optional, provider-neutral semantic reasoning. Clear
commands and contextual references use local deterministic routes; with a configured
model, additional natural variants use a validated JSON
decision before the existing planner and permissions. Project, repository, folder
and recent-result context stay scoped to the conversation. Text and voice share
the same pipeline, including questions and corrections during pending confirmation.

Try “Open Streetlight”, “Check its git status”, “What does that mean?”, and
“Commit those changes as fix API”. The commit still requires confirmation.
See [contextual reasoning and the manual test conversation](docs/CONTEXTUAL_REASONING.md)
for provider behavior, supported capabilities and safety limits.

### Wake session (v0.8.1)

The optional transcript wake adapter listens in short microphone windows and matches configured phrases locally after Faster-Whisper transcription. Enable it in `.env` with `JARVIS_WAKE_PROVIDER=transcript`, then start `python -m app.main --runtime`. Say “Hey JARVIS” (or “Hey JARVIS, open Sentinel AI”). JARVIS acknowledges and listens for follow-up commands for ten seconds after each turn. “Run its tests” uses the project from the current wake session and requests confirmation before executing the registered test command. The window then returns to idle; the next command needs a wake phrase. Push-to-talk (`python -m app.voice`) remains available.

`JARVIS_WAKE_PHRASES`, `JARVIS_WAKE_WINDOW_SECONDS`, and `JARVIS_FOLLOW_UP_SECONDS` tune the phrases and timing. This adapter runs STT on each listening window, so CPU usage and response latency depend on the local model. Wake detection and live microphone behavior still need validation on the Windows machine; the automated tests use synthetic transcripts. The default wake provider remains disabled until explicitly enabled.

- **Local-First & Private**: Powered by local Ollama models (`qwen2.5:1.5b` for reasoning and `nomic-embed-text` for embeddings). No external cloud API keys required.
- **Phase 3 Agentic Action & Permission Layer**:
  - **Bounded Task Planning**: Converts complex goals into structured, validated multi-step `ActionPlan` models bounded by `MAX_PLAN_STEPS` (6).
  - **Deterministic Permission Engine**: Evaluates every step against explicit risk levels (`READ_ONLY`, `LOW`, `MEDIUM`, `BLOCKED`).
  - **Explicit Confirmation Flow**: Medium-risk actions (file writes, directory creation, background processes) pause for confirmation via CLI (`[y/N]`) or REST token.
  - **Zero Raw Shell Execution**: Prohibits raw shell execution (`cmd.exe`, `powershell`, `os.system`, `eval()`) and strictly blocks writing executable scripts (`.ps1`, `.bat`, `.cmd`, `.exe`, `.vbs`).
  - **Persistent Action Auditing**: Records all action executions, permission decisions, and sanitized arguments in SQLite (`data/jarvis.db`).
- **Central Jarvis Orchestrator**: Unified request processing layer (`app/brain/orchestrator.py`) supporting structured Pydantic responses, session memory bounding, deterministic tool execution, and agent planning.
- **FastAPI Core API**: Built-in REST server providing `/health`, `/api/chat`, `/api/plan`, `/api/actions`, `/api/tools`, `/api/memory`, and `/api/session/{session_id}` endpoints.
- **Deterministic-First Command Router**: Executes known system, application, project, memory, and file commands in <2ms without incurring LLM latency.
- **Project Intelligence & VS Code Launching**:
  - Search, inspect, and open local projects in VS Code.
  - Deep project inspection (technology stack, git status, file structure, key files).
- **Persistent SQLite Memory**: Stores user preferences and facts across sessions with automatic schema migration and keyword search.
- **Local Document RAG & Hybrid Retrieval**:
  - Lexical full-text search with SQLite FTS5 (BM25 ranking).
  - Semantic vector search with Ollama embeddings (`nomic-embed-text`) and pure-Python cosine similarity.
  - Reciprocal Rank Fusion (RRF with $k=60$) combining lexical and semantic rankings.
  - Text-based PDF ingestion via `pypdf`.

---

## Architecture

```text
User (CLI / Desktop / REST Client)
    │
    ▼
JARVIS Core API / CLI Entrypoint (app/main.py, app/api/server.py)
    │
    ▼
Jarvis Orchestrator (app/brain/orchestrator.py)
    ├─► Session Manager (app/state/session.py)
    ├─► Intent Router (app/brain/intent.py)
    ├─► Jarvis Planner & Validator (app/brain/planner.py)
    ├─► Permission Engine (app/brain/permissions.py)
    ├─► Confirmation Manager (app/brain/confirmation.py)
    ├─► Agent Executor (app/agent/executor.py)
    │
    ├─► Tool Registry Execution (app/tools/registry.py)
    │     ├── Applications: Notepad, Calculator, VS Code, Browser, Paint, Explorer
    │     ├── Projects: Search, Inspect, Open, Run, Stop, Status, Tree, Find TODOs
    │     ├── System: OS, CPU, RAM, Disk space, Hostname, Python version
    │     ├── Files: Search, Info, List, Read, Create folder, Write file (Path-Restricted)
    │     ├── Memory: Save, Show, Search, Forget (SQLite: data/jarvis.db)
    │     ├── Document RAG: Index, Status, Ask (FTS5 BM25 + nomic-embed-text: data/documents.db)
    │     └── Action Auditing: History, Query (SQLite: data/jarvis.db)
    │
    └─► LLM Reasoning Brain (app/brain/llm.py)
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
2. Start Ollama and pull the required models:
   ```powershell
   ollama pull qwen2.5:1.5b
   ollama pull nomic-embed-text
   ```

### 3. Setup Project & Dependencies
```powershell
cd C:\JARVIS
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## How to Run

### 1. Interactive CLI Mode (Default)
```powershell
.\venv\Scripts\python.exe -m app.main
```

### 2. FastAPI Server Mode
```powershell
.\venv\Scripts\python.exe -m app.main --server --port 8000
```
Or via Uvicorn directly:
```powershell
uvicorn app.api.server:app --host 127.0.0.1 --port 8000
```

---

## REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | System diagnostics, LLM connectivity, active model, and memory counts |
| `POST` | `/api/chat` | Send conversational message or command (`{"message": "...", "session_id": "..."}`) |
| `POST` | `/api/plan` | Propose and validate an ActionPlan without executing (`{"goal": "..."}`) |
| `GET` | `/api/actions` | Query recent action audit history (`limit=50`) |
| `GET` | `/api/actions/{id}` | Inspect a specific pending confirmation token |
| `POST` | `/api/actions/{id}/confirm` | Confirm and resume a paused action plan |
| `POST` | `/api/actions/{id}/cancel` | Cancel a paused action plan |
| `GET` | `/api/tools` | List all registered tools, descriptions, and risk levels |
| `GET` | `/api/memory` | Query persistent memories (params: `q`, `category`, `limit`) |
| `POST` | `/api/memory` | Store new memory (`{"content": "...", "category": "..."}`) |
| `DELETE` | `/api/session/{session_id}` | Reset conversational history for a given session |

---

## Testing

Run the full automated test suite in the repository's virtual environment:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

## Local voice runtime (v0.4)

```powershell
.\venv\Scripts\python.exe -m app.main --voice
```

Use ENTER to start and stop each utterance. Wait for the response before recording
again. Use `scripts/verify_voice_session.ps1` for the continuous eight-command
microphone acceptance test. `JARVIS_LOG_LEVEL=DEBUG` enables the project pipeline
diagnostics in `logs/jarvis.log`.

Speech runs sequentially in bounded, one-utterance workers. A worker must acknowledge
its completed utterance; failures appear in the terminal and log. The assistant and
Whisper model stay alive across utterances. An enabled but unavailable speech backend
never silently becomes a mock.

`Open <registered project>` and `Close <registered project>` use the existing
permission/executor pipeline. Editors launched by JARVIS use a separate VS Code
user-data directory per instance in `data/editor-sessions/`. This provides ownership
evidence for graceful window closing, but means those windows have separate settings
and workspace-trust state. Their first launch may show normal VS Code setup/trust UI.
Do not remove these directories while an editor is open or has unsaved recovery data.

Closing verifies the tracked process creation time and exact private profile, then
requests a normal Windows window close. It never kills VS Code. Untracked windows,
multiple windows in one tracked instance, uncertain ownership, and unsaved-work
dialogs result in an explicit refusal or incomplete-close response. Tracking lasts
for the current JARVIS process; an editor from an earlier session is not adopted.

Opening waits for an identifiable window. VS Code updates can block new isolated
instances even while existing editor windows continue working. Finish the update
before retrying. An exited or unready launcher is reported as a failure.

See `V04_RUNTIME_REPORT.md` for verification results and remaining limitations.

## Safe Git/GitHub project workflows

Say `Check the git status of the Streetlight project`, then
`Commit the changes as fix complaint endpoint`, then `Push it to GitHub`.
Git commands retain the selected project within the conversation. Status is
read-only; commit, pull and publication require the existing confirmation flow.
Reply `yes` to approve or `no` to cancel.

`Upload JARVIS to GitHub` commits if needed and pushes to an existing GitHub remote.
Missing remotes produce explicit setup/authentication guidance; automatic GitHub
repository creation is not implemented. General Git questions remain conversational.
See [the Git workflow guide](docs/GIT_WORKFLOW.md) for commands, protections and limits.
