import os
import sys
import argparse
from pathlib import Path

from app.brain.llm import JarvisBrain
from app.brain.orchestrator import JarvisOrchestrator
from app.memory.database import initialize_database, get_connection
from app.retrieval.indexer import get_index_stats
from app.tools.registry import list_tools
from app.state.session import session_manager
from app.config.settings import (
    JARVIS_NAME,
    VERSION,
    OLLAMA_MODEL,
    LLM_PROVIDER,
    JARVIS_HOST,
    JARVIS_PORT,
)
from app.utils.logger import logger


def get_status_report(brain: JarvisBrain) -> str:
    """Generate dynamic live status report based on real component checks."""
    lines = [f"{JARVIS_NAME} System Status"]
    lines.append("-" * 35)

    # 1. Brain / LLM Provider
    health = brain.health_check()
    provider_name = health.get("provider", LLM_PROVIDER)
    is_connected = health.get("connected", False)
    conn_str = "Connected" if is_connected else "Offline / Disconnected"
    model_name = health.get("model", OLLAMA_MODEL)
    lines.append(f"LLM Provider   : {provider_name.upper()} ({conn_str})")
    lines.append(f"Active Model   : {model_name}")

    # 2. SQLite Database
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM memories")
            mem_count = cursor.fetchone()[0]
        db_status = f"OK ({mem_count} saved memories)"
    except Exception as e:
        db_status = f"Error ({e})"
    lines.append(f"Database       : {db_status}")

    # 3. Document RAG Store
    try:
        stats = get_index_stats()
        rag_status = f"OK ({stats['file_count']} docs, {stats['chunk_count']} chunks)"
    except Exception as e:
        rag_status = f"Not configured / {e}"
    lines.append(f"Document Index : {rag_status}")

    # 4. Current Project
    curr_proj = session_manager.default_session.get_current_project()
    lines.append(f"Current Project: {curr_proj or 'None'}")

    # 5. Active JARVIS-managed processes
    procs = session_manager.default_session.list_active_processes()
    proc_str = ", ".join(procs) if procs else "None"
    lines.append(f"Active Tasks   : {proc_str}")

    return "\n".join(lines)


def get_help_guide() -> str:
    """Generate dynamic help guide grouped by tool categories."""
    categories = list_tools()
    lines = ["=" * 55, f"             {JARVIS_NAME} HELP GUIDE", "=" * 55]

    for cat_name, tools in sorted(categories.items()):
        lines.append(f"\n[{cat_name}]")
        for tool in tools:
            lines.append(f"  {tool.name:<22} - {tool.description}")

    lines.append("\n[Quick Shortcuts & Commands]")
    lines.append("  help                   - Display this capabilities guide")
    lines.append("  status                 - Live diagnostic check")
    lines.append("  projects               - List all registered projects")
    lines.append("  memories               - Display persistent memories")
    lines.append("  clear                  - Clear terminal screen")
    lines.append("  exit / quit            - Gracefully shut down JARVIS")
    lines.append("=" * 55)

    return "\n".join(lines)


def print_banner(brain: JarvisBrain):
    health = brain.health_check()
    is_connected = health.get("connected", False)
    status_label = "Ready" if is_connected else "Ready (Local tools only - LLM offline)"

    print()
    print("=" * 55)
    print(f"             {JARVIS_NAME} v{VERSION}")
    print("       Local-First Personal AI Assistant")
    print("=" * 55)
    print(f"Provider : {brain.provider_name.capitalize()}")
    print(f"Model    : {health.get('model', OLLAMA_MODEL)}")
    print(f"Status   : {status_label}")
    print("Type 'help' for commands or 'exit' to shut down.")
    print("=" * 55)
    print()


def run_server(host: str = JARVIS_HOST, port: int = JARVIS_PORT):
    """Launch the FastAPI ASGI application via Uvicorn."""
    import uvicorn
    from app.api.server import app

    logger.info(f"Starting JARVIS Core API on http://{host}:{port}")
    print(f"\nStarting {JARVIS_NAME} Core API server on http://{host}:{port} ...")
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    initialize_database()
    logger.info("JARVIS initialized")

    parser = argparse.ArgumentParser(description=f"{JARVIS_NAME} Assistant")
    parser.add_argument("--server", action="store_true", help="Run as FastAPI Core API server")
    parser.add_argument("--voice", action="store_true", help="Run in interactive Voice Mode (Push-to-Talk)")
    parser.add_argument("--runtime", action="store_true", help="Run persistent desktop runtime (tray when available)")
    parser.add_argument("--host", default=JARVIS_HOST, help="Server host")
    parser.add_argument("--port", type=int, default=JARVIS_PORT, help="Server port")
    args = parser.parse_args()

    if args.server:
        run_server(host=args.host, port=args.port)
        return

    try:
        brain = JarvisBrain()
        orchestrator = JarvisOrchestrator(brain=brain)
    except Exception as error:
        logger.error(f"Startup error: {error}")
        print(f"Startup error: {error}")
        return

    if args.voice:
        from app.voice.runtime import VoiceRuntime
        runtime = VoiceRuntime(orchestrator=orchestrator)
        runtime.run_voice_loop()
        return

    if args.runtime:
        from app.runtime.core import JarvisRuntime
        runtime = JarvisRuntime(orchestrator=orchestrator)
        runtime.start_desktop()
        print("JARVIS persistent runtime is active. Press Ctrl+C to quit.")
        try:
            while runtime.state.value != "STOPPED":
                __import__("time").sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            runtime.shutdown()
        return

    print_banner(brain)

    while True:
        try:
            user_input = input("YOU > ").strip()

            if not user_input:
                continue

            lower = user_input.lower()

            if lower in {"exit", "quit", "shutdown"}:
                print("\nJARVIS > Shutting down. Goodbye!\n")
                logger.info("JARVIS shut down by user")
                break

            if lower == "clear":
                os.system("cls" if os.name == "nt" else "clear")
                continue

            if lower == "status":
                print(f"\nJARVIS >\n{get_status_report(brain)}\n")
                continue

            if lower == "help":
                print(f"\n{get_help_guide()}\n")
                continue

            # Process through unified Orchestrator
            result = orchestrator.process(user_input)
            print(f"\nJARVIS > {result.response}\n")

        except KeyboardInterrupt:
            print("\nJARVIS > Shutting down.\n")
            logger.info("JARVIS shut down by KeyboardInterrupt")
            break

        except Exception as error:
            logger.error(f"Runtime error: {error}", exc_info=True)
            print(f"\nJARVIS > Runtime error: {error}\n")


if __name__ == "__main__":
    main()
