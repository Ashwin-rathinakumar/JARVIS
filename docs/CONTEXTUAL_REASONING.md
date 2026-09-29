# JARVIS v0.9: contextual conversation and tool handoff

JARVIS is its own runtime. Its context, router, planner, permissions and tools
operate without a conversational model. Optional semantic and conversational
support can use the existing Ollama, Gemini or Nemotron adapters. No new provider,
endpoint or credentials were added. Development tools are not runtime components.
Astra/Codex refers only to the external development workflow, not JARVIS runtime.

Set `JARVIS_LLM_PROVIDER=none` (or `disabled`, `off`, or an empty value) to disable
all optional model adapters, including fallback. With both provider environment
variables absent, the default is also `none`. Existing explicit provider settings
and legacy `LLM_PROVIDER` remain supported. The local `.env` is not changed.

In disabled mode, project/Git/system/folder commands, deterministic references,
confirmation replies and the shared voice pipeline still work. General questions
and requests that need semantic interpretation return a clear model-unavailable
message. An unreachable configured model does not affect deterministic tools.
Provider constructor failures do not prevent core startup. Voice still requires
its independently configured microphone/STT/TTS dependencies.

## Shared pipeline

Text, API chat and transcribed voice input enter `JarvisOrchestrator.process`:

1. Resolve confirmation replies and explicit contextual shortcuts in this session.
2. Use existing deterministic planner/intent routes for clear commands.
3. When enabled, ask the optional provider for a semantic decision, with a concise capability catalog,
   bounded working state, registered project aliases and up to six recent turns.
4. Parse and validate the proposed mode, tool, confidence, argument names/types and
   target references. Validate semantic actions with the existing PlanValidator.
5. Apply deterministic PermissionEngine policy. The model cannot supply approval.
6. Execute the registered tool, or pause with the existing confirmation token.
7. Update state only after success. Return a grounded result; semantic tools may
   receive a model-generated explanation of their verified result.

VoiceRuntime owns capture, transcription and playback. It no longer intercepts
all non-yes/no input while an action is pending. The persistent runtime also uses
the shared reference resolver. Ending a wake listening window does not erase
the conversation's working state. No manual conversation/tool mode switch exists.

Existing controlled-agent investigations and deterministic multi-step plans remain
available through their existing policy boundaries.

## Semantic contract and capability metadata

The provider adapters expose text generation, not a common native structured-output
API. The optional model is prompted to return a JSON object. JARVIS parses JSON only for action
selection; it never extracts executable commands from prose or uses eval/exec.

```json
{
  "mode": "tool",
  "tool": "git_status",
  "arguments": {"project_name": "active_project"},
  "confidence": 0.97
}
```

Other modes are `conversation` (with an answer in `response`), `clarify`, and
`external` (an honest unsupported-current-information explanation). The semantic
catalog derives descriptions and risk levels from the tool registry and adds
closed argument schemas, target types and examples. It exposes a deliberately
bounded subset: system queries, project opening/closing/overview/folders, Git,
file listing, trusted project tests and weather. Other existing deterministic
tools retain their current routes. To extend semantic capabilities, register the
tool and declare its public argument schema in `app/brain/semantic.py`.

Unknown tools, extra parameters, low/nonfinite confidence, shell-like targets,
unknown/uncertain project names and invalid paths are refused. Missing targets
produce clarification. A model's `requires_confirmation: false` has no authority.
The knowledge-question guard prevents an explicit explanation/hypothetical from
becoming a model-selected operation.

Malformed JSON cannot execute anything. Legacy plain conversational responses are
accepted as conversation only; prose claiming execution for an action request is
refused. Provider exceptions use the configured fallback if available, otherwise
return a useful failure. Deterministic commands still work without a model. Model
requests retain each provider's existing timeout; no external calls are required
by unit tests.

## Session state and references

The existing `ConversationContext` was extended, rather than introducing another
global state store. Each SessionState has:

- `active_project` (the existing `last_project`), `previous_project` and `active_path`.
- `active_repository`, `last_tool`, `last_action` and a bounded `last_result`.
- `last_entity`, up to five recent entities, and the existing location context.
- Its existing `pending_plan` and `pending_confirmation_id`. The model sees a
  derived pending-action description and a boolean, never the confirmation token.

Successful project opening selects the project and root. Git results select the
repository without losing a previously identified backend folder. Folder discovery
or opening updates the active path. Conversational turns retain these entities.
Failures do not replace them. Previous-project navigation swaps back to the last
selected project. Ambiguous references prompt a question with recent candidates.

Explicit targets take priority. Otherwise a relevant pending action supplies the
reference for questions such as “what branch is it on first?”, followed by active
session context. Git project arguments are bound before approval. An unrelated
read-only query can update working context without retargeting a pending operation.

The model receives bounded result summaries and selected metadata, not a source
tree or the full transcript. Raw file/document contents are not retained in working
state. Stack inspection returns only recognized manifest technologies, not file
contents. Backend discovery checks the named folder, then unambiguous backend,
server or api candidates; a Python project root can itself be the backend. Missing
or ambiguous layouts require clarification rather than a guessed path.

Folder navigation uses Explorer with an argument array. Project folders must
resolve inside their registered root, including after symlink resolution. Downloads
is an explicit navigation-only known location; it does not expand file-write access.

## Pending actions and safety

`yes`, `go ahead`, `no`, `cancel` and their existing voice variants use the same
deterministic handling for text and voice. Punctuation does not change approval.
“Maybe” keeps the request pending. Read-only follow-ups preserve it. A new mutating
request replaces/revokes the old pending approval and receives its own confirmation
when required. Cancellation/expiration revokes execution eligibility.

Approval validates the token-bound tool and resolved arguments against the paused
step before execution. API confirmation and cancellation require a matching token
in the caller's session and use the same orchestrator. A modified pending plan
cannot reuse approval for its old target. Tools revalidate project/filesystem state
at execution time; the existing Git safeguards remain in place.

Read-only queries need no confirmation. Folder/project opening retains low risk.
Commit/pull/tests retain medium risk, and Git push/upload retain high risk. No new
delete or arbitrary shell capability was added. Automatic repository creation
remains outside the Git workflow.

## Responses, current information and observability

General questions receive provider-generated explanations. Common Git status results
get a concise deterministic summary without a second model call. Semantically routed
successful tools can be explained by the optional model using only the supplied result; failures
remain explicit. “Show raw result” returns the stored detailed message, while “show
me the full git status” refreshes detailed Git status. Original structured tool data
remains on ChatResponse. Confirmed plan results use the existing truthful executor
summary. Failed summary generation falls back to the original tool message.

Weather uses the existing live weather capability, never system information.
The semantic contract identifies unsupported external information; a guard also
rejects unsupported current news, prices, scores and similar requests rather than
accepting an invented model answer. No web search/news capability was added.

Set `JARVIS_LOG_LEVEL=DEBUG` to inspect input, selected intent/tool, resolved target,
permission decision and execution outcome. Normal logs remain concise. Credential
patterns are redacted; voice output content and file/document result contents are
omitted from logs/audits. This is defense in depth, not a universal secret detector.

## Manual conversation test

Start text mode with `.\venv\Scripts\python.exe -m app.main`, or use `--voice`
for push-to-talk. Keep the same session. Tests below do not require committing or
pushing anything; cancel the mutation prompts.

1. “What is FastAPI?” → a normal explanation, no local tool.
2. “Open Streetlight.” → project opens and becomes active.
3. “Check its git status.” → Streetlight branch/change summary.
4. “What does that mean?” → explanation using the previous Git result.
5. “Show me the full git status.” → detailed paths.
6. “Commit those changes as test contextual reasoning.” → confirmation.
7. “No.” → commit cancelled.
8. “What's my operating system?” → system information tool.
9. “What is an operating system?” → normal explanation.
10. “Open Sentinel.” → active project switches after successful opening.
11. “What's this project built with?” → bounded project manifest inspection.
12. “Show me its backend.” → identified folder or a truthful ambiguity/missing result.
13. “Open that folder.” → the identified folder opens in Explorer.
14. “Go back to the project root.” → Sentinel root opens.
15. “Push it.” → confirmation for Sentinel.
16. “What branch is it on first?” → read-only query; push remains pending.
17. “Actually push JARVIS instead.” → old token revoked; new confirmation for JARVIS.
18. “No.” → new push cancelled.
19. “Now tell me what dependency injection is.” → normal explanation.

Also try “Let's work on Streetlight”, “Take me to JARVIS”, “Is this repository
clean?” and “Are there any changes here?”. These exercise the semantic provider,
not an exhaustive collection of phrase-specific regular expressions.

## Verification and limits

`tests/test_contextual_reasoning.py` uses temporary projects and mocked semantic
providers/executors. It covers intent distinctions, natural variants, session
isolation, references, folder boundaries, grounded metadata, pending-action
replacement, voice parity, malformed/hostile model output, failure fallback and
permission enforcement. Existing Git tests continue using local bare repositories.
Run the entire suite with:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -q
```

These tests verify contracts and safety independently of external availability.
Live linguistic quality depends on the configured provider/model and must be
checked with the manual script. No live microphone, model-quality evaluation,
GitHub publication or external-resource creation is implied by passing unit tests.

Final verification on 2026-09-28: the complete unittest suite passed all 335 tests
(63 new contextual tests) in 104.089 seconds, with no failures or errors. The run
log is `logs/contextual-tests.txt`. Existing Git and voice tests were preserved.

The subsequent optional-provider correction passed all 350 tests (15 additional
no-provider tests) in 67.639 seconds, with no failures or errors. Its complete log
is `logs/optional-provider-tests.txt`. Tests verify local project/Git/system/folder
references, confirmation and voice transcript handling without a model adapter,
plus safe startup and operation when a configured adapter fails.
