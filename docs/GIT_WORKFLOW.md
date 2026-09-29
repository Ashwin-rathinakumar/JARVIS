# Git/GitHub workflow increment

Git actions use the existing tool registry, project resolver, permission engine,
confirmation tokens and voice/API orchestration. General questions still use the
conversational provider. There is no arbitrary shell command interface.

## Commands

- `JARVIS, check the git status of the Streetlight project.`
- `What branch is JARVIS on?`
- `Commit the changes as fix complaint endpoint.`
- `Push it to GitHub.`
- `Create a commit called fix voice runtime and push it.`
- `Upload JARVIS to GitHub.`
- `Pull the latest JARVIS changes.`
- `What is the difference between git fetch and git pull?`

After selecting a project, follow-up Git commands reuse that conversation's
project. With no project context, JARVIS asks for a registered name. Paths, shell
syntax, uncertain fuzzy matches and nested repository roots are refused. Project
aliases come from the existing registry. Context is isolated by session.

Status is read-only and reports the branch, staged, modified and untracked paths,
and remote names (URLs are omitted to avoid exposing embedded credentials).
Commit and pull use the existing medium-risk confirmation policy; push,
commit-and-push and upload use high-risk confirmation. Reply `yes` to proceed or
`no` to cancel. A commit without a message uses `Update project changes`, shown
in the confirmation. No empty commit is created. A compound commit-and-push is
one explicitly confirmed workflow; a failed push preserves the local commit.

The project is bound before approval. Operations recheck repository state when
executed. Only inspected paths are staged with literal pathspecs. Ignored files
stay ignored; changed/staged/untracked `.env*`, key, credential, token, secret and
editor-session paths block committing. This is a conservative filename check,
not a scan for secrets embedded in ordinary source files or existing history.
Review existing commits before approving publication.

Push explicitly sends only the current branch to its configured upstream branch,
or establishes an upstream on the selected remote using the current branch name.
It overrides mirror/follow-tag behavior and does not force push. Origin is chosen
when there is no branch remote; a sole other remote is also supported. Ambiguous
or malformed destinations are refused. Existing Git Credential Manager or SSH
configuration handles authentication; no password/token storage is implemented.

Pull refuses a dirty worktree and uses fetch followed by fast-forward-only merge
with `--no-overwrite-ignore`, so ignored local files are protected too. It creates
no merge commit and uses no automatic stash or rebase. Detached HEAD, unresolved conflicts and in-progress history
operations block mutations. Hooks are disabled for these bounded operations;
commit signing is disabled to avoid interactive signing prompts. Projects that
require hooks or signed commits should commit using their normal Git workflow.
Subprocesses use argument arrays, a 60-second timeout and no interactive credential
prompts. Raw Git/gh errors are withheld and mapped to actionable error codes.

## Upload and repository creation

Upload checks the remote before staging. With a valid github.com remote it commits
if necessary, then pushes after approval. With no remote, it returns `NO_REMOTE`,
GitHub CLI readiness (`GH_READY`, `GH_UNAUTHENTICATED`, or `GH_UNAVAILABLE`) and
`repository_creation_requires_confirmation: true`, without changing files.

Automatic repository creation is deliberately not implemented. Create the intended
repository explicitly with the desired account/name/visibility and configure its
remote, then retry. JARVIS never treats `git push` as repository creation and never
requests passwords or tokens. A plain local project must first be explicitly
initialized as a Git repository. Regular pushes do not depend on `gh`.

## Root cause and verification

The prior implementation only reported whether a `.git` directory existed during
project inspection. It had no executable Git/GitHub tools, command grammar or
permission classifications; upload requests therefore fell through to chat.
The `.gitignore` also contained NUL-interleaved editor-session entries appended to
the `*.bak` line. These have been replaced with one valid UTF-8 ignore entry.
Existing editor-session files are retained.

`tests/test_git_workflow.py` uses temporary repositories and local bare remotes,
with mocked authentication failures and CLI availability. It makes no GitHub
network pushes. Run all tests with:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```
