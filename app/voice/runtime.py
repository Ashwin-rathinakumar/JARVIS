import re
import threading
from typing import Optional, Set
from app.brain.orchestrator import JarvisOrchestrator
from app.brain.confirmation import confirmation_manager
from app.core.schemas import ChatResponse
from app.voice.microphone import Microphone
from app.voice.stt import BaseSTT, create_stt_provider
from app.voice.tts import BaseTTS, create_tts_provider
from app.response.formatter import ResponseFormatter
from app.state.session import session_manager, SessionState
from app.utils.logger import logger

CONFIRMATION_YES_PHRASES: Set[str] = {
    "yes", "yeah", "yep", "confirm", "go ahead", "proceed", "do it", "continue", "y", "sure", "ok"
}

CONFIRMATION_NO_PHRASES: Set[str] = {
    "no", "nope", "cancel", "stop", "don't", "do not", "never mind", "n", "abort", "reject"
}


class VoiceRuntime:
    """
    Connects Push-to-Talk Voice I/O to the existing JARVIS command processing pipeline.
    Uses the exact same JarvisOrchestrator, Planner, Permissions, and Confirmation tokens.
    """

    def __init__(
        self,
        orchestrator: Optional[JarvisOrchestrator] = None,
        microphone: Optional[Microphone] = None,
        stt: Optional[BaseSTT] = None,
        tts: Optional[BaseTTS] = None,
        session_id: str = "voice-session-default",
    ):
        self.orchestrator = orchestrator or JarvisOrchestrator()
        self.microphone = microphone or Microphone()
        self.stt = stt or create_stt_provider()
        self.tts = tts or create_tts_provider()
        self.session_id = session_id
        self.formatter = ResponseFormatter()
        self._audio_lock = threading.RLock()
        self.tts_failures = 0
        self.last_tts_succeeded = None

    def _output(self, response: ChatResponse) -> ChatResponse:
        spoken = self.formatter.format_for_voice(response)
        self.last_tts_succeeded = None
        if not getattr(self.tts, "enabled", True):
            logger.info("Voice output intent=%s TTS=intentionally_disabled", response.intent)
            return response
        try:
            self.last_tts_succeeded = bool(self.tts.speak(spoken))
        except Exception as error:
            self.last_tts_succeeded = False
            logger.error("[TTS ERROR] backend=%s operation=speak error=%s", type(self.tts).__name__, error)
        if self.last_tts_succeeded:
            self.tts_failures = 0
        else:
            self.tts_failures += 1
            logger.error("[TTS ERROR] consecutive_failures=%d recovery=next_utterance", self.tts_failures)
            print(f"[TTS ERROR] Response could not be spoken ({self.tts_failures} consecutive failures). See logs/jarvis.log.")
        logger.info("Voice output intent=%s tool=%s success=%s TTS_attempted=true TTS_completed=%s response=%r",
                    response.intent, response.tool_used, response.success, self.last_tts_succeeded, response.response)
        return response

    def handle_transcript(self, raw_transcript: str) -> ChatResponse:
        with self._audio_lock:
            try:
                response = self._handle_transcript(raw_transcript)
            except Exception:
                logger.exception("Voice command processing failed")
                response = ChatResponse(success=False, intent="system", response="I couldn't process that command.",
                                        session_id=self.session_id, error="VOICE_PROCESSING_FAILED")
            return self._output(response)

    def _handle_transcript(self, raw_transcript: str) -> ChatResponse:
        """
        Process a transcribed text utterance through the core JARVIS orchestrator.
        """
        text = (raw_transcript or "").strip()

        if not text:
            msg = "I didn't catch that."
            return ChatResponse(
                success=True,
                intent="chat",
                response=msg,
                session_id=self.session_id,
            )

        logger.info(f"[VoiceRuntime] Handling transcript: '{text}' (session={self.session_id})")
        session: SessionState = session_manager.get_session(self.session_id)
        lower = re.sub(r"[.!?,]+$", "", text.lower()).strip()

        # Check if there is an active pending confirmation
        if session.pending_plan and session.pending_confirmation_id:
            token = session.pending_confirmation_id
            # Verify if token is still valid in confirmation manager
            token_details = confirmation_manager.get_confirmation(token)
            if not token_details:
                # Expired or invalid token
                session.pending_plan = None
                session.pending_confirmation_id = None
                msg = "That confirmation request has expired. Please issue the command again."
                return ChatResponse(
                    success=False,
                    intent="system",
                    response=msg,
                    session_id=self.session_id,
                    error="CONFIRMATION_EXPIRED",
                )

            # Check normalized confirmation response
            if lower in CONFIRMATION_YES_PHRASES:
                logger.info("[VoiceRuntime] Voice user confirmed pending action.")
                response = self.orchestrator.process("y", session_id=self.session_id, source="voice")
            elif lower in CONFIRMATION_NO_PHRASES:
                logger.info("[VoiceRuntime] Voice user cancelled pending action.")
                response = self.orchestrator.process("n", session_id=self.session_id, source="voice")
            else:
                # Ambiguous response -> do NOT execute or cancel, request clear response
                logger.info(f"[VoiceRuntime] Ambiguous confirmation response: '{text}'")
                msg = "I didn't receive a clear confirmation. Say yes to continue or no to cancel."
                return ChatResponse(
                    success=True,
                    intent="system",
                    response=msg,
                    session_id=self.session_id,
                    status="confirmation_required",
                    confirmation_id=token,
                )
        else:
            # Normal command processing
            response = self.orchestrator.process(text, session_id=self.session_id, source="voice")
        return response

    def listen_and_process(self, duration: Optional[float] = None) -> ChatResponse:
        # Capture, transcription and playback cannot overlap even if called by
        # two clients. Whisper remains attached to this runtime for the session.
        with self._audio_lock:
            try:
                audio = self.microphone.capture_push_to_talk(duration=duration)
                if audio is None:
                    return self._output(ChatResponse(success=False, intent="system",
                        response="I didn't catch that.", session_id=self.session_id, error="AUDIO_CAPTURE_FAILED"))
                utterance = self.stt.transcribe(audio)
                print("\n[VOICE DEBUG]")
                print(f"Transcript: {utterance.text!r}")
                print(f"Language: {utterance.language}")
                print(f"Confidence: {utterance.confidence}")
                logger.debug("Voice STT transcript=%r language=%s confidence=%s",
                             utterance.text, utterance.language, utterance.confidence)
            except Exception:
                logger.exception("Voice capture/transcription failed")
                return self._output(ChatResponse(success=False, intent="system",
                    response="I couldn't transcribe that. Please try again.",
                    session_id=self.session_id, error="STT_FAILED"))
            return self.handle_transcript(utterance.text)

    def run_voice_loop(self):
        """Interactive Push-to-Talk Voice Session CLI REPL."""
        print("=" * 60)
        print("JARVIS Voice Mode (Push-to-Talk)")
        print("Press ENTER to speak. Type 'exit' or press Ctrl+C to quit.")
        print("=" * 60)

        while True:
            try:
                inp = input("\n[ENTER to speak, 'q' to quit]: ").strip().lower()
                if inp in {"q", "quit", "exit"}:
                    print("Exiting JARVIS Voice Mode.")
                    break

                resp = self.listen_and_process()
                print(f"\nJARVIS: {resp.response}")

            except (KeyboardInterrupt, EOFError):
                print("\nExiting JARVIS Voice Mode.")
                break
            except Exception as e:
                logger.error(f"Voice loop error: {e}")
                print(f"Voice Error: {e}")
