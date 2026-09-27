import unittest
from unittest.mock import MagicMock, patch

from app.projects.resolver import ProjectResolver, ProjectResolution, normalize_project_name, project_resolver
from app.config.projects import PROJECTS, resolve_project_key
from app.brain.intent import classify_intent_deterministic
from app.voice.runtime import VoiceRuntime
from app.voice.stt import MockSTT
from app.voice.tts import MockTTS
from app.brain.orchestrator import JarvisOrchestrator
from app.state.session import session_manager


class TestProjectResolver(unittest.TestCase):

    def setUp(self):
        self.test_projects = {
            "jarvis": {
                "name": "JARVIS",
                "path": r"C:\JARVIS",
                "aliases": ["jarvis", "j.a.r.v.i.s"],
            },
            "keer": {
                "name": "K.E.E.R.",
                "path": r"C:\Users\Ashwin Rathinakumar\Downloads\Forge (1)\keer",
                "aliases": ["keer", "k e e r", "k-e-e-r", "key", "ker"],
            },
            "sentinel": {
                "name": "Sentinel AI",
                "path": r"C:\JARVIS\workspace\sentinel",
                "aliases": ["sentinel", "sentinel ai"],
            },
            "streetlight": {
                "name": "Streetlight Fault Reporting System",
                "path": r"C:\JARVIS\workspace\streetlight",
                "aliases": ["streetlight system", "streetlight fault reporting system"],
            },
        }
        self.resolver = ProjectResolver(projects_registry=self.test_projects)

    def test_exact_canonical_match(self):
        res = self.resolver.resolve("JARVIS")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "JARVIS")
        self.assertEqual(res.project_key, "jarvis")

    def test_case_insensitive_match(self):
        res = self.resolver.resolve("jarvis")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "JARVIS")
        self.assertEqual(res.project_key, "jarvis")

    def test_punctuation_match(self):
        res = self.resolver.resolve("K.E.E.R.")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "K.E.E.R.")
        self.assertEqual(res.project_key, "keer")

    def test_acronym_spacing_match(self):
        res = self.resolver.resolve("K E E R")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "K.E.E.R.")
        self.assertEqual(res.project_key, "keer")

    def test_acronym_hyphen_match(self):
        res = self.resolver.resolve("K-E-E-R")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "K.E.E.R.")
        self.assertEqual(res.project_key, "keer")

    def test_compact_match(self):
        res = self.resolver.resolve("KEER")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "K.E.E.R.")
        self.assertEqual(res.project_key, "keer")

    def test_explicit_stt_alias_key(self):
        res = self.resolver.resolve("key")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "K.E.E.R.")
        self.assertEqual(res.project_key, "keer")

    def test_explicit_stt_alias_ker(self):
        res = self.resolver.resolve("ker")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "K.E.E.R.")
        self.assertEqual(res.project_key, "keer")

    def test_contextual_prefix_stripping(self):
        res = self.resolver.resolve("open project key")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "K.E.E.R.")

        res2 = self.resolver.resolve("the project Sentinel AI")
        self.assertTrue(res2.matched)
        self.assertEqual(res2.canonical_name, "Sentinel AI")

    def test_contextual_project_fillers_are_anchored_and_normalized(self):
        cases = [
            "keer project",
            "the keer project",
            "project named keer",
            "project called keer",
            "keer project name",
            "the K.E.E.R. workspace",
            "the keer folder",
            "the keer repo",
            "the keer repository",
        ]
        for phrase in cases:
            with self.subTest(phrase=phrase):
                res = self.resolver.resolve(phrase)
                self.assertTrue(res.matched)
                self.assertEqual(res.project_key, "keer")

    def test_forge_alias_resolves_only_in_project_resolution(self):
        res = project_resolver.resolve("forge")
        self.assertTrue(res.matched)
        self.assertEqual(res.project_key, "keer")

        decision = classify_intent_deterministic("open forge")
        self.assertEqual(decision["tool"], "open_project")
        self.assertEqual(resolve_project_key(decision["arguments"]["project_name"]), "keer")

        conversational = classify_intent_deterministic("forge the metal")
        if conversational:
            self.assertNotEqual(conversational.get("tool"), "open_project")

    def test_typo_fuzzy_match(self):
        res = self.resolver.resolve("sentinal ai")
        self.assertTrue(res.matched)
        self.assertEqual(res.canonical_name, "Sentinel AI")
        self.assertEqual(res.project_key, "sentinel")

    def test_unknown_project(self):
        res = self.resolver.resolve("banana engine")
        self.assertFalse(res.matched)
        self.assertFalse(res.ambiguous)
        self.assertIn("don't know", res.message.lower())

    def test_ambiguous_projects_detection(self):
        ambiguous_registry = {
            "sentinel_ai": {
                "name": "Sentinel AI",
                "path": r"C:\sentinel_ai",
                "aliases": ["sentinel"],
            },
            "sentinel_dashboard": {
                "name": "Sentinel Dashboard",
                "path": r"C:\sentinel_dashboard",
                "aliases": ["sentinel"],
            },
        }
        r = ProjectResolver(projects_registry=ambiguous_registry)
        res = r.resolve("Sentinel")
        self.assertFalse(res.matched)
        self.assertTrue(res.ambiguous)
        self.assertIn("Sentinel AI", res.candidates)
        self.assertIn("Sentinel Dashboard", res.candidates)
        self.assertIn("more than one matching project", res.message)

    def test_common_word_safety_no_global_replacement(self):
        raw_sentence = "press the key"
        # Verify normal string operations do NOT corrupt raw sentence
        norm = normalize_project_name(raw_sentence)
        self.assertEqual(raw_sentence, "press the key")
        self.assertNotEqual(norm, "K.E.E.R.")

        # Intent classification of general sentence must not route to project
        intent = classify_intent_deterministic(raw_sentence)
        if intent:
            self.assertNotEqual(intent.get("tool"), "open_project")


class TestProjectIntegration(unittest.TestCase):

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
        self.session_id = f"test-project-integ-{self._testMethodName}"
        session_manager.delete_session(self.session_id)
        self.runtime = VoiceRuntime(
            orchestrator=self.orchestrator,
            stt=self.mock_stt,
            tts=self.mock_tts,
            session_id=self.session_id,
        )

    def test_intent_classification_for_project_phrases(self):
        phrases = [
            ("open K.E.E.R.", "keer"),
            ("open K E E R", "keer"),
            ("open k-e-e-r", "keer"),
            ("open keer", "keer"),
            ("open project key", "keer"),
            ("open sentinal ai", "sentinel"),
            ("open jarvis", "jarvis"),
            ("open project streetlight", "streetlight"),
        ]
        for phrase, expected_key in phrases:
            decision = classify_intent_deterministic(phrase)
            self.assertIsNotNone(decision, f"Failed to match intent for '{phrase}'")
            self.assertEqual(decision["intent"], "tool")
            self.assertEqual(decision["tool"], "open_project")
            resolved_key = resolve_project_key(decision["arguments"]["project_name"])
            self.assertEqual(resolved_key, expected_key, f"Failed key resolution for phrase '{phrase}'")

    def test_voice_runtime_project_opening_flow(self):
        # Test simulated STT output "open project key" through voice runtime
        resp = self.runtime.handle_transcript("open project key")
        self.assertTrue(resp.success)
        self.assertEqual(resp.intent, "project")
        self.assertIn("K.E.E.R.", resp.response)


if __name__ == "__main__":
    unittest.main()
