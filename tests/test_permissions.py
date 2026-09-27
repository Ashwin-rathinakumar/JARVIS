import unittest
from app.brain.permissions import PermissionEngine, get_risk_level
from app.core.schemas import RiskLevel, PermissionDecision


class TestPermissions(unittest.TestCase):

    def test_risk_level_classifications(self):
        self.assertEqual(get_risk_level("system_information"), RiskLevel.READ_ONLY)
        self.assertEqual(get_risk_level("get_weather"), RiskLevel.READ_ONLY)
        self.assertEqual(get_risk_level("list_files"), RiskLevel.READ_ONLY)
        self.assertEqual(get_risk_level("search_projects"), RiskLevel.READ_ONLY)
        self.assertEqual(get_risk_level("open_application"), RiskLevel.LOW)
        self.assertEqual(get_risk_level("remember"), RiskLevel.LOW)
        self.assertEqual(get_risk_level("create_folder"), RiskLevel.MEDIUM)
        self.assertEqual(get_risk_level("write_text_file"), RiskLevel.MEDIUM)
        self.assertEqual(get_risk_level("delete_file"), RiskLevel.BLOCKED)
        self.assertEqual(get_risk_level("raw_shell"), RiskLevel.BLOCKED)
        self.assertEqual(get_risk_level("powershell"), RiskLevel.BLOCKED)
        self.assertEqual(get_risk_level("cmd"), RiskLevel.BLOCKED)

    def test_read_only_auto_allow(self):
        decision, reason = PermissionEngine.evaluate("system_information", {})
        self.assertEqual(decision, PermissionDecision.ALLOW)
        self.assertIsNone(reason)

        decision, reason = PermissionEngine.evaluate("get_weather", {"location": "Chennai"})
        self.assertEqual(decision, PermissionDecision.ALLOW)
        self.assertIsNone(reason)

    def test_low_risk_auto_allow(self):
        decision, reason = PermissionEngine.evaluate("open_application", {"app": "notepad"})
        self.assertEqual(decision, PermissionDecision.ALLOW)

    def test_medium_risk_requires_confirmation(self):
        decision, reason = PermissionEngine.evaluate("create_folder", {"folder_path": "workspace/test_folder"})
        self.assertEqual(decision, PermissionDecision.CONFIRM)
        self.assertIsNotNone(reason)

    def test_medium_risk_confirmed_allows(self):
        decision, reason = PermissionEngine.evaluate("create_folder", {"folder_path": "workspace/test_folder"}, confirmed=True)
        self.assertEqual(decision, PermissionDecision.ALLOW)

    def test_blocked_tools_denied(self):
        blocked = ["delete_file", "format_disk", "disable_security", "raw_shell", "eval_code", "cmd", "powershell"]
        for tool in blocked:
            decision, reason = PermissionEngine.evaluate(tool, {})
            self.assertEqual(decision, PermissionDecision.DENY, f"Failed to deny blocked tool: {tool}")
            self.assertIn("blocked", reason.lower())

    def test_path_traversal_denied(self):
        decision, reason = PermissionEngine.evaluate("read_text_file", {"filepath": "../../windows/system.ini"})
        self.assertEqual(decision, PermissionDecision.DENY)
        self.assertIn("path traversal", reason.lower())

    def test_blocked_script_extensions_denied(self):
        dangerous = ["script.ps1", "run.bat", "exec.cmd", "payload.vbs", "virus.exe", "test.dll"]
        for fn in dangerous:
            decision, reason = PermissionEngine.evaluate("write_text_file", {"filepath": fn, "content": "bad"})
            self.assertEqual(decision, PermissionDecision.DENY, f"Failed to deny script extension: {fn}")
            self.assertIn("blocked", reason.lower())

    def test_shell_syntax_in_application_name_denied(self):
        decision, reason = PermissionEngine.evaluate("open_application", {"app": "notepad & calc"})
        self.assertEqual(decision, PermissionDecision.DENY)
        self.assertIn("prohibited", reason.lower())


if __name__ == "__main__":
    unittest.main()
