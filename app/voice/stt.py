import os
import inspect
from abc import ABC, abstractmethod
from typing import Optional, List, Union, Any
from app.config.settings import (
    JARVIS_STT_PROVIDER,
    JARVIS_STT_MODEL,
    JARVIS_STT_DEVICE,
    JARVIS_STT_LANGUAGE,
    JARVIS_STT_BEAM_SIZE,
    JARVIS_STT_TEMPERATURE,
    JARVIS_STT_CONDITION_ON_PREVIOUS_TEXT,
    JARVIS_STT_VAD_FILTER,
)
from app.voice.models import AudioData, TranscribedUtterance
from app.voice.microphone import Microphone
from app.utils.logger import logger
from app.voice.vocabulary import build_stt_vocabulary, vocabulary_hint_text

try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except Exception as _fw_err:
    FASTER_WHISPER_AVAILABLE = False
    logger.warning(f"faster-whisper library unavailable: {_fw_err}")


def get_stt_initial_prompt() -> str:
    """Fallback prompt for Whisper versions without native hotword support."""
    return "JARVIS assistant voice command. Technical vocabulary: " + vocabulary_hint_text()


class BaseSTT(ABC):
    """Abstract interface for Speech-to-Text engines."""

    @abstractmethod
    def transcribe(self, audio: Union[AudioData, str]) -> TranscribedUtterance:
        """Transcribe AudioData or a file path into a TranscribedUtterance."""
        pass


class FasterWhisperSTT(BaseSTT):
    """
    Local Speech-to-Text provider using faster-whisper.
    Runs locally on CPU or GPU without external cloud API dependencies.
    """

    def __init__(
        self,
        model_size: str = JARVIS_STT_MODEL,
        device: str = JARVIS_STT_DEVICE,
        compute_type: str = "int8",
        beam_size: int = JARVIS_STT_BEAM_SIZE,
        language: str = JARVIS_STT_LANGUAGE,
        temperature: float = JARVIS_STT_TEMPERATURE,
        condition_on_previous_text: bool = JARVIS_STT_CONDITION_ON_PREVIOUS_TEXT,
        vad_filter: bool = JARVIS_STT_VAD_FILTER,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = max(1, beam_size)
        self.language = language
        self.temperature = temperature
        self.condition_on_previous_text = condition_on_previous_text
        self.vad_filter = vad_filter
        self._model: Optional[Any] = None

    def _load_model(self) -> bool:
        if not FASTER_WHISPER_AVAILABLE:
            logger.error("Cannot load FasterWhisperSTT: faster-whisper is not installed.")
            return False

        if self._model is not None:
            return True

        try:
            logger.info(f"Loading faster-whisper model '{self.model_size}' on {self.device} ({self.compute_type})...")
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            logger.info(f"FasterWhisperSTT model '{self.model_size}' loaded successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to load faster-whisper model '{self.model_size}': {e}")
            # Try CPU fallback with float32 if int8 fails
            try:
                logger.info("Attempting CPU float32 fallback...")
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="float32")
                return True
            except Exception as fallback_err:
                logger.error(f"CPU fallback also failed: {fallback_err}")
                return False

    def transcribe(self, audio: Union[AudioData, str]) -> TranscribedUtterance:
        """Transcribe audio samples or WAV file path."""
        if audio is None:
            return TranscribedUtterance(text="", confidence=0.0)

        if not self._load_model():
            logger.warning("STT model unavailable, returning empty transcription.")
            return TranscribedUtterance(text="", confidence=0.0)

        temp_path: Optional[str] = None
        try:
            if isinstance(audio, str):
                target_file = audio
            elif isinstance(audio, AudioData):
                temp_path = Microphone.save_temp_wav(audio)
                target_file = temp_path
            else:
                return TranscribedUtterance(text="", confidence=0.0)

            if not target_file or not os.path.exists(target_file):
                return TranscribedUtterance(text="", confidence=0.0)

            vocabulary = build_stt_vocabulary()
            hint_text = ", ".join(vocabulary)
            try:
                supports_hotwords = "hotwords" in inspect.signature(self._model.transcribe).parameters
            except (TypeError, ValueError):
                supports_hotwords = False
            decode_options = {
                "beam_size": self.beam_size,
                "language": self.language,
                "vad_filter": self.vad_filter,
                "temperature": self.temperature,
                "condition_on_previous_text": self.condition_on_previous_text,
            }
            if supports_hotwords:
                decode_options["hotwords"] = hint_text
                decode_options["initial_prompt"] = "JARVIS assistant voice command."
            else:
                decode_options["initial_prompt"] = get_stt_initial_prompt()
            logger.debug(
                "STT decode model=%s beam_size=%d hotwords_supported=%s hints_used=%s hint_count=%d",
                self.model_size, self.beam_size, supports_hotwords, bool(vocabulary), len(vocabulary),
            )
            segments, info = self._model.transcribe(target_file, **decode_options)

            segments = list(segments)

            transcript_parts = [
                segment.text.strip()
                for segment in segments
                if segment.text and segment.text.strip()
            ]

            full_text = " ".join(transcript_parts).strip()

            # faster-whisper does not provide a simple global
            # transcription confidence value.
            # language_probability is safe metadata to read,
            # but it represents language detection confidence,
            # not transcript accuracy.
            language_probability = getattr(
                info,
                "language_probability",
                None
            )

            logger.info("STT completed model=%s language=%s language_probability=%s",
                        self.model_size, getattr(info, "language", "unknown"), language_probability)
            logger.debug("STT transcript=%r", full_text)

            return TranscribedUtterance(
                text=full_text,
                confidence=None,
                language=getattr(info, "language", "en"),
            )
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return TranscribedUtterance(text="", confidence=0.0)

        finally:
            if temp_path:
                Microphone.cleanup_temp_wav(temp_path)


class MockSTT(BaseSTT):
    """Mock STT engine for automated unit tests and deterministic offline testing."""

    def __init__(self, responses: Optional[List[str]] = None):
        self.responses = list(responses) if responses else []
        self.call_count = 0

    def queue_response(self, text: str):
        self.responses.append(text)

    def transcribe(self, audio: Union[AudioData, str]) -> TranscribedUtterance:
        self.call_count += 1
        if self.responses:
            text = self.responses.pop(0)
            return TranscribedUtterance(text=text, confidence=1.0)
        return TranscribedUtterance(text="", confidence=0.0)


def create_stt_provider(provider_name: str = JARVIS_STT_PROVIDER) -> BaseSTT:
    """Factory helper to instantiate STT provider based on configuration."""
    name = (provider_name or "").lower().strip()
    if name in {"faster_whisper", "faster-whisper", "whisper"}:
        return FasterWhisperSTT()
    elif name == "mock":
        return MockSTT()
    else:
        logger.warning(f"Unknown STT provider '{provider_name}', defaulting to FasterWhisperSTT.")
        return FasterWhisperSTT()
