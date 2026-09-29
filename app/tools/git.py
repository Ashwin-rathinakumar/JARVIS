"""Bounded Git workflows; approval is owned by the existing permission engine.

No shell, destructive commands, automatic conflict resolution or repository creation.
Only registered project roots are accepted. Raw subprocess output never leaves here.
"""
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from app.projects.resolver import project_resolver
from app.tools.files import is_path_allowed


class GitFailure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def resolve_git_project(project_name):
    if not isinstance(project_name, str) or not project_name.strip():
        raise GitFailure("PROJECT_REQUIRED", "Which registered project should I use?")
    if any(c in project_name for c in '/\\:;&|`$<>\n\r\0') or ".." in project_name:
        raise GitFailure("INVALID_PROJECT", "Use a registered project name or alias, not a path or shell command.")
    result = project_resolver.resolve(project_name)
    if not result.matched or result.ambiguous or result.match_type == "fuzzy":
        raise GitFailure("UNKNOWN_PROJECT", "Project is unknown or uncertain. Please specify its registered name or alias.")
    root = Path(result.project["path"]).resolve()
    if not root.is_dir() or not is_path_allowed(root):
        raise GitFailure("UNSAFE_PATH", "The registered project folder is missing or outside allowed paths.")
    return result.project_key, root


def _run(root, *args, executable="git", check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never", GH_PROMPT_DISABLED="1")
    command = [executable, *args]
    if executable == "git":
        command = ["git", "-c", "core.hooksPath=NUL", "-c", "protocol.ext.allow=never", *args]
    try:
        result = subprocess.run(command, cwd=str(root), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60, shell=False, env=env)
    except FileNotFoundError:
        raise GitFailure("GIT_NOT_INSTALLED" if executable == "git" else "GH_UNAVAILABLE",
                         f"{executable} is not installed or is not on PATH.") from None
    except subprocess.TimeoutExpired:
        raise GitFailure("TIMEOUT", "Git operation timed out. Check repository status before retrying; it may have partially completed.") from None
    except OSError:
        raise GitFailure("PROCESS_FAILED", "Could not start the Git operation. Check the executable and project folder.") from None
    if check and result.returncode:
        error = (result.stderr + result.stdout).lower()
        for terms, code, message in [
            (("authentication", "permission denied", "could not read username", "terminal prompts disabled"), "AUTH_FAILED", "Authentication failed. Sign in using Git Credential Manager or gh auth login, then retry."),
            (("non-fast-forward", "fetch first", "rejected"), "PUSH_REJECTED", "Push was rejected because the remote contains commits not present locally. I did not overwrite them."),
            (("not a git repository",), "NOT_REPOSITORY", "This project is not a Git repository. Initialize it explicitly before using Git tools."),
            (("unable to auto-detect email", "author identity unknown"), "IDENTITY_REQUIRED", "Configure Git user.name and user.email before committing."),
            (("already exists",), "REPOSITORY_EXISTS", "The repository already exists. Configure its remote explicitly."),
            (("could not resolve", "unable to access", "repository not found"), "REMOTE_UNAVAILABLE", "Remote unavailable. Check its address, network connection and account access."),
            (("not possible to fast-forward", "diverging branches"), "NOT_FAST_FORWARD", "Pull cannot fast-forward. Resolve the diverging history manually; no merge was created."),
            (("would be overwritten",), "LOCAL_CHANGES", "Local or ignored files would be overwritten. Pull stopped; preserve or move those files manually before retrying."),
        ]:
            if any(term in error for term in terms):
                raise GitFailure(code, message)
        raise GitFailure("GIT_FAILED", "Git operation failed. Check repository status and configuration locally; raw output is withheld to protect credentials.")
    return result


def _sensitive(path):
    parts = path.replace("\\", "/").lower().split("/")
    name = parts[-1]
    return (name == ".env" or name.startswith(".env.") or name.endswith((".pem", ".key"))
            or name == "credentials.json" or name.startswith("service-account")
            or "token" in name or "secret" in name or "credentials" in name
            or "editor-sessions" in parts)


def _snapshot(root):
    top = _run(root, "rev-parse", "--show-toplevel").stdout.strip()
    if Path(top).resolve() != root:
        raise GitFailure("REPOSITORY_ROOT_MISMATCH", "The selected project is inside another repository. Register the repository root explicitly.")
    branch = _run(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
    chunks = _run(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout.split("\0")
    staged, modified, untracked, conflicts = [], [], [], []
    index = 0
    while index < len(chunks):
        item = chunks[index]
        index += 1
        if not item:
            continue
        code, name = item[:2], item[3:]
        if code == "??":
            untracked.append(name)
        else:
            if code[0] != " ":
                staged.append(name)
            if code[1] != " ":
                modified.append(name)
            if "U" in code or code in {"AA", "DD"}:
                conflicts.append(name)
            if "R" in code or "C" in code:
                index += 1  # porcelain -z includes the old name separately
    remotes = _run(root, "remote").stdout.splitlines()
    return dict(branch=branch or None, staged=staged, modified=modified,
                untracked=untracked, conflicts=conflicts, remotes=remotes)


def _ready(root, state):
    if not state["branch"]:
        raise GitFailure("DETACHED_HEAD", "HEAD is detached. Switch to a branch explicitly before changing or publishing the repository.")
    if state["conflicts"]:
        raise GitFailure("CONFLICTS", "Unresolved conflicts exist. Resolve them manually before continuing.")
    for marker in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        path = _run(root, "rev-parse", "--git-path", marker).stdout.strip()
        if (root / path).exists():
            raise GitFailure("OPERATION_IN_PROGRESS", "A merge, rebase or history operation is in progress. Finish it manually first.")


def _remote(root, state):
    branch = state["branch"]
    configured = _run(root, "config", "--get", f"branch.{branch}.remote", check=False).stdout.strip()
    remote = configured or ("origin" if "origin" in state["remotes"] else (state["remotes"][0] if len(state["remotes"]) == 1 else None))
    if not remote:
        raise GitFailure("NO_REMOTE", "No unambiguous remote is configured. Repository creation and authentication are separate setup steps; git push does not create a GitHub repository.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", remote) or remote not in state["remotes"]:
        raise GitFailure("INVALID_REMOTE", "The configured remote is invalid. Review the Git remote configuration.")
    # Check both fetch and push destinations, including URL rewrites. Reject helpers,
    # credential-bearing URLs and multiple push URLs to avoid unintended publishing.
    urls = []
    for push in (False, True):
        args = ["remote", "get-url", "--all"] + (["--push"] if push else []) + [remote]
        values = _run(root, *args).stdout.splitlines()
        if len(values) != 1 or not _valid_remote(values[0]):
            raise GitFailure("INVALID_REMOTE", "Remote must have one valid HTTPS, SSH or local destination without embedded credentials.")
        urls.extend(values)
    return remote, urls[-1]


def _valid_remote(url):
    if any(c in url for c in "\n\r\0") or url.startswith("-") or "::" in url:
        return False
    if re.fullmatch(r"[\w.-]+@[\w.-]+:[\w./-]+", url):
        return True
    if "://" in url:
        try:
            parsed = urlsplit(url)
            return (parsed.scheme in {"https", "ssh"} and bool(parsed.hostname) and bool(parsed.path.strip("/"))
                    and not parsed.password and not parsed.query and not parsed.fragment
                    and (parsed.scheme == "ssh" or parsed.username is None))
        except ValueError:
            return False
    return Path(url).is_absolute() and Path(url).is_dir()


def _commit(root, state, message):
    if not isinstance(message, str) or not message.strip() or len(message) > 500 or any(c in message for c in "\r\n\0"):
        raise GitFailure("INVALID_MESSAGE", "Supply a nonempty commit message of at most 500 characters on one line.")
    paths = set(state["staged"] + state["modified"] + state["untracked"])
    if any(_sensitive(path) for path in paths):
        raise GitFailure("SENSITIVE_FILES", "Potentially sensitive files or runtime sessions are changed, staged or untracked. Nothing was staged. Remove them from the index and ignore or review them manually.")
    if not paths:
        return False
    # Stage only inspected paths. Literal pathspecs prevent filenames such as
    # :(glob)* from expanding to uninspected files; newly created files stay out.
    _run(root, "--literal-pathspecs", "add", "-A", "--", *sorted(paths))
    staged = _run(root, "diff", "--cached", "--name-only", "-z").stdout.split("\0")
    if any(_sensitive(path) for path in staged if path):
        raise GitFailure("SENSITIVE_FILES", "The index now contains a sensitive file. Commit stopped; review the index manually.")
    if not _run(root, "diff", "--cached", "--quiet", check=False).returncode:
        return False
    _run(root, "-c", "commit.gpgsign=false", "commit", "-m", message)
    return True


def _push(root, state, remote):
    if _run(root, "rev-parse", "--verify", "HEAD", check=False).returncode:
        raise GitFailure("NO_COMMITS", "There are no commits to push. Commit the intended files first.")
    # Explicit refspec limits the push to this branch even with push.default=matching
    # or configured remote push refspecs. Never force, mirror or push extra tags.
    target = _run(root, "config", "--get", f"branch.{state['branch']}.merge", check=False).stdout.strip()
    if target and (not target.startswith("refs/heads/") or _run(root, "check-ref-format", target, check=False).returncode):
        raise GitFailure("INVALID_UPSTREAM", "The upstream branch is invalid. Review branch tracking configuration.")
    options = [] if target else ["-u"]
    target = target or f"refs/heads/{state['branch']}"
    _run(root, "-c", "push.followTags=false", "-c", "push.recurseSubmodules=no", "-c", f"remote.{remote}.mirror=false",
         "push", *options, remote, f"refs/heads/{state['branch']}:{target}")


def _gh_capabilities(root):
    try:
        _run(root, "--version", executable="gh")
        authenticated = _run(root, "auth", "status", executable="gh", check=False).returncode == 0
        return "GH_READY" if authenticated else "GH_UNAUTHENTICATED"
    except GitFailure as error:
        return error.code


def _workflow(operation, project_name, message=None):
    result = {"success": False, "operation": operation}
    try:
        key, root = resolve_git_project(project_name)
        result["project"] = key
        _run(root, "--version")
        state = _snapshot(root)
        result.update(state)
        if operation == "status":
            result.update(success=True, message=f"{key}: branch {state['branch'] or 'detached HEAD'}. "
                          f"Staged: {', '.join(state['staged']) or 'none'}. "
                          f"Modified: {', '.join(state['modified']) or 'none'}. "
                          f"Untracked: {', '.join(state['untracked']) or 'none'}. "
                          f"Remotes: {', '.join(state['remotes']) or 'none'}.")
            return result
        _ready(root, state)
        remote = None
        if operation in {"push", "pull", "publish", "commit_push"}:
            try:
                remote, url = _remote(root, state)
            except GitFailure as error:
                if operation == "publish" and error.code == "NO_REMOTE":
                    result["github_capability"] = _gh_capabilities(root)
                    result["repository_creation_requires_confirmation"] = True
                    guidance = {
                        "GH_READY": " GitHub CLI is authenticated. Create the intended repository explicitly, choose its visibility, and configure its remote before retrying. This workflow does not create repositories.",
                        "GH_UNAUTHENTICATED": " GitHub CLI is installed but not authenticated. Use gh auth login locally; never send credentials to JARVIS.",
                        "GH_UNAVAILABLE": " GitHub CLI is unavailable. Create the repository and configure its remote manually, or install and authenticate gh locally.",
                    }
                    error.message += guidance.get(result["github_capability"], " GitHub CLI readiness could not be verified.")
                raise
            result["remote"] = remote
            if operation == "publish" and not (url.startswith("git@github.com:") or url.startswith("https://github.com/") or url.startswith("ssh://git@github.com/")):
                raise GitFailure("NOT_GITHUB_REMOTE", "The selected remote is not on github.com. Configure a GitHub remote explicitly before uploading.")
        if operation in {"commit", "commit_push", "publish"}:
            result["committed"] = _commit(root, state, message)
        if operation in {"push", "commit_push", "publish"}:
            _push(root, state, remote)
        if operation == "pull":
            if state["staged"] or state["modified"] or state["untracked"]:
                raise GitFailure("DIRTY_WORKTREE", "Commit or handle local changes and untracked files before pulling. Nothing was overwritten.")
            target = _run(root, "config", "--get", f"branch.{state['branch']}.merge", check=False).stdout.strip() or f"refs/heads/{state['branch']}"
            if not target.startswith("refs/heads/") or _run(root, "check-ref-format", target, check=False).returncode:
                raise GitFailure("INVALID_UPSTREAM", "The upstream branch is invalid. Review branch tracking configuration.")
            # Equivalent to ff-only pull, split so ignored files are protected too.
            # git pull does not expose merge's --no-overwrite-ignore option.
            _run(root, "fetch", "--no-recurse-submodules", "--no-tags", remote, target)
            _run(root, "-c", "merge.autostash=false", "merge", "--ff-only", "--no-autostash",
                 "--no-overwrite-ignore", "FETCH_HEAD")
        messages = {"commit": "Changes committed." if result.get("committed") else "Nothing to commit; no empty commit was created.",
                    "push": "Current branch pushed successfully. Uncommitted changes were not included.",
                    "commit_push": "Changes committed if needed and current branch pushed successfully.",
                    "publish": "Changes committed if needed and current branch uploaded to GitHub.",
                    "pull": "Latest changes pulled using fast-forward only."}
        result.update(success=True, message=messages[operation])
    except GitFailure as error:
        result.update(error_code=error.code, message=error.message)
        if result.get("committed"):
            result["message"] += " The local commit succeeded and was preserved."
    return result


def git_status(project_name=None):
    return _workflow("status", project_name)


def git_commit(project_name=None, message="Update project changes"):
    return _workflow("commit", project_name, message)


def git_push(project_name=None):
    return _workflow("push", project_name)


def git_pull(project_name=None):
    return _workflow("pull", project_name)


def git_commit_push(project_name=None, message="Update project changes"):
    return _workflow("commit_push", project_name, message)


def git_publish(project_name=None, message="Update project changes"):
    return _workflow("publish", project_name, message)
