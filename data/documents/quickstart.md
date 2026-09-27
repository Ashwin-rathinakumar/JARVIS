# JARVIS Quick Reference Guide

JARVIS is a local-first personal AI assistant running on Windows 11.
It connects to local Ollama models (default: qwen2.5:1.5b) and executes deterministic tools.
Tool execution includes opening applications (Notepad, Calculator, VS Code), managing projects, system diagnostics, and persistent memory.

Key features:
- Fast deterministic command routing
- Project management with process isolation
- SQLite memory database
- Local document RAG via SQLite FTS5 BM25 search
- Local privacy: zero cloud dependencies required for normal operations.
