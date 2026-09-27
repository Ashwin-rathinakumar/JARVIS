# JARVIS Development Worklog

## Overview
This document records the incremental upgrade of **JARVIS** through **v0.3 Phase 2: Core Intelligence** and **Phase 3: Agentic Action & Permission Layer**, detailing the deterministic task planner, step-by-step agent execution engine, multi-level permission model, confirmation token management, action audit logging, SQLite vector persistence, hybrid RAG, and test verification results.

---

## 1. Phase 3: Agentic Action & Permission Layer Architecture

### A. Core Agent Pipeline
```text
User Goal
   │
   ▼
Jarvis Orchestrator (app/brain/orchestrator.py)
   │
   ├─► Fast Deterministic Routing (system, single file ops, memory, direct chat) (<2ms)
   │
   └─► Jarvis Planner (app/brain/planner.py)
         │  • Pattern Matcher (multi-step discovery, inspection, directory/file operations)
         │  • Ollama JSON Planner Fallback
         │
         ▼
       Plan Validator (app/brain/planner.py)
         │  • Tool registry verification & risk assignment
         │  • Step bounding (MAX_PLAN_STEPS=6)
         │  • Dependency verification ($from_step)
         │
         ▼
       Agent Executor (app/agent/executor.py)
         │  • Step-by-step bounded execution (MAX_AGENT_STEPS=6)
         │  • Safe dependency resolution (no eval)
         │  • PermissionEngine policy evaluation
         │
         ├─► [ALLOW]: Execute registered tool -> Record Audit -> Generate Observation -> Next Step
         ├─► [CONFIRM]: Pause Plan -> Generate Token (TTL 300s) -> Request User Approval [y/N]
         └─► [DENY]: Stop Plan -> Record Rejection Audit -> Emit Failure Diagnostic
```

### B. Risk & Permission Classifications (`app/brain/permissions.py`)
- **READ_ONLY** (`auto-allow`): `system_information`, `cpu_info`, `memory_info`, `disk_info`, `hostname`, `python_version`, `current_directory`, `show_memories`, `search_memories`, `list_projects`, `current_project`, `project_status`, `analyze_project`, `project_tree`, `find_todos`, `search_projects`, `inspect_project`, `list_files`, `find_file`, `search_files`, `read_text_file`, `get_file_info`, `index_documents`, `document_status`, `ask_documents`, `get_recent_actions`.
- **LOW** (`auto-allow`): `open_application` (strictly allowlisted: notepad, calc, paint, explorer, vscode, browser), `close_application`, `open_project`, `remember`.
- **MEDIUM** (`confirmation required`): `create_folder`, `create_directory`, `create_text_file`, `write_text_file`, `forget_memory`, `run_project`, `stop_project`.
- **HIGH / BLOCKED** (`strictly prohibited`): `delete_file`, `format_disk`, `disable_security`, `raw_shell`, `eval_code`, `cmd`, `powershell`, `system_exec`.

### C. Confirmation Management (`app/brain/confirmation.py`)
- In-memory `ConfirmationManager` generates unique cryptographic tokens with 300s TTL.
- Plans pause at medium/high risk steps with status `CONFIRMATION_REQUIRED`.
- CLI users reply with `y` / `yes` or `n` / `no`.
- REST API users submit `POST /api/actions/{id}/confirm` or `POST /api/actions/{id}/cancel`.

### D. Action Audit System (`app/agent/audit.py`)
- Persistent SQLite table `action_audits` in `data/jarvis.db`.
- Records timestamp, session ID, plan ID, step ID, tool name, risk level, permission decision, sanitized arguments summary, execution status, error codes, and result message.
- Automatic redaction of sensitive argument keys (`password`, `token`, `key`, `secret`).
- Accessible directly via conversational inquiry tool `get_recent_actions()` or REST endpoint `GET /api/actions`.

### E. File & Project Intelligence Tools (`app/tools/files.py`, `app/tools/projects.py`)
- `search_files()`: Walk-based filtered search bounded by `MAX_FILE_SEARCH_RESULTS` (20).
- `create_directory()`: Safe directory creation with path validation.
- `write_text_file()`: Safe text writer with maximum file size bounding (256 KB) and prohibited extension validation (`.exe`, `.bat`, `.cmd`, `.ps1`, `.vbs`, etc.).
- `get_file_info()`: Detailed filesystem metadata extraction.
- `search_projects()`: Fuzzy and exact project locator with disambiguation prompts.
- `inspect_project()`: In-depth project inspection (tech stack, git status, file structure, key files).

---

## 2. Phase 2 & Retrieval RAG Foundations

- **Local Embeddings**: `app/retrieval/embeddings.py` generates vectors using `nomic-embed-text` via Ollama.
- **Semantic Vector Storage & Cosine Similarity**: Pure-Python vector search in SQLite `documents.db` with chunk hash deduplication.
- **Hybrid Retrieval with RRF**: Reciprocal Rank Fusion ($k=60$) combining SQLite FTS5 BM25 lexical ranking and cosine similarity embeddings.
- **Text-Based PDF Ingestion**: Page-by-page text extraction (`pypdf`) with error handling for scanned or protected files.

---

## 3. Test Coverage & Verification

Automated test suite (`tests/`):
- `tests/test_planner.py`: Multi-step deterministic plan generation, JSON fallback, validator bounding, invalid tool rejection, blocked tool rejection.
- `tests/test_permissions.py`: Risk classifications, read-only auto-allow, medium confirmation, blocked command denials, path traversal rejection, script extension blocking, shell injection prevention.
- `tests/test_executor.py`: Multi-step plan execution, dependency resolution (`$from_step`), confirmation pause/resume, dry-run simulation.
- `tests/test_audit.py`: Argument sanitization/redaction, SQLite audit recording, audit queries, `get_recent_actions` tool.
- `tests/test_security_phase3.py`: Verification of raw shell rejection (`cmd.exe`, `powershell`, `eval`), blocked extensions, System32 protection, and protected environment preservation.
- `tests/test_orchestrator.py`: Central orchestration, deterministic routing, session isolation, error containment.
- `tests/test_api.py`: FastAPI endpoints for health, chat, tools, memory, sessions, and action confirmations.
- `tests/test_path_safety.py`: Directory boundary enforcement against `JARVIS_ALLOWED_PATHS`.
- `tests/test_hybrid.py`: Hybrid search, RRF score fusion, chunk deduplication.
- `tests/test_pdf.py`: PDF loading, chunking, FTS5 indexing, semantic embedding.
- `tests/test_embeddings.py`: Ollama embedding generation, timeouts, error handling.
- `tests/test_rag.py`: Lexical BM25 and semantic cosine similarity ranking.
- `tests/test_projects.py`: Alias matching, launcher discovery, project run/stop.
- `tests/test_intent.py`: Deterministic intent matching across all groups.
- `tests/test_database.py`: SQLite memory CRUD and formatting.
- `tests/test_tools.py`: System diagnostics, safe file operations, application normalization.
- `tests/test_session.py`: Bounded history, process registration.
- `tests/test_router.py`: Command routing and chat fallback.
- `tests/test_provider.py`: Ollama timeout, connection error recovery, Gemini fallback.

**Test Run Summary**:
```text
Ran 110 tests in 26.698s
OK (110 passed, 0 failures, 0 errors)
```

---

## 4. Complete Project Architecture Tree

```text
C:\JARVIS
├── .env                       # Active environment configuration
├── .env.example               # Template configuration with Phase 3 settings
├── README.md                  # Project overview, API reference, and quickstart
├── DEVELOPMENT.md             # Engineering worklog & architecture specifications
├── requirements.txt           # Dependencies: fastapi, uvicorn, requests, pypdf, pydantic
├── verify_phase3.py           # Verification script for 10 manual validation scenarios
├── data/
│   ├── jarvis.db              # SQLite persistent memories & action_audits table
│   ├── documents.db           # SQLite FTS5 (BM25) & document_embeddings
│   └── documents/             # Target directory for local document RAG (.txt, .md, .pdf)
├── logs/
│   └── jarvis.log             # Rotating diagnostic logs
├── workspace/                 # Sandboxed working directory for file and agent tasks
├── app/
│   ├── main.py                # Dual entrypoint: Interactive CLI REPL or FastAPI server (--server)
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── executor.py        # AgentExecutor: Step execution, dependency resolution, observations
│   │   └── audit.py           # Action audit logging & SQLite persistence
│   ├── api/
│   │   ├── __init__.py
│   │   └── server.py          # FastAPI server factory, chat, health, actions & confirmation routes
│   ├── brain/
│   │   ├── __init__.py
│   │   ├── orchestrator.py    # JarvisOrchestrator central processing engine
│   │   ├── planner.py         # JarvisPlanner & PlanValidator
│   │   ├── permissions.py     # PermissionEngine & risk classifications
│   │   ├── confirmation.py    # ConfirmationManager: token generation & TTL validation
│   │   ├── llm.py             # JarvisBrain provider coordinator
│   │   ├── intent.py          # Deterministic matcher + LLM fallback
│   │   ├── router.py          # Command execution dispatcher
│   │   ├── prompts.py         # Central system prompt
│   │   ├── context.py         # Dynamic memory & project context builder
│   │   ├── state.py           # Backward-compatible state re-export
│   │   └── providers/
│   │       ├── base.py        # BaseLLMProvider interface
│   │       ├── ollama.py      # Local Ollama client
│   │       └── gemini.py      # Optional Gemini provider
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py        # Centralized settings, path security, agent limits
│   │   └── projects.py        # Project registry (JARVIS, KEER)
│   ├── core/
│   │   ├── __init__.py
│   │   └── schemas.py         # Pydantic models (ActionPlan, ActionStep, Observation, AuditRecord, etc.)
│   ├── memory/
│   │   ├── __init__.py
│   │   └── database.py        # SQLite database manager
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── loader.py          # Document loader (.txt, .md, .pdf)
│   │   ├── chunker.py         # Sliding window chunker
│   │   ├── indexer.py         # SQLite FTS5 BM25 + semantic vector storage
│   │   ├── embeddings.py      # Ollama embedding engine (nomic-embed-text)
│   │   ├── hybrid.py          # Reciprocal Rank Fusion (RRF) hybrid search
│   │   └── rag.py             # Grounded retrieval & Q&A
│   ├── state/
│   │   ├── __init__.py
│   │   └── session.py         # SessionState & SessionManager with plan tracking
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── apps.py            # Allowlisted application launcher
│   │   ├── projects.py        # Project management, search_projects, inspect_project, Code launcher
│   │   ├── system.py          # Hardware & OS diagnostics
│   │   ├── files.py           # Safe file operations, search_files, write_text_file, get_file_info
│   │   ├── analysis.py        # Project structure & TODO scanner
│   │   └── registry.py        # Centralized tool registry & ToolResult
│   └── utils/
│       ├── __init__.py
│       └── logger.py          # File and console logger
└── tests/
    ├── test_planner.py        # Multi-step planning and validation tests
    ├── test_permissions.py    # Deterministic permission and risk level tests
    ├── test_executor.py       # Agent step executor and dependency resolution tests
    ├── test_audit.py          # Action audit and redaction tests
    ├── test_security_phase3.py# Strict security invariant tests
    ├── test_orchestrator.py   # Orchestration & intent execution tests
    ├── test_api.py            # FastAPI REST endpoint tests
    ├── test_path_safety.py    # Path traversal restriction tests
    ├── test_hybrid.py         # Hybrid search & RRF tests
    ├── test_pdf.py            # PDF ingestion & extraction tests
    ├── test_embeddings.py     # Embedding unit tests
    ├── test_rag.py            # Lexical & semantic RAG tests
    ├── test_projects.py       # Project management tests
    ├── test_intent.py         # Intent classification tests
    ├── test_database.py       # SQLite memory tests
    ├── test_tools.py          # Tool execution tests
    ├── test_session.py        # Session state tests
    ├── test_router.py         # Router tests
    └── test_provider.py       # Provider fallback tests
```
