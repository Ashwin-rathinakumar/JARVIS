import unittest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from app.api.server import create_app
from app.memory.database import initialize_database, save_memory


class TestFastAPIServer(unittest.TestCase):

    def setUp(self):
        initialize_database()
        self.mock_brain = MagicMock()
        self.mock_brain.health_check.return_value = {
            "provider": "ollama",
            "connected": True,
            "model": "qwen2.5:1.5b",
        }
        self.mock_brain.ask.return_value = "Mocked LLM answer."
        self.app = create_app(brain=self.mock_brain)
        self.client = TestClient(self.app)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["provider"], "ollama")
        self.assertEqual(data["model"], "qwen2.5:1.5b")
        self.assertTrue(data["connected"])
        self.assertIn("OK", data["database"])

    def test_chat_endpoint_conversation(self):
        response = self.client.post(
            "/api/chat",
            json={"message": "Explain black holes", "session_id": "api-session-1"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["intent"], "chat")
        self.assertEqual(data["response"], "Mocked LLM answer.")
        self.assertEqual(data["session_id"], "api-session-1")

    def test_chat_endpoint_system_tool(self):
        response = self.client.post(
            "/api/chat",
            json={"message": "system info"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["intent"], "system")
        self.assertEqual(data["tool_used"], "system_information")
        self.assertIn("Operating System", data["response"])

    def test_list_tools_endpoint(self):
        response = self.client.get("/api/tools")
        self.assertEqual(response.status_code, 200)
        tools = response.json()
        self.assertIsInstance(tools, list)
        tool_names = [t["name"] for t in tools]
        self.assertIn("open_application", tool_names)
        self.assertIn("system_information", tool_names)
        self.assertIn("remember", tool_names)

    def test_memory_crud_endpoints(self):
        # Create memory
        create_resp = self.client.post(
            "/api/memory",
            json={"content": "API test memory item", "category": "project"}
        )
        self.assertEqual(create_resp.status_code, 200)
        self.assertTrue(create_resp.json()["success"])

        # Retrieve memory
        get_resp = self.client.get("/api/memory?q=API test memory")
        self.assertEqual(get_resp.status_code, 200)
        mems = get_resp.json()
        self.assertTrue(len(mems) > 0)
        self.assertEqual(mems[0]["content"], "API test memory item")
        self.assertEqual(mems[0]["category"], "project")

    def test_delete_session_endpoint(self):
        response = self.client.delete("/api/session/custom-session-123")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["session_id"], "custom-session-123")


if __name__ == "__main__":
    unittest.main()
