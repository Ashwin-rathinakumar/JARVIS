import json
import sqlite3
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from app.config.settings import DATABASE_PATH
from app.core.schemas import AuditRecord
from app.utils.logger import logger


def _get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DATABASE_PATH)


def init_audit_table():
    """Ensure action_audits table exists in SQLite database."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS action_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                session_id TEXT,
                plan_id TEXT,
                step_id TEXT,
                tool TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                permission_decision TEXT NOT NULL,
                arguments_summary TEXT,
                success BOOLEAN NOT NULL,
                error_code TEXT,
                message TEXT,
                source TEXT DEFAULT 'cli'
            )
        """)
        # Pragma check for existing table without source column
        cursor.execute("PRAGMA table_info(action_audits)")
        columns = [c[1] for c in cursor.fetchall()]
        if "source" not in columns:
            cursor.execute("ALTER TABLE action_audits ADD COLUMN source TEXT DEFAULT 'cli'")
        conn.commit()
    finally:
        conn.close()


def sanitize_arguments(arguments: Dict[str, Any]) -> str:
    """Sanitize arguments by redacting potential passwords, tokens, or huge content."""
    sanitized = {}
    for k, v in arguments.items():
        if any(secret in k.lower() for secret in ["password", "token", "key", "secret"]):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, str) and len(v) > 200:
            sanitized[k] = v[:100] + "... [truncated]"
        else:
            sanitized[k] = v
    try:
        return json.dumps(sanitized)
    except Exception:
        return str(sanitized)


def record_audit(
    tool: str,
    risk_level: str,
    permission_decision: str,
    arguments: Dict[str, Any],
    success: bool,
    session_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    step_id: Optional[str] = None,
    error_code: Optional[str] = None,
    message: Optional[str] = None,
    source: str = "cli",
) -> None:
    """Record an action audit entry in SQLite."""
    init_audit_table()
    args_summary = sanitize_arguments(arguments)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO action_audits (
                timestamp, session_id, plan_id, step_id, tool,
                risk_level, permission_decision, arguments_summary,
                success, error_code, message, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ts, session_id, plan_id, step_id, tool,
            risk_level, permission_decision, args_summary,
            success, error_code, message, source
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"Failed to record audit log: {e}")
    finally:
        conn.close()


def get_recent_actions(limit: int = 10) -> str:
    """Retrieve formatted summary of recent executed actions for user inquiry."""
    init_audit_table()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, tool, risk_level, permission_decision,
                   arguments_summary, success, error_code, message, source
            FROM action_audits
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
    except Exception as e:
        logger.error(f"Failed to read action audits: {e}")
        return f"Unable to read action history: {e}"
    finally:
        conn.close()

    if not rows:
        return "No recent actions have been recorded yet."

    lines = ["Recent Actions Audit:"]
    for row in rows:
        status_str = "SUCCESS" if row[6] else f"FAILED ({row[7] or 'Error'})"
        src_str = f" [{row[9]}]" if len(row) > 9 and row[9] else ""
        lines.append(
            f"- [{row[1]}]{src_str} {row[2]} (risk: {row[3]}, decision: {row[4]}) -> {status_str}: {row[8] or ''}"
        )
    return "\n".join(lines)


def get_audit_records(limit: int = 50) -> List[AuditRecord]:
    """Retrieve structured audit records for REST API."""
    init_audit_table()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, session_id, plan_id, step_id, tool,
                   risk_level, permission_decision, arguments_summary,
                   success, error_code, message, source
            FROM action_audits
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
    except Exception as e:
        logger.error(f"Failed to query audits: {e}")
        return []
    finally:
        conn.close()

    return [
        AuditRecord(
            id=r[0],
            timestamp=r[1],
            session_id=r[2],
            plan_id=r[3],
            step_id=r[4],
            tool=r[5],
            risk_level=r[6],
            permission_decision=r[7],
            arguments_summary=r[8],
            success=bool(r[9]),
            error_code=r[10],
            message=r[11],
            source=r[12] if len(r) > 12 else "cli",
        )
        for r in rows
    ]


# Aliases for backward compatibility and test convenience
sanitize_payload = sanitize_arguments
get_recent_action_records = get_audit_records
