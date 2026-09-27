"""Backward-compatible re-export of SessionState."""
from app.state.session import SessionState, session

__all__ = ["SessionState", "session"]