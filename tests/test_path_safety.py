import unittest
from pathlib import Path
from unittest.mock import patch

from app.tools.files import (
    is_path_allowed,
    list_files,
    find_file,
    read_text_file,
    create_directory,
    create_folder,
    write_text_file,
    create_text_file,
    get_file_info,
)
from app.config.settings import BASE_DIR, WORKSPACE_DIR


class TestPathSafety(unittest.TestCase):

    def test_allowed_paths_within_project(self):
        project_file = BASE_DIR / "requirements.txt"
        self.assertTrue(is_path_allowed(project_file))
        self.assertTrue(is_path_allowed(BASE_DIR))

    def test_restricted_path_outside_allowed(self):
        with patch("app.tools.files.JARVIS_ALLOWED_PATHS", [BASE_DIR]):
            with patch("tempfile.gettempdir", return_value="C:/DummyTemp"):
                forbidden_path = Path("C:/Windows/System32")
                self.assertFalse(is_path_allowed(forbidden_path))

                # Test file operations on forbidden path
                res_list = list_files("C:/Windows/System32")
                self.assertIn("Access denied", res_list)

                res_read = read_text_file("C:/Windows/System32/drivers/etc/hosts")
                self.assertIn("Access denied", res_read)

                res_find = find_file("*.dll", "C:/Windows/System32")
                self.assertIn("Access denied", res_find)

                res_folder = create_folder("C:/Windows/System32/secret")
                self.assertIn("Access denied", res_folder)

                res_file = create_text_file("C:/Windows/System32/hacked.txt", "content")
                self.assertIn("Access denied", res_file)

                res_info = get_file_info("C:/Windows/System32")
                self.assertIn("Access denied", res_info)

    def test_implicit_create_directory_defaults_to_workspace(self):
        target_name = "regression_test_dir_implicit_unique"
        expected_path = (WORKSPACE_DIR / target_name).resolve()
        if expected_path.exists():
            import shutil
            shutil.rmtree(expected_path, ignore_errors=True)
        res = create_directory(target_name)
        self.assertIn(str(expected_path), res)

    def test_implicit_write_text_file_defaults_to_workspace(self):
        target_name = "regression_test_file_implicit_unique.txt"
        res = write_text_file(target_name, "content", overwrite=True)
        expected_path = (WORKSPACE_DIR / target_name).resolve()
        self.assertIn(str(expected_path), res)

    def test_explicit_valid_allowed_path_respected(self):
        explicit_dir = WORKSPACE_DIR / "explicit_test_folder"
        res = create_directory(str(explicit_dir))
        self.assertIn(str(explicit_dir.resolve()), res)

    def test_explicit_outside_root_path_denied(self):
        res = create_directory("C:/Windows/System32/forbidden_test_dir")
        self.assertIn("Access denied", res)

    def test_traversal_denied(self):
        res = write_text_file("../../windows/system.ini", "bad", overwrite=True)
        self.assertIn("Access denied", res)


if __name__ == "__main__":
    unittest.main()
