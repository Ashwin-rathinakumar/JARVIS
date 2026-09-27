# JARVIS v0.3 Patch Notes

This overlay patch preserves your existing `.env`, virtual environment, SQLite memories, document index, and local logs.

## Added
- Smart memory retrieval for normal conversation.
- Central conversation context builder.
- `.env.example` and a real `.gitignore`.
- Context tests and memory relevance tests.

## Changed
- Runtime version updated to v0.3.
- VS Code/project launching avoids `shell=True` for normal configured commands.
- VS Code child stdout/stderr is detached from the JARVIS console.
- Project tests no longer require an actual Windows/VS Code host.

## Verification
- `python -m compileall -q app tests`
- `python -m unittest discover -s tests -p "test_*.py" -v`
- Result: 43 passed.

## Windows verification after applying
Run:

```powershell
cd C:\JARVIS
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\venv\Scripts\python.exe -m app.main
```

Then test:

```text
remember that my preferred editor is VS Code
what editor do I prefer?
open keer project
run keer project
```
