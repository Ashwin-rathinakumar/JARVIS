from dataclasses import dataclass
from typing import Optional, Any
from datetime import datetime, timezone


@dataclass
class AudioData:
    """Encapsulates captured audio samples."""
    samples: Any  # numpy.ndarray or bytes
    sample_rate: int = 16000
    channels: int = 1

    @property
    def duration_seconds(self) -> float:
        try:
            if hasattr(self.samples, "shape"):
                return float(self.samples.shape[0]) / float(self.sample_rate)
            elif isinstance(self.samples, bytes):
                # 16-bit PCM (2 bytes per sample)
                return len(self.samples) / (self.sample_rate * 2)
        except Exception:
            pass
        return 0.0


@dataclass
class TranscribedUtterance:
    """Encapsulates Speech-to-Text output."""
    text: str
    confidence: Optional[float] = None
    language: str = "en"

    @property
    def is_empty(self) -> bool:
        return not bool(self.text and self.text.strip())


@dataclass
class PendingVoiceConfirmation:
    """Tracks active pending voice confirmation token."""
    token: str
    description: str
    plan_id: Optional[str] = None
    created_at: float = 0.0
