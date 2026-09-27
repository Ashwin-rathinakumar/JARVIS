import unittest
from unittest.mock import MagicMock, patch

from app.projects.resolver import extract_project_candidate, project_resolver, normalize_project_name
from app.brain.intent import classify_intent_deterministic
from app.config.projects import PROJECTS
from app.voice.runtime import VoiceRuntime
from app.voice.stt import MockSTT
from app.voice.tts import MockTTS
from app.brain.orchestrator import JarvisOrchestrator
from app.state.session import session_manager


class TestVoiceProjectPipeline(unittest.TestCase):

    def setUp(self):
        from app.projects.lifecycle import project_lifecycle
        project_lifecycle.states.clear()
        for mocked in [patch('app.tools.projects.subprocess.Popen'),
                       patch.object(project_lifecycle, 'wait_until_open', return_value=True)]:
            mocked.start()
            self.addCleanup(mocked.stop)
        self.mock_brain = MagicMock()
        self.mock_brain.ask.return_value = "Mock LLM answer"
        self.orchestrator = JarvisOrchestrator(brain=self.mock_brain)
        self.mock_stt = MockSTT()
        self.mock_tts = MockTTS()
        self.session_id = f"test-voice-pipeline-{self._testMethodName}"
        session_manager.delete_session(self.session_id)
        self.runtime = VoiceRuntime(
            orchestrator=self.orchestrator,
            stt=self.mock_stt,
            tts=self.mock_tts,
            session_id=self.session_id,
        )

    def test_candidate_extraction_normalization(self):
        test_cases = [
            ("sentinel ai project.", "sentinel ai"),
            ("project sentinel ai", "sentinel ai"),
            ("the sentinel ai project", "sentinel ai"),
            ("ker project.", "ker"),
            ("key project.", "key"),
            ("K-E-R project.", "K-E-R"),
            ("Open Sentinel AI", "Sentinel AI"),
            ("Open Sentinel AI Project", "Sentinel AI"),
            ("Open Sentinel AI Project.", "Sentinel AI"),
            ("Open, Sentinel AI project.", "Sentinel AI"),
            ("Open KER project.", "KER"),
            ("Open Streetlight Project.", "Streetlight"),
            ("Open project named keer", "keer"),
            ("Open keer project name", "keer"),
            ("Open the K.E.E.R. workspace", "K.E.E.R"),
        ]
        for input_text, expected_candidate in test_cases:
            candidate = extract_project_candidate(input_text)
            self.assertEqual(
                (candidate.lower() if candidate else None),
                expected_candidate.lower(),
                f"Candidate extraction failed for '{input_text}'. Got '{candidate}', expected '{expected_candidate}'"
            )

    def test_contextual_wrapper_normalization(self):
        wrapper_cases = [
            ("Sentinel AI", "sentinel ai"),
            ("Sentinel AI Project", "sentinel ai"),
            ("Sentinel AI Project.", "sentinel ai"),
            ("the Sentinel AI project", "sentinel ai"),
            ("project Sentinel AI", "sentinel ai"),
            ("KER", "ker"),
            ("KER project", "ker"),
            ("KER project.", "ker"),
            ("K-E-R project", "k e r"),
            ("key project.", "key"),
            ("project named keer", "keer"),
            ("keer project name", "keer"),
            ("the K.E.E.R. workspace", "keer"),
        ]
        for input_text, expected_norm in wrapper_cases:
            norm = normalize_project_name(input_text)
            self.assertEqual(
                norm,
                expected_norm,
                f"Defensive normalization failed for '{input_text}'. Got '{norm}', expected '{expected_norm}'"
            )

    def test_punctuation_tolerant_intent_routing(self):
        routing_cases = [
            ("Open Sentinel AI", "Sentinel AI"),
            ("Open Sentinel AI Project", "Sentinel AI"),
            ("Open Sentinel AI Project.", "Sentinel AI"),
            ("Open, Sentinel AI project.", "Sentinel AI"),
            ("Open KER", "K.E.E.R."),
            ("Open KER project", "K.E.E.R."),
            ("Open KER project.", "K.E.E.R."),
            ("Open K-E-R project", "K.E.E.R."),
            ("Open key project.", "K.E.E.R."),
            ("Open Streetlight", "Streetlight Fault Reporting System"),
            ("Open Streetlight Project.", "Streetlight Fault Reporting System"),
            ("open project named keer", "K.E.E.R."),
            ("open keer project name", "K.E.E.R."),
            ("open the K.E.E.R. workspace", "K.E.E.R."),
        ]
        for phrase, expected_canonical in routing_cases:
            decision = classify_intent_deterministic(phrase)
            self.assertIsNotNone(decision, f"Deterministic intent classification failed for '{phrase}'")
            self.assertEqual(decision["intent"], "tool", f"Intent for '{phrase}' was not 'tool'")
            self.assertEqual(decision["tool"], "open_project", f"Tool for '{phrase}' was not 'open_project'")
            res = project_resolver.resolve(decision["arguments"]["project_name"])
            self.assertTrue(res.matched, f"Project resolution failed for candidate '{decision['arguments']['project_name']}'")
            self.assertEqual(res.canonical_name, expected_canonical, f"Canonical mismatch for phrase '{phrase}'")

    def test_required_project_open_variations_resolve_to_canonical_keys(self):
        cases = {
            "open keer": "keer",
            "open keer project": "keer",
            "open K.E.E.R.": "keer",
            "open K E E R": "keer",
            "open the keer project": "keer",
            "open project named keer": "keer",
            "open keer project name": "keer",
            "open the K.E.E.R. workspace": "keer",
            "open sentinel project": "sentinel",
            "open streetlight project": "streetlight",
            "open jarvis project": "jarvis",
        }
        for phrase, expected_key in cases.items():
            with self.subTest(phrase=phrase):
                decision = classify_intent_deterministic(phrase)
                self.assertEqual(decision["intent"], "tool")
                self.assertEqual(decision["tool"], "open_project")
                resolution = project_resolver.resolve(decision["arguments"]["project_name"])
                self.assertTrue(resolution.matched)
                self.assertEqual(resolution.project_key, expected_key)

    def test_unknown_project_remains_truthful_not_found(self):
        response = self.runtime.handle_transcript("open MoonBase project name")
        self.assertFalse(response.success)
        self.assertIn("don't know the project", response.response.lower())

    def test_no_placeholder_project_resolution(self):
        placeholder_inputs = ["Open project", "Open new project", "Open a project", "Open project."]
        for phrase in placeholder_inputs:
            candidate = extract_project_candidate(phrase)
            self.assertIsNone(candidate, f"Candidate extraction should return None for generic placeholder '{phrase}'")

            decision = classify_intent_deterministic(phrase)
            if decision:
                # Should not route to open_project with "New Project"
                target = decision.get("arguments", {}).get("project_name")
                self.assertNotEqual(target, "New Project")
                self.assertNotEqual(target, "project")

    def test_ordinary_word_safety(self):
        phrase = "press the key"
        candidate = extract_project_candidate(phrase)
        # Should not resolve to K.E.E.R. in general chat
        decision = classify_intent_deterministic(phrase)
        if decision:
            self.assertNotEqual(decision.get("tool"), "open_project")

    def test_end_to_end_mock_voice_project_opening(self):
        transcripts = [
            ("open k.e.e.r. project", "K.E.E.R."),
            ("open sentinel ai project.", "Sentinel AI"),
            ("open streetlight project.", "Streetlight Fault Reporting System"),
            ("open key project.", "K.E.E.R."),
            ("open ker project.", "K.E.E.R."),
        ]
        for transcript, expected_canonical in transcripts:
            resp = self.runtime.handle_transcript(transcript)
            self.assertTrue(resp.success, f"End-to-end voice processing failed for '{transcript}': {resp.response}")
            self.assertEqual(resp.intent, "project")
            self.assertIn(expected_canonical, resp.response, f"Response '{resp.response}' did not contain expected canonical name '{expected_canonical}'")


if __name__ == "__main__":
    unittest.main()
