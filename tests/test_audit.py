import unittest
from app.agent.audit import record_audit, get_recent_action_records, get_recent_actions, sanitize_payload
from app.core.schemas import RiskLevel, PermissionDecision


class TestAudit(unittest.TestCase):

    def test_sanitize_payload_redaction(self):
        payload = {
            "password": "super_secret_password",
            "api_key": "sk-1234567890abcdef",
            "normal_field": "public_data",
            "token": "bearer-secret-token",
        }
        sanitized = sanitize_payload(payload)
        self.assertIn("[REDACTED]", sanitized)
        self.assertNotIn("super_secret_password", sanitized)
        self.assertNotIn("sk-1234567890abcdef", sanitized)
        self.assertIn("public_data", sanitized)

    def test_record_and_query_audit(self):
        record_audit(
            tool="test_tool",
            risk_level=RiskLevel.READ_ONLY.value,
            permission_decision=PermissionDecision.ALLOW.value,
            arguments={"query": "hello"},
            success=True,
            session_id="test-audit-sess",
            message="Completed successfully",
        )

        records = get_recent_action_records(limit=5)
        self.assertGreaterEqual(len(records), 1)
        latest = records[0]
        self.assertEqual(latest.tool, "test_tool")
        self.assertEqual(latest.session_id, "test-audit-sess")
        self.assertEqual(latest.risk_level, "read_only")
        self.assertEqual(latest.permission_decision, "allow")
        self.assertTrue(latest.success)

    def test_get_recent_actions_tool(self):
        record_audit(
            tool="create_folder",
            risk_level=RiskLevel.MEDIUM.value,
            permission_decision=PermissionDecision.ALLOW.value,
            arguments={"folder_path": "workspace/demo"},
            success=True,
            session_id="test-summary-sess",
            message="Created folder: C:\\JARVIS\\workspace\\demo",
        )

        output = get_recent_actions(limit=5)
        self.assertIn("Recent Actions", output)
        self.assertIn("create_folder", output)


if __name__ == "__main__":
    unittest.main()
