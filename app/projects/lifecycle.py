"""Session-owned editor instances. Never terminate a process or match titles."""
from dataclasses import dataclass
from pathlib import Path
import os
import time
import uuid
import psutil

from app.config.settings import BASE_DIR


@dataclass
class ProjectRuntimeState:
    project_key: str
    canonical_name: str
    path: Path
    profile: Path
    process: object
    launched_at: float
    created_at: float | None
    opened_by_jarvis: bool = True
    open: bool | None = None


class WindowsEditorBackend:
    def identity(self, pid):
        proc = psutil.Process(pid)
        return proc.create_time(), proc.cmdline()

    def windows(self, pid):
        if os.name != "nt":
            raise RuntimeError("Scoped editor closing is available only on Windows")
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        found = []

        @callback_type
        def visit(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        if not user32.EnumWindows(visit, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return found

    def request_close(self, hwnd, pid):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            raise RuntimeError("Editor window ownership changed")
        if not user32.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE: honors unsaved-work dialogs
            raise ctypes.WinError(ctypes.get_last_error())


class ProjectLifecycle:
    def __init__(self, backend=None):
        self.states: dict[str, ProjectRuntimeState] = {}
        self.backend = backend or WindowsEditorBackend()

    def new_profile(self):
        return BASE_DIR / "data" / "editor-sessions" / uuid.uuid4().hex

    def track(self, key, name, path, profile, process):
        try:
            born, _ = self.backend.identity(process.pid)
        except (psutil.Error, OSError, TypeError):
            born = None
        self.states[key] = ProjectRuntimeState(key, name, path, profile, process, time.time(), born)

    def owned(self, state):
        if state.created_at is None or state.process.poll() is not None:
            return False
        try:
            born, args = self.backend.identity(state.process.pid)
            index = args.index("--user-data-dir")
            return born == state.created_at and Path(args[index + 1]).resolve() == state.profile.resolve()
        except (psutil.Error, OSError, ValueError, IndexError, TypeError):
            return False

    def status(self, key):
        state = self.states.get(key)
        if state is None:
            return None
        if state.process.poll() is not None:
            state.open = False
        elif self.owned(state):
            try:
                state.open = True if self.backend.windows(state.process.pid) else (False if state.open is False else None)
            except (OSError, RuntimeError):
                state.open = None
        else:
            state.open = None
        return state

    def wait_until_open(self, key, timeout=40):
        deadline = time.monotonic() + timeout
        while True:
            state = self.status(key)
            if state is None or state.process.poll() is not None:
                return False
            if state.open is True:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def startup_failure(self, key):
        state = self.states.get(key)
        if state:
            for log in sorted(state.profile.glob("logs/*/main.log"), reverse=True)[:1]:
                try:
                    if "Code is currently being updated" in log.read_text(encoding="utf-8")[-16000:]:
                        return "VS Code is currently being updated. Please let the update finish and try again."
                except OSError:
                    pass
        return "VS Code did not create a verifiable editor window. Check VS Code startup and try again."

    def close(self, key, path, timeout=5):
        state = self.status(key)
        if state is not None and state.open is False:
            return False, "does not appear to be open."
        if state is None or state.path != path or not self.owned(state):
            return False, "couldn't safely identify the editor instance to close it."
        windows = self.backend.windows(state.process.pid)
        # Multiple windows in a managed profile may contain unrelated work.
        if len(windows) != 1:
            return False, "couldn't safely identify a single editor window to close."
        if not self.owned(state):
            return False, "editor ownership changed; no close was requested."
        self.backend.request_close(windows[0], state.process.pid)
        deadline = time.monotonic() + timeout
        while True:
            if state.process.poll() is not None or not self.backend.windows(state.process.pid):
                state.open = False
                return True, "closed"
            if time.monotonic() >= deadline:
                return False, "is still open. Check VS Code for an unsaved-work prompt."
            time.sleep(0.1)


project_lifecycle = ProjectLifecycle()
