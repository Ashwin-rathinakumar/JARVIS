import unittest
from app.brain.intent import classify_intent, classify_intent_deterministic


class TestIntentClassification(unittest.TestCase):

    def test_deterministic_projects(self):
        r = classify_intent_deterministic("open keer project")
        self.assertEqual(r["tool"], "open_project")
        self.assertIn(r["arguments"]["project_name"], {"keer", "K.E.E.R."})

        r = classify_intent_deterministic("open jarvis project")
        self.assertEqual(r["tool"], "open_project")
        self.assertIn(r["arguments"]["project_name"], {"jarvis", "JARVIS"})

        r = classify_intent_deterministic("run project")
        self.assertEqual(r["tool"], "run_project")

        r = classify_intent_deterministic("stop project")
        self.assertEqual(r["tool"], "stop_project")

        r = classify_intent_deterministic("list projects")
        self.assertEqual(r["tool"], "list_projects")

        r = classify_intent_deterministic("current project")
        self.assertEqual(r["tool"], "current_project")

    def test_deterministic_apps(self):
        r = classify_intent_deterministic("open calculator")
        self.assertEqual(r["tool"], "open_application")
        self.assertEqual(r["arguments"]["app"], "calculator")

        r = classify_intent_deterministic("close notepad")
        self.assertEqual(r["tool"], "close_application")
        self.assertEqual(r["arguments"]["app"], "notepad")

    def test_deterministic_system(self):
        r = classify_intent_deterministic("system info")
        self.assertEqual(r["tool"], "system_information")

        r = classify_intent_deterministic("give me the system information of my laptop")
        self.assertEqual(r["tool"], "system_information")

        r = classify_intent_deterministic("cpu info")
        self.assertEqual(r["tool"], "cpu_info")

        r = classify_intent_deterministic("memory info")
        self.assertEqual(r["tool"], "memory_info")

        r = classify_intent_deterministic("disk info")
        self.assertEqual(r["tool"], "disk_info")

    def test_deterministic_memory(self):
        r = classify_intent_deterministic("remember that I prefer dark mode")
        self.assertEqual(r["tool"], "remember")
        self.assertEqual(r["arguments"]["content"], "I prefer dark mode")

        r = classify_intent_deterministic("show memories")
        self.assertEqual(r["tool"], "show_memories")

        r = classify_intent_deterministic("search memories dark")
        self.assertEqual(r["tool"], "search_memories")
        self.assertEqual(r["arguments"]["query"], "dark")

        r = classify_intent_deterministic("forget memory 3")
        self.assertEqual(r["tool"], "forget_memory")
        self.assertEqual(r["arguments"]["memory_id"], 3)

    def test_deterministic_rag(self):
        r = classify_intent_deterministic("index documents")
        self.assertEqual(r["tool"], "index_documents")

        r = classify_intent_deterministic("document status")
        self.assertEqual(r["tool"], "document_status")

        r = classify_intent_deterministic("ask documents what is jarvis")
        self.assertEqual(r["tool"], "ask_documents")
        self.assertEqual(r["arguments"]["query"], "what is jarvis")

    def test_deterministic_files(self):
        # Basic list files
        r = classify_intent_deterministic("list files")
        self.assertEqual(r["tool"], "list_files")
        self.assertEqual(r["arguments"]["directory"], ".")

        # Natural variants
        r = classify_intent_deterministic("list the files")
        self.assertEqual(r["tool"], "list_files")
        self.assertEqual(r["arguments"]["directory"], ".")

        r = classify_intent_deterministic("show files")
        self.assertEqual(r["tool"], "list_files")
        self.assertEqual(r["arguments"]["directory"], ".")

        r = classify_intent_deterministic("show me the files")
        self.assertEqual(r["tool"], "list_files")
        self.assertEqual(r["arguments"]["directory"], ".")

        r = classify_intent_deterministic("list files in the current directory")
        self.assertEqual(r["tool"], "list_files")
        self.assertEqual(r["arguments"]["directory"], ".")

        r = classify_intent_deterministic("what files are in this folder?")
        self.assertEqual(r["tool"], "list_files")
        self.assertEqual(r["arguments"]["directory"], ".")

        r = classify_intent_deterministic("show the files in the project")
        self.assertEqual(r["tool"], "list_files")
        self.assertEqual(r["arguments"]["directory"], ".")

        # Find file
        r = classify_intent_deterministic("find file *.py")
        self.assertEqual(r["tool"], "find_file")
        self.assertEqual(r["arguments"]["pattern"], "*.py")


if __name__ == "__main__":
    unittest.main()
