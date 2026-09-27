import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from app.config.projects import PROJECTS, resolve_project_key
from app.tools.projects import (
    find_vscode_launcher,
    open_project,
    run_project,
    stop_project,
    list_projects,
    get_current_project,
    get_project_status,
)
from app.state.session import session


class TestProjectManagement(unittest.TestCase):

    def setUp(self):
        session.clear()
        from app.projects.lifecycle import project_lifecycle
        project_lifecycle.states.clear()
        ready = patch.object(project_lifecycle, 'wait_until_open', return_value=True)
        ready.start()
        self.addCleanup(ready.stop)

    def tearDown(self):
        session.clear()

    def test_project_registry_entries(self):
        self.assertIn("jarvis", PROJECTS)
        self.assertIn("keer", PROJECTS)
        # Ensure KEER path matches expected location without being modified
        self.assertIn("keer", PROJECTS["keer"]["path"].lower())

    def test_alias_resolution(self):
        self.assertEqual(resolve_project_key("keer"), "keer")
        self.assertEqual(resolve_project_key("k.e.e.r."), "keer")
        self.assertEqual(resolve_project_key("keer project"), "keer")
        self.assertEqual(resolve_project_key("my keer project"), "keer")
        self.assertEqual(resolve_project_key("jarvis"), "jarvis")
        self.assertEqual(resolve_project_key("j.a.r.v.i.s"), "jarvis")
        self.assertEqual(resolve_project_key("unknown_project"), None)

    def test_vscode_launcher_discovery(self):
        launcher = find_vscode_launcher()
        self.assertIsNotNone(launcher)
        cmd, use_shell = launcher
        self.assertTrue(len(cmd) > 0)
        self.assertIsInstance(use_shell, bool)

    @patch("subprocess.Popen")
    def test_open_project_success(self, mock_popen):
        # Open JARVIS project
        result = open_project("jarvis")
        self.assertIn("Opened JARVIS in VS Code", result)
        mock_popen.assert_called_once()
        self.assertEqual(session.get_current_project(), "jarvis")

    def test_open_unknown_project(self):
        result = open_project("non_existent_xyz")
        self.assertIn("I don't know the project", result)

    @patch("subprocess.Popen")
    def test_run_and_stop_project(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_proc.poll.return_value = None  # Process running
        mock_popen.return_value = mock_proc

        # Run project
        result = run_project("jarvis")
        self.assertIn("Started JARVIS (PID: 9999)", result)
        self.assertIn("jarvis", session.list_active_processes())

        # Stop project
        stop_result = stop_project("jarvis")
        self.assertIn("Stopped JARVIS", stop_result)
        mock_proc.terminate.assert_called_once()
        self.assertNotIn("jarvis", session.list_active_processes())

    def test_list_projects(self):
        listing = list_projects()
        self.assertIn("JARVIS [jarvis]", listing)
        self.assertIn("K.E.E.R. [keer]", listing)

    def test_current_project(self):
        self.assertEqual(get_current_project(), "No project is currently active.")
        session.set_current_project("jarvis")
        self.assertEqual(get_current_project(), "Current project is JARVIS.")


if __name__ == "__main__":
    unittest.main()
