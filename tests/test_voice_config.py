import unittest
from app.config.settings import (
    JARVIS_VOICE_ENABLED,
    JARVIS_STT_PROVIDER,
    JARVIS_STT_MODEL,
    JARVIS_STT_DEVICE,
    JARVIS_TTS_ENABLED,
    JARVIS_TTS_RATE,
    JARVIS_TTS_VOLUME,
)


class TestVoiceConfig(unittest.TestCase):

    def test_voice_settings_defaults(self):
        self.assertIsInstance(JARVIS_VOICE_ENABLED, bool)
        self.assertIsInstance(JARVIS_STT_PROVIDER, str)
        self.assertIsInstance(JARVIS_STT_MODEL, str)
        self.assertIsInstance(JARVIS_STT_DEVICE, str)
        self.assertIsInstance(JARVIS_TTS_ENABLED, bool)
        self.assertIsInstance(JARVIS_TTS_RATE, int)
        self.assertIsInstance(JARVIS_TTS_VOLUME, float)


if __name__ == "__main__":
    unittest.main()
