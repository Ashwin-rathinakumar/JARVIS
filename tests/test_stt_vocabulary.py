import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.voice.stt import FasterWhisperSTT, get_stt_initial_prompt
from app.voice.vocabulary import build_stt_vocabulary, vocabulary_hint_text


class NativeHotwordModel:
    def __init__(self, transcript="What is recursion?"):
        self.transcript = transcript
        self.kwargs = None

    def transcribe(self, audio, hotwords=None, initial_prompt=None, **kwargs):
        self.kwargs = {"hotwords": hotwords, "initial_prompt": initial_prompt, **kwargs}
        return [SimpleNamespace(text=self.transcript)], SimpleNamespace(language="en", language_probability=0.99)


class PromptOnlyModel:
    def __init__(self):
        self.kwargs = None

    def transcribe(self, audio, beam_size=5, language="en", vad_filter=True, temperature=0.0,
                   condition_on_previous_text=False, initial_prompt=None):
        self.kwargs = locals()
        return [SimpleNamespace(text="ordinary unchanged text")], SimpleNamespace(language="en")


class TestSTTVocabulary(unittest.TestCase):
    def test_technical_vocabulary_is_included(self):
        hints = build_stt_vocabulary()
        for term in ["JARVIS", "Python", "recursion", "FastAPI", "PostgreSQL", "Nemotron", "Ollama", "LangChain", "Qdrant"]:
            self.assertIn(term, hints)

    def test_registered_projects_and_aliases_are_dynamic(self):
        registry = {"alpha": {"name": "Alpha Engine", "aliases": ["A.E.", "alpha workspace"]}}
        with patch("app.config.projects.PROJECTS", registry):
            hints = build_stt_vocabulary(categories=["projects"])
        self.assertIn("Alpha Engine", hints)
        self.assertIn("A.E.", hints)
        self.assertIn("alpha workspace", hints)

    def test_duplicates_are_removed_case_insensitively(self):
        hints = build_stt_vocabulary(categories=["general"], custom_terms=["jarvis", "JARVIS", "Nemotron"])
        keys = [item.casefold().rstrip(".") for item in hints]
        self.assertEqual(len(keys), len(set(keys)))

    def test_vocabulary_is_bounded_by_count_and_characters(self):
        hints = build_stt_vocabulary(categories=[], custom_terms=[f"term-{i}" for i in range(100)], max_terms=7, max_chars=45)
        self.assertLessEqual(len(hints), 7)
        self.assertLessEqual(len(", ".join(hints)), 45)

    def test_native_hotwords_and_conservative_decoding_are_used(self):
        stt = FasterWhisperSTT(beam_size=4, temperature=0.0, condition_on_previous_text=False, vad_filter=True)
        stt._model = NativeHotwordModel()
        with patch("app.voice.stt.os.path.exists", return_value=True):
            result = stt.transcribe("voice.wav")
        self.assertEqual(result.text, "What is recursion?")
        self.assertIsNone(result.confidence)
        self.assertIn("recursion", stt._model.kwargs["hotwords"])
        self.assertEqual(stt._model.kwargs["beam_size"], 4)
        self.assertEqual(stt._model.kwargs["temperature"], 0.0)
        self.assertFalse(stt._model.kwargs["condition_on_previous_text"])

    def test_initial_prompt_fallback_for_api_without_hotwords(self):
        stt = FasterWhisperSTT()
        stt._model = PromptOnlyModel()
        with patch("app.voice.stt.os.path.exists", return_value=True):
            result = stt.transcribe("voice.wav")
        self.assertEqual(result.text, "ordinary unchanged text")
        self.assertIn("recursion", stt._model.kwargs["initial_prompt"])

    def test_no_global_replacement_and_aliases_are_context_only(self):
        for transcript in ["What is the question?", "Use the key variable."]:
            stt = FasterWhisperSTT()
            stt._model = NativeHotwordModel(transcript)
            with patch("app.voice.stt.os.path.exists", return_value=True):
                result = stt.transcribe("voice.wav")
            self.assertEqual(result.text, transcript)

    def test_fallback_prompt_uses_same_bounded_source(self):
        prompt = get_stt_initial_prompt()
        self.assertIn(vocabulary_hint_text(), prompt)


if __name__ == "__main__":
    unittest.main()
