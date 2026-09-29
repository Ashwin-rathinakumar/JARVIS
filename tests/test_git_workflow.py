import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.tools import git as git_tools
from app.projects.resolver import ProjectResolver
from app.projects.git_commands import parse_git_command
from app.brain.intent import classify_intent
from app.brain.permissions import PermissionEngine
from app.core.schemas import PermissionDecision
from app.brain.orchestrator import JarvisOrchestrator
from app.state.session import session_manager


@unittest.skipUnless(shutil.which("git"), "Git required for local integration tests")
class GitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.remote = Path(self.temp.name) / "remote.git"
        self.raw("init", "-b", "feature/test")
        self.raw("config", "user.name", "Test")
        self.raw("config", "user.email", "test@example.invalid")
        resolver = ProjectResolver({"sample": {"name": "Sample Project", "path": str(self.root), "aliases": ["sample alias"]}})
        mock = patch.object(git_tools, "project_resolver", resolver)
        mock.start()
        self.addCleanup(mock.stop)

    def raw(self, *args, cwd=None, check=True):
        return subprocess.run(["git", *args], cwd=cwd or self.root, capture_output=True,
                              text=True, check=check, timeout=20)

    def seed(self):
        (self.root / "file.txt").write_text("hello", encoding="utf-8")
        result = git_tools.git_commit("sample", "Initial")
        self.assertTrue(result["success"], result)

    def add_remote(self):
        self.raw("init", "--bare", str(self.remote))
        self.raw("remote", "add", "origin", str(self.remote))

    def test_status_branch_files_and_alias(self):
        self.seed()
        (self.root / "file.txt").write_text("changed")
        (self.root / "new file.txt").write_text("new")
        self.add_remote()
        result = git_tools.git_status("sample alias")
        self.assertTrue(result["success"])
        self.assertEqual(result["branch"], "feature/test")
        self.assertEqual(result["modified"], ["file.txt"])
        self.assertEqual(result["untracked"], ["new file.txt"])
        self.assertEqual(result["remotes"], ["origin"])

    def test_not_repository(self):
        shutil.rmtree(self.root / ".git")
        self.assertEqual(git_tools.git_status("sample")["error_code"], "NOT_REPOSITORY")

    def test_parent_repository_rejected(self):
        child = self.root / "child"
        child.mkdir()
        git_tools.project_resolver.projects["sample"]["path"] = str(child)
        self.assertEqual(git_tools.git_status("sample")["error_code"], "REPOSITORY_ROOT_MISMATCH")

    def test_commit_and_nothing_to_commit(self):
        self.seed()
        before = self.raw("rev-parse", "HEAD").stdout
        result = git_tools.git_commit("sample", "No changes")
        self.assertTrue(result["success"])
        self.assertFalse(result["committed"])
        self.assertEqual(before, self.raw("rev-parse", "HEAD").stdout)

    def test_push_with_and_without_upstream(self):
        self.seed()
        self.add_remote()
        for _ in range(2):
            result = git_tools.git_push("sample")
            self.assertTrue(result["success"], result)
        self.assertEqual(self.raw("rev-parse", "--abbrev-ref", "@{u}").stdout.strip(), "origin/feature/test")

    def test_push_does_not_publish_other_branches(self):
        self.seed()
        self.add_remote()
        self.raw("branch", "private-work")
        self.raw("config", "remote.origin.push", "refs/heads/*:refs/heads/*")
        self.raw("config", "remote.origin.mirror", "true")
        self.assertTrue(git_tools.git_push("sample")["success"])
        self.assertEqual(self.raw("for-each-ref", "--format=%(refname)", cwd=self.remote).stdout.strip(), "refs/heads/feature/test")

    def test_missing_remote_no_mutation(self):
        (self.root / "file.txt").write_text("hello")
        with patch.object(git_tools, "_gh_capabilities", return_value="GH_UNAUTHENTICATED"):
            result = git_tools.git_publish("sample")
        self.assertEqual(result["error_code"], "NO_REMOTE")
        self.assertTrue(result["repository_creation_requires_confirmation"])
        self.assertEqual(result["github_capability"], "GH_UNAUTHENTICATED")
        self.assertEqual(self.raw("diff", "--cached", "--name-only").stdout, "")

    def test_rejected_push_preserves_local_commit(self):
        self.seed()
        self.add_remote()
        self.assertTrue(git_tools.git_push("sample")["success"])
        other = Path(self.temp.name) / "other"
        self.raw("clone", "-b", "feature/test", str(self.remote), str(other))
        self.raw("config", "user.name", "Test", cwd=other)
        self.raw("config", "user.email", "test@example.invalid", cwd=other)
        (other / "remote.txt").write_text("remote")
        self.raw("add", ".", cwd=other)
        self.raw("commit", "-m", "remote change", cwd=other)
        self.raw("push", cwd=other)
        (self.root / "local.txt").write_text("local")
        result = git_tools.git_commit_push("sample", "local change")
        self.assertEqual(result["error_code"], "PUSH_REJECTED")
        self.assertTrue(result["committed"])
        self.assertIn("preserved", result["message"])

    def test_sensitive_untracked_and_staged_block_all_staging(self):
        for filename in [".env", ".env.local", "private.key", "cert.pem", "credentials.json", "service-account-prod.json", "access-token.txt", "secrets.txt"]:
            with self.subTest(filename=filename):
                file = self.root / filename
                file.write_text("do not publish")
                result = git_tools.git_commit("sample")
                self.assertEqual(result["error_code"], "SENSITIVE_FILES")
                self.assertEqual(self.raw("diff", "--cached", "--name-only").stdout, "")
                file.unlink()
        (self.root / ".env").write_text("secret")
        self.raw("add", ".env")
        self.assertEqual(git_tools.git_commit("sample")["error_code"], "SENSITIVE_FILES")

    def test_ignore_and_runtime_files(self):
        (self.root / ".gitignore").write_text(".env\ndata/editor-sessions/\n")
        (self.root / ".env").write_text("secret")
        runtime = self.root / "data/editor-sessions"
        runtime.mkdir(parents=True)
        (runtime / "state.json").write_text("runtime")
        self.assertTrue(git_tools.git_commit("sample")["success"])
        self.assertEqual(self.raw("ls-files").stdout.strip(), ".gitignore")

    def test_shell_like_message_is_literal(self):
        (self.root / "file.txt").write_text("hello")
        message = 'fix; echo unsafe & $(whoami) | --help'
        self.assertTrue(git_tools.git_commit("sample", message)["success"])
        self.assertEqual(self.raw("log", "-1", "--format=%s").stdout.strip(), message)

    def test_invalid_project_paths(self):
        for value in [None, "../sample", str(self.root), "sample;whoami", "unknown project", "sample\n"]:
            self.assertFalse(git_tools.git_status(value)["success"], value)

    def test_malformed_remote(self):
        self.seed()
        self.raw("remote", "add", "origin", "ext::bad-command")
        self.assertEqual(git_tools.git_push("sample")["error_code"], "INVALID_REMOTE")

    def test_detached_and_conflict_operation(self):
        self.seed()
        self.raw("checkout", "--detach")
        self.assertEqual(git_tools.git_commit("sample")["error_code"], "DETACHED_HEAD")
        self.raw("checkout", "feature/test")
        (self.root / ".git/MERGE_HEAD").write_text(self.raw("rev-parse", "HEAD").stdout)
        self.assertEqual(git_tools.git_commit("sample")["error_code"], "OPERATION_IN_PROGRESS")

    def test_pull_dirty_refused_clean_allowed(self):
        self.seed()
        self.add_remote()
        self.assertTrue(git_tools.git_push("sample")["success"])
        (self.root / "local.txt").write_text("local")
        self.assertEqual(git_tools.git_pull("sample")["error_code"], "DIRTY_WORKTREE")
        (self.root / "local.txt").unlink()
        self.assertTrue(git_tools.git_pull("sample")["success"])

    def test_pull_preserves_ignored_files(self):
        self.seed()
        self.add_remote()
        self.assertTrue(git_tools.git_push("sample")["success"])
        other = Path(self.temp.name) / "other"
        self.raw("clone", "-b", "feature/test", str(self.remote), str(other))
        self.raw("config", "user.name", "Test", cwd=other)
        self.raw("config", "user.email", "test@example.invalid", cwd=other)
        (other / "local-only.txt").write_text("remote content")
        self.raw("add", ".", cwd=other)
        self.raw("commit", "-m", "remote file", cwd=other)
        self.raw("push", cwd=other)
        (self.root / ".git/info/exclude").write_text("local-only.txt\n")
        (self.root / "local-only.txt").write_text("precious local content")
        result = git_tools.git_pull("sample")
        self.assertFalse(result["success"], result)
        self.assertEqual((self.root / "local-only.txt").read_text(), "precious local content")

    def test_existing_differently_named_upstream_is_preserved(self):
        self.seed()
        self.add_remote()
        self.raw("push", "-u", "origin", "HEAD:refs/heads/review")
        self.assertTrue(git_tools.git_push("sample")["success"])
        self.assertEqual(self.raw("config", "--get", "branch.feature/test.merge").stdout.strip(), "refs/heads/review")

    def test_literal_pathspec_does_not_stage_uninspected_file(self):
        self.seed()
        (self.root / "selected.txt").write_text("selected")
        original = git_tools._run
        def racing_run(root, *args, **kwargs):
            if "add" in args:
                (self.root / ".env").write_text("new secret")
            return original(root, *args, **kwargs)
        with patch.object(git_tools, "_run", side_effect=racing_run):
            result = git_tools.git_commit("sample", "selected only")
        self.assertTrue(result["success"], result)
        self.assertNotIn(".env", self.raw("ls-files").stdout.splitlines())

    def test_session_confirmation_and_followup(self):
        self.seed()
        self.add_remote()
        brain = MagicMock()
        brain.ask.return_value = "Fetch downloads commits; pull also integrates them."
        orchestrator = JarvisOrchestrator(brain)
        sid = self._testMethodName
        session_manager.delete_session(sid)
        self.addCleanup(session_manager.delete_session, sid)
        status = orchestrator.process("check git status of sample alias", sid)
        self.assertTrue(status.success, status.response)
        (self.root / "change.txt").write_text("change")
        response = orchestrator.process("Commit the changes as fix complaint endpoint.", sid)
        self.assertEqual(response.status, "confirmation_required")
        self.assertEqual(self.raw("log", "-1", "--format=%s").stdout.strip(), "Initial")
        self.assertTrue(orchestrator.process("yes", sid).success)
        self.assertEqual(self.raw("log", "-1", "--format=%s").stdout.strip(), "fix complaint endpoint")
        response = orchestrator.process("Push it to GitHub.", sid)
        self.assertEqual(response.status, "confirmation_required")
        self.assertTrue(orchestrator.process("yes", sid).success)
        self.assertEqual(orchestrator.process("What is the difference between git fetch and git pull?", sid).intent, "chat")
        self.assertEqual(orchestrator.process("push it", sid + "other").error, "PROJECT_REQUIRED")


class GitRoutingTests(unittest.TestCase):
    def test_routes(self):
        cases = {
            "JARVIS, check the git status of the Streetlight project.": "status",
            "What's the git status?": "status", "What branch am I on?": "status",
            "what branch is JARVIS on?": "status", "Commit these changes": "commit",
            "Commit the current changes as fix project resolver": "commit",
            "push this project": "push", "Push my Streetlight project.": "push",
            "Push the latest JARVIS changes.": "push", "Commit and push": "commit_push",
            "Commit these changes and push them.": "commit_push",
            "Create a commit called fix voice runtime and push it.": "commit_push",
            "upload this to GitHub": "publish", "Upload JARVIS to GitHub.": "publish",
            "Pull the latest changes.": "pull", "Pull the latest JARVIS changes.": "pull",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(classify_intent(command)["tool"], "git_" + expected)
        self.assertEqual(parse_git_command("Create a commit called fix voice runtime and push it")["arguments"]["message"], "fix voice runtime")

    def test_general_questions_do_not_execute(self):
        for command in ["What does git rebase do?", "How do I push to GitHub?", "Explain git status", "What is the difference between git fetch and git pull?"]:
            self.assertEqual(classify_intent(command)["intent"], "chat")

    def test_permissions(self):
        self.assertEqual(PermissionEngine.evaluate("git_status", {})[0], PermissionDecision.ALLOW)
        for tool in ["git_commit", "git_push", "git_pull", "git_publish", "git_commit_push"]:
            self.assertEqual(PermissionEngine.evaluate(tool, {})[0], PermissionDecision.CONFIRM)
            self.assertEqual(PermissionEngine.evaluate(tool, {}, confirmed=True)[0], PermissionDecision.ALLOW)

    def test_auth_failure_is_sanitized(self):
        result = subprocess.CompletedProcess([], 128, "", "Authentication failed https://user:PRIVATE_TOKEN@github.com/test")
        with patch.object(git_tools.subprocess, "run", return_value=result):
            with self.assertRaises(git_tools.GitFailure) as caught:
                git_tools._run(Path.cwd(), "push", "origin")
        self.assertEqual(caught.exception.code, "AUTH_FAILED")
        self.assertNotIn("PRIVATE_TOKEN", caught.exception.message)

    def test_missing_executable_and_timeout(self):
        for error, code in [(FileNotFoundError(), "GIT_NOT_INSTALLED"), (subprocess.TimeoutExpired("git", 60), "TIMEOUT")]:
            with patch.object(git_tools.subprocess, "run", side_effect=error):
                with self.assertRaises(git_tools.GitFailure) as caught:
                    git_tools._run(Path.cwd(), "status")
                self.assertEqual(caught.exception.code, code)

    def test_gh_unavailable_and_unauthenticated(self):
        with patch.object(git_tools.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertEqual(git_tools._gh_capabilities(Path.cwd()), "GH_UNAVAILABLE")
        with patch.object(git_tools.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "private auth detail")):
            self.assertEqual(git_tools._gh_capabilities(Path.cwd()), "GIT_FAILED")
        with patch.object(git_tools.subprocess, "run", side_effect=[subprocess.CompletedProcess([], 0, "gh version", ""), subprocess.CompletedProcess([], 1, "", "private auth detail")]):
            self.assertEqual(git_tools._gh_capabilities(Path.cwd()), "GH_UNAUTHENTICATED")


if __name__ == "__main__":
    unittest.main()
