import unittest
from unittest.mock import MagicMock, patch

from app.brain.intent import classify_intent, classify_intent_deterministic
from app.brain.orchestrator import JarvisOrchestrator
from app.brain.routing import RouteCategory, normalize_request_text, parse_weather_request
from app.state.session import session_manager
from app.tools.registry import ToolResult


class TestRoutingPolicy(unittest.TestCase):
    def test_general_knowledge_is_first_class_no_tool(self):
        prompts = [
            "What is recursion?",
            "Explain polymorphism.",
            "What is an API?",
            "Tell me about black holes.",
            "Who invented Python?",
            "Can you explain inheritance in Java?",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                decision = classify_intent(prompt)
                self.assertEqual(decision["intent"], "chat")
                self.assertIsNone(decision["tool"])
                self.assertEqual(decision["route_category"], RouteCategory.GENERAL_KNOWLEDGE.value)

    def test_general_chat_is_first_class_no_tool(self):
        for prompt in ["Hello", "How are you?", "Tell me a joke."]:
            with self.subTest(prompt=prompt):
                decision = classify_intent(prompt)
                self.assertEqual(decision["intent"], "chat")
                self.assertIsNone(decision["tool"])
                self.assertIn(decision["route_category"], {
                    RouteCategory.GENERAL_CHAT.value, RouteCategory.GENERAL_KNOWLEDGE.value,
                })

    def test_weather_routes_with_location_extraction(self):
        cases = {
            "What's the weather in Chennai?": ("Chennai", "current"),
            "weather in Chennai": ("Chennai", "current"),
            "temperature in Chennai": ("Chennai", "current"),
            "Temperature at Bengaluru": ("Bengaluru", "current"),
            "is it raining in Chennai?": ("Chennai", "current"),
            "what's the forecast for Chennai?": ("Chennai", "current"),
            "JARVIS, what's the weather like in Chennai today?": ("Chennai", "today"),
            "Second, tell me how the weather is in Shanghai.": ("Shanghai", "current"),
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                decision = classify_intent(prompt)
                self.assertEqual(decision["tool"], "get_weather")
                self.assertEqual(decision["route_category"], RouteCategory.CURRENT_INFO.value)
                self.assertEqual(
                    (decision["arguments"]["location"], decision["arguments"]["when"]), expected
                )

    def test_weather_without_location_requests_clarification(self):
        for prompt in ["What's the weather?", "Will it rain today?", "What is the weather tomorrow?"]:
            with self.subTest(prompt=prompt):
                decision = classify_intent(prompt)
                self.assertEqual(decision["intent"], "clarification")
                self.assertIsNone(decision["tool"])
                self.assertIn("location", decision["arguments"]["message"].lower())

    def test_weather_never_selects_unrelated_tools(self):
        for prompt in ["What's the weather in Chennai?", "Weather in Bengaluru", "Is it raining in Chennai?"]:
            with self.subTest(prompt=prompt):
                decision = classify_intent(prompt)
                self.assertNotEqual(decision["tool"], "system_information")
                self.assertNotIn(decision["tool"], {"open_project", "list_files", "read_text_file"})

    def test_strict_system_queries(self):
        prompts = [
            "Show system info.",
            "What OS am I running?",
            "How much disk space do I have?",
            "How many CPU cores are there?",
            "What version of Python is installed?",
            "Show my machine specs.",
            "What's my computer name?",
            "Could you tell me how much free disk space I have?",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                decision = classify_intent(prompt)
                self.assertEqual(decision["tool"], "system_information")
                self.assertEqual(decision["route_category"], RouteCategory.SYSTEM_ACTION.value)

    def test_general_queries_never_become_system_info(self):
        prompts = [
            "What's the weather in Chennai?", "What is Java?", "Who is Alan Turing?",
            "Explain HTTP.", "What project am I working on?",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertNotEqual(classify_intent(prompt).get("tool"), "system_information")

    def test_project_actions_and_queries_remain_deterministic(self):
        cases = {
            "Open K.E.E.R.": "open_project",
            "Open Sentinel project.": "open_project",
            "Open Streetlight.": "open_project",
            "Hey JARVIS, can you open K.E.E.R. for me?": "open_project",
            "List projects.": "list_projects",
            "List my projects.": "list_projects",
            "What projects do I have?": "list_projects",
            "What project am I working on?": "current_project",
        }
        for prompt, expected_tool in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(classify_intent(prompt)["tool"], expected_tool)

    def test_project_question_does_not_execute_action(self):
        decision = classify_intent("What is K.E.E.R. supposed to do?")
        self.assertEqual(decision["intent"], "chat")
        self.assertIsNone(decision["tool"])

    def test_active_project_does_not_hijack_general_chat(self):
        session_id = "routing-active-project"
        session_manager.delete_session(session_id)
        session_manager.get_session(session_id).set_current_project("keer")
        brain = MagicMock()
        brain.ask.return_value = "A black hole is a compact astronomical object."
        orchestrator = JarvisOrchestrator(brain=brain)
        with patch("app.brain.orchestrator.execute_tool") as execute:
            response = orchestrator.process("What is a black hole?", session_id=session_id)
        self.assertEqual(response.intent, "chat")
        self.assertIsNone(response.tool_used)
        execute.assert_not_called()
        brain.ask.assert_called_once()

    def test_orchestrator_weather_uses_only_weather_tool(self):
        brain = MagicMock()
        orchestrator = JarvisOrchestrator(brain=brain)
        result = ToolResult(True, "Current weather in Chennai: clear sky, 30°C.", tool="get_weather")
        with patch("app.brain.orchestrator.execute_tool", return_value=result) as execute:
            response = orchestrator.process("What's the weather in Chennai?", session_id="weather-routing")
        execute.assert_called_once_with("get_weather", {"location": "Chennai", "when": "current"})
        self.assertEqual(response.intent, "current_info")
        self.assertEqual(response.tool_used, "get_weather")
        brain.ask.assert_not_called()

    def test_orchestrator_general_question_executes_no_tool(self):
        brain = MagicMock()
        brain.ask.return_value = "Recursion is self-reference with a base case."
        orchestrator = JarvisOrchestrator(brain=brain)
        with patch("app.brain.orchestrator.execute_tool") as execute:
            response = orchestrator.process("What is recursion?", session_id="knowledge-routing")
        execute.assert_not_called()
        self.assertEqual(response.intent, "chat")
        brain.ask.assert_called_once()

    def test_unknown_action_never_becomes_system_info(self):
        decision = classify_intent("Launch the quantum reactor.")
        self.assertNotEqual(decision.get("tool"), "system_information")

        brain = MagicMock()
        orchestrator = JarvisOrchestrator(brain=brain)
        response = orchestrator.process("Launch the quantum reactor.", session_id="unknown-action")
        self.assertFalse(response.success)
        self.assertEqual(response.tool_used, "open_project")
        self.assertIn("don't know the project", response.response.lower())
        brain.ask.assert_not_called()

    def test_router_no_longer_accepts_llm_tool_hallucinations(self):
        # No network/LLM classifier is consulted for unmatched language.
        with patch("app.brain.intent.classify_intent_deterministic", return_value=None):
            decision = classify_intent("An ordinary unmatched question")
        self.assertEqual(decision["intent"], "chat")
        self.assertIsNone(decision["tool"])

    def test_conversational_wrapper_normalization_is_anchored(self):
        self.assertEqual(normalize_request_text("Hey JARVIS, can you open K.E.E.R. for me?"), "open K.E.E.R.?")
        self.assertEqual(normalize_request_text("Can you explain inheritance in Java?"), "explain inheritance in Java?")
        self.assertIsNone(parse_weather_request("Explain weather systems."))


if __name__ == "__main__":
    unittest.main()
