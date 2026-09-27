import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import uuid

from app.voice.tts import Pyttsx3TTS, create_tts_provider, MockTTS
from app.voice.tts_worker import speak_once
from app.voice.runtime import VoiceRuntime
from app.voice.stt import MockSTT, FasterWhisperSTT
from app.voice.models import AudioData
from app.voice.microphone import Microphone
from app.brain.orchestrator import JarvisOrchestrator
from app.brain.intent import classify_intent_deterministic
from app.projects.lifecycle import ProjectLifecycle
from app.projects.resolver import ProjectResolver
from app.tools.registry import execute_tool
from app.tools.projects import open_project, close_project


class ReliabilityTests(unittest.TestCase):
    def runtime(self, tts=None):
        mic = MagicMock()
        mic.capture_push_to_talk.return_value = AudioData(b'\0\0' * 100)
        return VoiceRuntime(orchestrator=JarvisOrchestrator(brain=MagicMock()), microphone=mic,
                            stt=MockSTT(['system information'] * 8), tts=tts or MockTTS(),
                            session_id='reliability-' + uuid.uuid4().hex)

    def test_five_commands_one_runtime(self):
        runtime = self.runtime()
        for _ in range(5):
            self.assertTrue(runtime.listen_and_process().success)
        self.assertEqual(len(runtime.tts.spoken_messages), 5)
        self.assertEqual(runtime.stt.call_count, 5)

    def test_false_and_exception_visible_then_recovery(self):
        tts = MagicMock()
        tts.speak.side_effect = [True, RuntimeError('broken'), False, True, True]
        runtime = self.runtime(tts)
        for expected in [True, False, False, True, True]:
            self.assertTrue(runtime.listen_and_process().success)
            self.assertEqual(runtime.last_tts_succeeded, expected)
        self.assertEqual(tts.speak.call_count, 5)
        self.assertEqual(runtime.tts_failures, 0)

    @patch('app.voice.tts.subprocess.run')
    def test_worker_timeout_recovery_and_acknowledgement(self, run):
        run.side_effect = [subprocess.TimeoutExpired('worker', 1),
                           SimpleNamespace(returncode=0, stdout='TTS_COMPLETED\n', stderr=''),
                           SimpleNamespace(returncode=0, stdout='', stderr='')]
        tts = Pyttsx3TTS(enabled=True)
        self.assertFalse(tts.speak('one'))
        self.assertTrue(tts.speak('two'))
        self.assertFalse(tts.speak('three'))
        self.assertFalse(run.call_args.kwargs['shell'])
        self.assertIn('timeout', run.call_args.kwargs)

    def test_worker_requires_real_finished_callback(self):
        engine = MagicMock()
        with self.assertRaises(RuntimeError):
            speak_once(dict(text='test', rate=175, volume=1), lambda: engine)
        engine.stop.assert_called_once()
        callbacks = {}
        engine.connect.side_effect = lambda name, cb: callbacks.update({name: cb})
        engine.runAndWait.side_effect = lambda: callbacks['finished-utterance']('response', True)
        speak_once(dict(text='test', rate=175, volume=1), lambda: engine)

    def test_factory_never_silently_uses_mock(self):
        self.assertIsInstance(create_tts_provider(), Pyttsx3TTS)
        self.assertFalse(create_tts_provider(False).speak('disabled'))

    def test_capture_and_stt_exceptions_spoken_once(self):
        runtime = self.runtime()
        runtime.microphone.capture_push_to_talk.side_effect = RuntimeError('device')
        self.assertFalse(runtime.listen_and_process().success)
        self.assertEqual(len(runtime.tts.spoken_messages), 1)
        runtime.microphone.capture_push_to_talk.side_effect = None
        runtime.stt.transcribe = MagicMock(side_effect=RuntimeError('STT'))
        self.assertFalse(runtime.listen_and_process().success)
        self.assertEqual(len(runtime.tts.spoken_messages), 2)

    def test_stt_model_reused_confidence_unknown_and_wav_cleaned(self):
        stt = FasterWhisperSTT()
        stt._model = MagicMock()
        stt._model.transcribe.return_value = ([SimpleNamespace(text='hello')], SimpleNamespace(language='en'))
        with patch('app.voice.stt.FASTER_WHISPER_AVAILABLE', True), tempfile.NamedTemporaryFile(suffix='.wav') as wav:
            with patch.object(Microphone, 'save_temp_wav', return_value=wav.name), patch.object(Microphone, 'cleanup_temp_wav') as cleanup:
                for _ in range(2):
                    self.assertIsNone(stt.transcribe(AudioData(b'00')).confidence)
                self.assertEqual(cleanup.call_count, 2)
                stt._model.transcribe.side_effect = RuntimeError('decode')
                stt.transcribe(AudioData(b'00'))
                self.assertEqual(cleanup.call_count, 3)

    def test_confirmation_punctuation_still_uses_token(self):
        runtime = self.runtime()
        response = runtime.handle_transcript('run JARVIS')
        self.assertEqual(response.status, 'confirmation_required')
        with patch('app.tools.projects.subprocess.Popen') as launch:
            response = runtime.handle_transcript('No.')
            self.assertIn('cancel', response.response.lower())
            launch.assert_not_called()


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.backend = MagicMock()
        self.manager = ProjectLifecycle(self.backend)
        self.proc = MagicMock(pid=123)
        self.proc.poll.return_value = None
        self.path = Path('C:/JARVIS').resolve()
        self.profile = self.manager.new_profile()
        self.backend.identity.return_value = (123.5, ['Code.exe', '--user-data-dir', str(self.profile), str(self.path)])
        self.backend.windows.return_value = [456]
        self.manager.track('jarvis', 'JARVIS', self.path, self.profile, self.proc)

    def test_open_close_state(self):
        self.assertTrue(self.manager.states['jarvis'].opened_by_jarvis)
        self.backend.request_close.side_effect = lambda *_: setattr(self.backend.windows, 'return_value', [])
        success, _ = self.manager.close('jarvis', self.path)
        self.assertTrue(success)
        self.assertFalse(self.manager.states['jarvis'].open)
        self.proc.terminate.assert_not_called()
        self.proc.kill.assert_not_called()

    def test_unrelated_process_or_reused_pid_not_closed(self):
        for identity in [(999, ['Code.exe', '--user-data-dir', str(self.profile)]),
                         (123.5, ['Code.exe', '--user-data-dir', 'C:/unrelated']),
                         (123.5, ['Code.exe'])]:
            self.backend.identity.return_value = identity
            self.assertFalse(self.manager.close('jarvis', self.path)[0])
        self.backend.request_close.assert_not_called()

    def test_untracked_project_not_closed(self):
        self.assertFalse(self.manager.close('sentinel', self.path)[0])
        self.backend.request_close.assert_not_called()

    def test_multiple_windows_not_closed(self):
        self.backend.windows.return_value = [456, 789]
        self.assertFalse(self.manager.close('jarvis', self.path)[0])
        self.backend.request_close.assert_not_called()

    def test_unsaved_prompt_never_force_terminated(self):
        success, message = self.manager.close('jarvis', self.path, timeout=0)
        self.assertFalse(success)
        self.assertIn('unsaved', message)
        self.proc.kill.assert_not_called()
        self.proc.terminate.assert_not_called()

    def test_changed_registry_root_not_closed(self):
        self.assertFalse(self.manager.close('jarvis', Path('C:/other'))[0])
        self.backend.request_close.assert_not_called()

    def test_exited_editor_not_claimed_closed(self):
        self.proc.poll.return_value = 0
        success, message = self.manager.close('jarvis', self.path)
        self.assertFalse(success)
        self.assertIn('does not appear', message)

    def test_startup_requires_window_not_just_live_pid(self):
        self.backend.windows.return_value = []
        self.assertFalse(self.manager.wait_until_open('jarvis', timeout=0))
        self.backend.windows.return_value = [456]
        self.assertTrue(self.manager.wait_until_open('jarvis', timeout=0))

    def test_startup_reports_actual_update_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            state = self.manager.states['jarvis']
            state.profile = Path(folder)
            logdir = state.profile / 'logs' / 'test'
            logdir.mkdir(parents=True)
            (logdir / 'main.log').write_text('Error: Code is currently being updated.', encoding='utf-8')
            self.assertIn('currently being updated', self.manager.startup_failure('jarvis'))

    def test_closed_window_state_remains_closed(self):
        self.manager.states['jarvis'].open = False
        self.backend.windows.return_value = []
        self.assertFalse(self.manager.status('jarvis').open)


class ProjectPipelineTests(unittest.TestCase):
    def test_system_command_stt_sentence_punctuation(self):
        for phrase in ['Give me system information.', 'System info!', 'System information?']:
            self.assertEqual(classify_intent_deterministic(phrase)['tool'], 'system_information')

    def test_ambiguous_search_stops_dependent_open(self):
        registry = {'one': {'name': 'Shared One', 'path': 'C:/one'},
                    'two': {'name': 'Shared Two', 'path': 'C:/two'}}
        with patch('app.tools.projects.PROJECTS', registry), patch('app.tools.projects.JARVIS_ALLOWED_PATHS', []), patch('app.tools.projects.subprocess.Popen') as launch:
            result = JarvisOrchestrator(brain=MagicMock()).process('find shared and open it in code')
            self.assertFalse(result.success)
            self.assertIn('Which one', result.response)
            launch.assert_not_called()

    @patch('app.tools.projects.project_lifecycle')
    @patch('app.tools.projects.subprocess.Popen')
    def test_failed_startup_is_failed_tool_result(self, popen, lifecycle):
        lifecycle.status.return_value = None
        lifecycle.new_profile.return_value = Path('C:/JARVIS/data/editor-sessions/test')
        lifecycle.wait_until_open.return_value = False
        lifecycle.startup_failure.return_value = 'VS Code is currently being updated.'
        with patch('app.tools.projects.find_vscode_launcher', return_value=('C:/Code.exe', False)):
            result = execute_tool('open_project', {'project_name': 'JARVIS'})
        self.assertFalse(result.success)
        self.assertIn('being updated', result.message)

    def test_all_requested_phrases(self):
        for action in ['Open', 'Close']:
            for name in ['JARVIS', 'K.E.E.R.', 'KER project.', 'Sentinel AI Project.', ', Sentinel AI project.', 'Streetlight', 'K E E R']:
                with self.subTest(action=action, name=name):
                    decision = classify_intent_deterministic(action + ' ' + name)
                    self.assertEqual(decision['tool'], action.lower() + '_project')

    @patch('app.tools.projects.subprocess.Popen')
    def test_unknown_and_arbitrary_existing_directory_rejected(self, popen):
        for target in ['MoonBase', str(Path('app').resolve())]:
            self.assertFalse(execute_tool('open_project', {'project_name': target}).success)
            self.assertFalse(execute_tool('close_project', {'project_name': target}).success)
        popen.assert_not_called()

    def test_ambiguity_never_goes_to_llm_or_launch(self):
        resolver = ProjectResolver({'one': {'name': 'One', 'path': 'C:/one', 'aliases': ['shared']},
                                    'two': {'name': 'Two', 'path': 'C:/two', 'aliases': ['shared']}})
        brain = MagicMock()
        with patch('app.projects.resolver.project_resolver', resolver), patch('app.tools.projects.project_resolver', resolver), patch('app.tools.projects.subprocess.Popen') as launch:
            response = JarvisOrchestrator(brain=brain).process('Open shared')
            self.assertIn('Which one', response.response)
            self.assertFalse(response.success)
            brain.ask.assert_not_called()
            launch.assert_not_called()

    def test_eight_commands_through_one_runtime(self):
        backend = MagicMock()
        manager = ProjectLifecycle(backend)
        proc = MagicMock(pid=100)
        proc.poll.return_value = None
        active = []
        profile = None
        def launch(command, **kwargs):
            nonlocal profile
            profile = command[command.index('--user-data-dir') + 1]
            active[:] = [10]
            return proc
        backend.identity.side_effect = lambda _: (1, ['Code.exe', '--user-data-dir', profile])
        backend.windows.side_effect = lambda _: list(active)
        backend.request_close.side_effect = lambda *_: active.clear()
        runtime = ReliabilityTests().runtime()
        runtime.stt = MockSTT(['Give me system information', 'Open Streetlight', 'Close Streetlight',
                              'Open Sentinel AI', 'Close Sentinel AI', 'Open K E E R', 'Close K E E R',
                              'Give me system information'])
        with patch('app.tools.projects.project_lifecycle', manager), patch('app.tools.projects.subprocess.Popen', side_effect=launch), patch('app.tools.projects.find_vscode_launcher', return_value=('C:/Code.exe', False)):
            for _ in range(8):
                response = runtime.listen_and_process()
                self.assertTrue(response.success, response.response)
        self.assertEqual(len(runtime.tts.spoken_messages), 8)
        self.assertTrue(all(state.open is False for state in manager.states.values()))


if __name__ == '__main__':
    unittest.main()
