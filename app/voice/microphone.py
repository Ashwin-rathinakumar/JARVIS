import os
import sys
import time
import tempfile
import wave
from typing import Optional
from app.config.settings import JARVIS_SAMPLE_RATE
from app.voice.models import AudioData
from app.utils.logger import logger

try:
    import sounddevice as sd
    import numpy as np
    SOUNDDEVICE_AVAILABLE = True
except Exception as _sd_err:
    SOUNDDEVICE_AVAILABLE = False
    logger.warning(f"Audio device capture library unavailable: {_sd_err}")


class Microphone:
    """
    Push-to-Talk Windows microphone capture.
    Captures audio safely without crashing if hardware or drivers are absent.
    """

    def __init__(self, sample_rate: int = JARVIS_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.is_recording = False
        self._recording_buffers = []

    def is_device_available(self) -> bool:
        """Check if a default input microphone device is accessible."""
        if not SOUNDDEVICE_AVAILABLE:
            return False
        try:
            devices = sd.query_devices()
            default_in = sd.default.device[0]
            if default_in is not None and default_in >= 0:
                return True
            # Fallback: check if any device has max_input_channels > 0
            for d in devices:
                if d.get("max_input_channels", 0) > 0:
                    return True
        except Exception as e:
            logger.debug(f"Device query check failed: {e}")
        return False

    def capture_push_to_talk(self, duration: Optional[float] = None) -> Optional[AudioData]:
        """
        Record audio from default input device until user stops or duration expires.
        If interactive keyboard input is available, press ENTER to start and ENTER to stop.
        """
        if not self.is_device_available():
            logger.warning("No microphone input device available.")
            return None

        logger.info("Starting Push-to-Talk recording...")
        frames = []

        def callback(indata, frame_count, time_info, status):
            if status:
                logger.debug(f"Microphone status callback: {status}")
            frames.append(indata.copy())

        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                callback=callback,
            )
            with stream:
                self.is_recording = True
                if duration is not None and duration > 0:
                    time.sleep(duration)
                else:
                    input("Press ENTER to stop recording...")

            if not frames:
                logger.warning("No audio frames recorded.")
                return None

            audio_samples = np.concatenate(frames, axis=0).flatten()
            return AudioData(samples=audio_samples, sample_rate=self.sample_rate, channels=1)

        except Exception as e:
            logger.error(f"Microphone capture failed: {e}")
            return None
        finally:
            self.is_recording = False

    def close(self) -> None:
        """Release runtime-owned capture state; active streams use context cleanup."""
        self.is_recording = False
        self._recording_buffers.clear()

    @staticmethod
    def save_temp_wav(audio_data: AudioData) -> Optional[str]:
        """
        Safely write audio buffer to a temporary WAV file in the OS temp directory.
        Returns temporary filepath string.
        """
        if audio_data is None or audio_data.samples is None:
            return None

        temp_path = None
        try:
            temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_path = temp_file.name
            temp_file.close()

            samples = audio_data.samples
            if hasattr(samples, "dtype") and samples.dtype == np.float32:
                # Convert float32 [-1.0, 1.0] to int16 PCM
                int16_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
                bytes_data = int16_samples.tobytes()
            elif isinstance(samples, bytes):
                bytes_data = samples
            else:
                bytes_data = np.array(samples, dtype=np.int16).tobytes()

            with wave.open(temp_path, "wb") as wf:
                wf.setnchannels(audio_data.channels)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(audio_data.sample_rate)
                wf.writeframes(bytes_data)

            return temp_path

        except Exception as e:
            logger.error(f"Failed to create temporary WAV file: {e}")
            Microphone.cleanup_temp_wav(temp_path)
            return None

    @staticmethod
    def cleanup_temp_wav(filepath: Optional[str]) -> None:
        """Safely delete temporary audio file from OS temp directory."""
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                logger.debug(f"Failed to remove temp wav '{filepath}': {e}")
