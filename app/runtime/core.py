"""Persistent local runtime that wraps the existing JARVIS voice/core pipeline."""
import re
import threading
import time
from typing import Optional

from app.brain.intent import classify_intent
from app.brain.orchestrator import JarvisOrchestrator
from app.core.schemas import ChatResponse
from app.runtime.activation import DisabledWakeWordProvider, TranscriptWakeWordProvider, WakeWordProvider
from app.config.settings import (JARVIS_WAKE_PROVIDER, JARVIS_WAKE_PHRASES,
                                 JARVIS_WAKE_WINDOW_SECONDS, JARVIS_FOLLOW_UP_SECONDS)
from app.runtime.state import RuntimeState, RuntimeStateMachine
from app.runtime.tray import TrayController
from app.state.session import session_manager
from app.utils.logger import logger
from app.voice.microphone import Microphone
from app.voice.runtime import VoiceRuntime
from app.voice.stt import BaseSTT, create_stt_provider
from app.voice.tts import BaseTTS, create_tts_provider


class JarvisRuntime:
    """Owns persistent lifecycle, runtime state, voice adapters, and one session."""

    def __init__(self, orchestrator: Optional[JarvisOrchestrator] = None,
                 microphone: Optional[Microphone] = None, stt: Optional[BaseSTT] = None,
                 tts: Optional[BaseTTS] = None, wake_provider: Optional[WakeWordProvider] = None,
                 session_id: str = "persistent-runtime") -> None:
        self.session_id = session_id
        self.microphone = microphone or Microphone()
        self.stt = stt or create_stt_provider()
        self.tts = tts or create_tts_provider()
        self.voice = VoiceRuntime(orchestrator=orchestrator or JarvisOrchestrator(), microphone=self.microphone,
                                  stt=self.stt, tts=self.tts, session_id=session_id)
        self.state_machine = RuntimeStateMachine()
        if wake_provider is not None:
            self.wake_provider = wake_provider
        elif JARVIS_WAKE_PROVIDER == "transcript":
            self.wake_provider = TranscriptWakeWordProvider(self.microphone, self.stt, JARVIS_WAKE_PHRASES,
                                                            JARVIS_WAKE_WINDOW_SECONDS)
        else:
            self.wake_provider = DisabledWakeWordProvider()
        self.tray = TrayController(self)
        self._stop = threading.Event()
        self._listener: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._shutdown = False
        self.tts_enabled = bool(getattr(self.tts, "enabled", True))

    @property
    def state(self) -> RuntimeState:
        return self.state_machine.state

    def _set_state(self, state: RuntimeState, reason: str) -> None:
        self.state_machine.transition(state, reason)
        logger.info("Runtime state transition=%s reason=%s", state.value, reason)

    def _contextualize(self, transcript: str) -> str:
        text = (transcript or "").strip()
        context = session_manager.get_session(self.session_id).conversation_context
        lower = re.sub(r"[.!?]+$", "", text.lower()).strip()
        if context.last_location and lower in {"what about tomorrow", "and tomorrow", "tomorrow"}:
            return f"weather in {context.last_location} tomorrow"
        if context.last_project and re.fullmatch(r"(?:close|stop)\s+it", lower):
            return f"close {context.last_project}"
        if context.last_project and re.fullmatch(r"(?:run|execute)\s+(?:its|the)\s+tests", lower):
            return f"run tests for {context.last_project}"
        return text

    def process_transcript(self, transcript: str, follow_up: bool = False) -> ChatResponse:
        """Process one text/STT turn without restarting the runtime."""
        with self._lock:
            if self._shutdown:
                return ChatResponse(success=False, intent="system", response="JARVIS is shutting down.", session_id=self.session_id)
            text = self._contextualize(transcript)
            try:
                self._set_state(RuntimeState.THINKING, "transcript_ready")
                decision = classify_intent(text)
                if decision.get("tool"):
                    self._set_state(RuntimeState.EXECUTING, "deterministic_tool")
                response = self.voice._handle_transcript(text)
                self._set_state(RuntimeState.SPEAKING, "response_ready")
                if self.tts_enabled:
                    self.voice._output(response)
                self._set_state(RuntimeState.FOLLOW_UP if follow_up else RuntimeState.IDLE, "turn_complete")
                return response
            except Exception:
                logger.exception("Persistent runtime turn failed")
                if self.state != RuntimeState.ERROR:
                    self._set_state(RuntimeState.ERROR, "turn_failure")
                self._set_state(RuntimeState.IDLE, "recovered")
                return ChatResponse(success=False, intent="system", response="I couldn't process that command.", session_id=self.session_id)

    def process_voice_cycle(self, duration: Optional[float] = None, follow_up: bool = False) -> ChatResponse:
        with self._lock:
            try:
                self._set_state(RuntimeState.LISTENING, "capture_start")
                audio = self.microphone.capture_push_to_talk(duration=duration)
                if audio is None:
                    self._set_state(RuntimeState.FOLLOW_UP if follow_up else RuntimeState.IDLE, "empty_capture")
                    return ChatResponse(success=False, intent="system", response="I didn't catch that.", session_id=self.session_id)
                self._set_state(RuntimeState.TRANSCRIBING, "capture_complete")
                utterance = self.stt.transcribe(audio)
            except Exception:
                logger.exception("Voice capture/transcription failed")
                self._set_state(RuntimeState.ERROR, "voice_failure")
                self._set_state(RuntimeState.FOLLOW_UP if follow_up else RuntimeState.IDLE, "recovered")
                return ChatResponse(success=False, intent="system", response="I couldn't transcribe that.", session_id=self.session_id)
        if not utterance.text.strip():
            self._set_state(RuntimeState.FOLLOW_UP if follow_up else RuntimeState.IDLE, "silence")
            return ChatResponse(success=False, intent="system", response="I didn't catch that.", session_id=self.session_id)
        return self.process_transcript(utterance.text, follow_up=follow_up)

    def _conversation_window(self, initial_command: str) -> None:
        self._set_state(RuntimeState.LISTENING, "wake_detected")
        if self.tts_enabled:
            self._set_state(RuntimeState.SPEAKING, "wake_acknowledgement")
            try:
                self.tts.speak("Yes?")
            except Exception:
                logger.exception("Wake acknowledgement playback failed")
            self._set_state(RuntimeState.FOLLOW_UP, "wake_acknowledged")
        else:
            self._set_state(RuntimeState.FOLLOW_UP, "wake_acknowledged")
        if initial_command:
            self.process_transcript(initial_command, follow_up=True)
        deadline = time.monotonic() + JARVIS_FOLLOW_UP_SECONDS
        while not self._stop.is_set() and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            response = self.process_voice_cycle(duration=min(JARVIS_WAKE_WINDOW_SECONDS, remaining), follow_up=True)
            if response.success or response.status == "confirmation_required":
                deadline = time.monotonic() + JARVIS_FOLLOW_UP_SECONDS
            elif self._stop.wait(0.05):
                break
        if self.state == RuntimeState.FOLLOW_UP:
            self._set_state(RuntimeState.IDLE, "follow_up_timeout")
        session_manager.get_session(self.session_id).conversation_context.last_project = None
        session_manager.get_session(self.session_id).conversation_context.last_location = None

    def _wake_loop(self) -> None:
        while not self._stop.is_set():
            try:
                wait_seconds = JARVIS_WAKE_WINDOW_SECONDS if getattr(self.wake_provider, "continuous", False) else 0.2
                if self.wake_provider.wait_for_wake(wait_seconds):
                    logger.info("Runtime wake event received")
                    if getattr(self.wake_provider, "continuous", False):
                        self._conversation_window(self.wake_provider.take_command())
                    else:
                        self.process_voice_cycle()
            except Exception:
                logger.exception("Wake worker error")
                if self.state == RuntimeState.ERROR:
                    self._set_state(RuntimeState.IDLE, "wake_recovered")

    def start_listening(self) -> None:
        with self._lock:
            if self._shutdown or (self._listener and self._listener.is_alive()):
                return
            self._stop.clear()
            self._listener = threading.Thread(target=self._wake_loop, name="jarvis-wake", daemon=True)
            self._listener.start()
            logger.info("Persistent runtime listener started")

    def stop_listening(self) -> None:
        self._stop.set()
        if self._listener and self._listener is not threading.current_thread():
            self._listener.join(timeout=2)
        if self._listener and not self._listener.is_alive():
            self._listener = None
        if self.state == RuntimeState.LISTENING:
            self._set_state(RuntimeState.IDLE, "listener_stopped")

    def start_desktop(self) -> None:
        self.start_listening()
        self.tray.start()
        logger.info("Persistent runtime started")

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            if self.state != RuntimeState.STOPPED:
                self._set_state(RuntimeState.STOPPING, "shutdown")
        self.stop_listening()
        self.wake_provider.shutdown()
        self.tray.shutdown()
        close = getattr(self.microphone, "close", None)
        if callable(close):
            close()
        close_tts = getattr(self.tts, "shutdown", None)
        if callable(close_tts):
            close_tts()
        close_brain = getattr(self.voice.orchestrator.brain, "close", None)
        if callable(close_brain):
            close_brain()
        self._set_state(RuntimeState.STOPPED, "shutdown_complete")
        logger.info("Persistent runtime shutdown complete")
