import unittest
from pathlib import Path

from app.brain.permissions import PermissionEngine, get_risk_level
from app.core.schemas import RiskLevel, PermissionDecision
from app.tools.registry import execute_tool, get_tool
from app.tools.files import write_text_file, read_text_file, create_directory
from app.tools.apps import open_application


class TestSecurityPhase3(unittest.TestCase):

    def test_raw_shell_and_eval_tools_blocked(self):
        blocked_commands = [
            "cmd",
            "powershell",
            "raw_shell",
            "eval_code",
            "system_exec",
            "format_disk",
            "disable_security",
            "delete_file",
        ]
        for cmd in blocked_commands:
            self.assertEqual(get_risk_level(cmd), RiskLevel.BLOCKED)
            decision, reason = PermissionEngine.evaluate(cmd, {"command": "whoami"})
            self.assertEqual(decision, PermissionDecision.DENY)
            self.assertIn("blocked", reason.lower())

            # Attempt executing through registry
            res = execute_tool(cmd, {"command": "whoami"})
            self.assertFalse(res.success)

    def test_blocked_executable_file_extensions(self):
        dangerous_extensions = [
            ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".scr",
            ".com", ".dll", ".jar", ".msi", ".pyc", ".sh", ".bash"
        ]
        for ext in dangerous_extensions:
            filename = f"malicious{ext}"
            decision, reason = PermissionEngine.evaluate("write_text_file", {"filepath": filename, "content": "malware"})
            self.assertEqual(decision, PermissionDecision.DENY, f"Allowed blocked extension {ext}")
            self.assertIn("blocked", reason.lower())

            # Direct tool invocation must also refuse
            res = write_text_file(filename, "malware")
            self.assertIn("Access denied", res)

    def test_path_traversal_and_system32_access_denied(self):
        restricted_paths = [
            "C:/Windows/System32/drivers/etc/hosts",
            "C:\\Windows\\System32\\cmd.exe",
            "../../etc/passwd",
            "..\\..\\Windows\\win.ini",
        ]
        for path in restricted_paths:
            decision, reason = PermissionEngine.evaluate("read_text_file", {"filepath": path})
            # Should be either denied at permission engine or path check
            res = read_text_file(path)
            self.assertIn("Access denied", res, f"Path {path} was not blocked!")

    def test_protected_environment_directories_denied(self):
        protected_targets = [
            "C:/JARVIS/.git/hooks/pre-commit",
            "C:/JARVIS/venv/Scripts/python.exe",
            "C:/JARVIS/node_modules/payload.js",
        ]
        for target in protected_targets:
            decision, reason = PermissionEngine.evaluate("write_text_file", {"filepath": target, "content": "bad"})
            self.assertEqual(decision, PermissionDecision.DENY)

    def test_shell_injection_prevention_in_app_launcher(self):
        injections = [
            "notepad & calc",
            "calc | whoami",
            "notepad; echo pwned",
            "calc `dir`",
            "calc $(whoami)",
            "calc > out.txt",
        ]
        for injection in injections:
            decision, reason = PermissionEngine.evaluate("open_application", {"app": injection})
            self.assertEqual(decision, PermissionDecision.DENY)
            self.assertIn("prohibited", reason.lower())


if __name__ == "__main__":
    unittest.main()
