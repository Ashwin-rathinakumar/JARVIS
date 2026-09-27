import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from app.tools.system import (
    get_system_information,
    get_cpu_info,
    get_memory_info,
    get_disk_info,
    get_hostname,
    get_python_version,
    get_current_directory,
)
from app.tools.files import (
    list_files,
    find_file,
    read_text_file,
    create_folder,
    create_text_file,
    get_file_info,
)
from app.tools.apps import normalize_app, open_application
from app.tools.analysis import analyze_project, find_todos


class TestTools(unittest.TestCase):

    def test_system_info(self):
        info = get_system_information()
        self.assertIn("Operating System", info)
        self.assertIn("Python Version", info)

        cpu = get_cpu_info()
        self.assertIn("Processor", cpu)

        disk = get_disk_info()
        self.assertIn("Drive", disk)

        host = get_hostname()
        self.assertIn("Computer Name", host)

    def test_file_tools(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create file
            f_path = temp_path / "hello.txt"
            res_create = create_text_file(str(f_path), "Hello, World!")
            self.assertIn("Created file", res_create)
            self.assertTrue(f_path.exists())

            # Refuse silent overwrite
            res_no_over = create_text_file(str(f_path), "Different content", overwrite=False)
            self.assertIn("already exists", res_no_over)

            # Read file
            res_read = read_text_file(str(f_path))
            self.assertIn("Hello, World!", res_read)

            # File info
            res_info = get_file_info(str(f_path))
            self.assertIn("File", res_info)
            self.assertIn("hello.txt", res_info)

            # List files
            res_list = list_files(str(temp_path))
            self.assertIn("hello.txt", res_list)

            # Find file
            res_find = find_file("*.txt", str(temp_path))
            self.assertIn("hello.txt", res_find)

            # Create folder
            sub = temp_path / "subdir"
            res_dir = create_folder(str(sub))
            self.assertIn("Created folder", res_dir)
            self.assertTrue(sub.is_dir())

    def test_app_normalization(self):
        self.assertEqual(normalize_app("calc"), "calculator")
        self.assertEqual(normalize_app("ms paint"), "paint")
        self.assertEqual(normalize_app("vs code"), "vscode")
        self.assertEqual(normalize_app("visual studio code"), "vscode")

    @patch("subprocess.Popen")
    def test_open_app_mocked(self, mock_popen):
        res = open_application("notepad")
        self.assertIn("Opened notepad", res)
        mock_popen.assert_called_once()

    def test_analysis_tools(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            t_path = Path(temp_dir)
            sample_code = t_path / "script.py"
            sample_code.write_text("# TODO: implement this\nprint('hello')\n", encoding="utf-8")

            res_analysis = analyze_project(str(t_path))
            self.assertIn("Project Analysis", res_analysis)

            res_todos = find_todos(str(t_path))
            self.assertIn("TODO: implement this", res_todos)


if __name__ == "__main__":
    unittest.main()
