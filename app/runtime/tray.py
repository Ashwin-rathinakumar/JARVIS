"""Optional system-tray adapter. Core runtime works when GUI dependencies are absent."""
from typing import Callable, Optional

from app.runtime.state import RuntimeState
from app.utils.logger import logger


class TrayController:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.running = False
        self._icon = None

    def status_text(self) -> str:
        return f"JARVIS: {self.runtime.state.value.title()}"

    def start_listening(self) -> None:
        self.runtime.start_listening()

    def stop_listening(self) -> None:
        self.runtime.stop_listening()

    def toggle_tts(self) -> bool:
        self.runtime.tts_enabled = not self.runtime.tts_enabled
        return self.runtime.tts_enabled

    def open_console(self) -> None:
        logger.info("Tray requested JARVIS console/status view.")

    def quit(self) -> None:
        self.runtime.shutdown()

    def start(self) -> bool:
        """Start pystray only when optionally installed; never fail the core runtime."""
        try:
            import pystray  # type: ignore
            from PIL import Image  # type: ignore
            image = Image.new("RGB", (16, 16), "black")
            menu = pystray.Menu(
                pystray.MenuItem(lambda _: self.status_text(), None, enabled=False),
                pystray.MenuItem("Start listening", lambda *_: self.start_listening()),
                pystray.MenuItem("Stop listening", lambda *_: self.stop_listening()),
                pystray.MenuItem("Mute/unmute speech", lambda *_: self.toggle_tts()),
                pystray.MenuItem("Open status", lambda *_: self.open_console()),
                pystray.MenuItem("Quit JARVIS", lambda *_: self.quit()),
            )
            self._icon = pystray.Icon("jarvis", image, "JARVIS", menu)
            self.running = True
            self._icon.run_detached()
            return True
        except Exception as error:
            logger.warning("Tray unavailable; persistent core remains active: %s", error)
            return False

    def shutdown(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                logger.exception("Tray shutdown failed")
        self._icon = None
        self.running = False
