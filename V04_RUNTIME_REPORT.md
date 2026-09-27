# JARVIS v0.4 runtime repair report

Status: repairs implemented, but v0.4 is NOT complete: real project lifecycle acceptance remains blocked and the requested eight-command microphone sequence was not completed. Phase 5 was not started.

## Root causes

1. Reproduced the installed pyttsx3/SAPI repeated-speech defect outside the sandbox. The first of five utterances emitted `finished-utterance(name="1", completed=True)`. Calls 2–5 returned immediately with `name=None, completed=False`. The installed SAPI EndStream callback ends its driver loop while pyttsx3 also queues an engine endLoop; reusing this state loses the later utterances. The old wrapper treated returning from runAndWait as success. It also retained a failed engine and permanently latched initialization failure.
2. VoiceRuntime ignored a False speech result, logged thrown failures only as warnings, and bypassed ResponseFormatter on several early-return paths. The provider factory silently substituted MockTTS if pyttsx3 was unavailable.
3. Close project was absent from parsing, registry and permission policy. Close commands were sent to generic application closing. Editor PIDs/windows were not tracked; background run/stop state was not editor ownership.
4. Real VS Code startup failed because the VS Code updater held its startup mutex. Its own main.log recorded a 30-second wait followed by `Code is currently being updated`. The old launcher reported Opened immediately after Popen, hiding this failure. All four explicit registered project directories exist, including the actual SenitalAI spelling; adding aliases would not fix this failure.
5. Opening an unresolved name could guess a filesystem path or use the first search result. The path branch also referenced project_key before assignment. Ambiguous searches exposed the first path to dependent planner steps despite asking for clarification.
6. STT returned a hardcoded confidence=1.0 for any nonempty transcript. Temporary WAV creation could leave a partial file if writing failed. Confirmation replies such as `Yes.` were not recognized because of STT punctuation.
7. Deterministic system-information matching did not tolerate sentence-ending punctuation. Added narrowly scoped punctuation handling, without modifying file arguments or conversational text.
8. Environment mismatch: plain python used the system interpreter, missing pyttsx3 and pypdf; the repository virtual environment has runtime dependencies. The initial system-Python test run had 151 passing and 5 PDF failures. The venv lacks pytest, so full verification uses its standard-library unittest runner. A sandboxed venv run also encountered Windows temp-directory ACL failures; the complete suite was rerun with approved normal-user access.

## Architecture

Push-to-talk capture (stream context manager) -> cached local Whisper model -> transcript -> structured ProjectCommand / normal router -> existing planner, permissions and confirmation tokens -> executor/tool registry -> registered project resolution and verified editor lifecycle -> ChatResponse -> one ResponseFormatter/output path -> serialized speech worker -> completion acknowledgement.

Normal conversation retains the existing LLM path. Voice confirmations consume the existing core confirmation token and pending plan; ambiguous replies execute nothing. Trailing punctuation is stripped only for strict confirmation phrase matching.

## TTS lifecycle

One short-lived child interpreter owns pyttsx3 and its COM driver for one utterance. It validates a named successful completion callback and exits. The parent serializes playback, enforces a 90-second deadline, and requires an explicit acknowledgement. subprocess.run kills and reaps its own worker on timeout. Failed/partially spoken text is not automatically repeated; the next response gets a clean worker. JARVIS and Whisper are never restarted per response. Disabled speech is explicit, and failures are counted, logged and printed.

Actual backend verification: five consecutive repaired calls in one parent provider returned True, True, True, True, True. Completion callbacks establish backend completion, not proof that a human heard the sound; the microphone acceptance session separately checks that.

## Project lifecycle and safety

A new editor gets a unique local user-data profile. State stores registry key, canonical name, trusted resolved path, launch time, Popen handle, process creation time, private profile, opened_by_jarvis and tri-state editor-open status. Opening waits up to 40 seconds for a window owned by the verified process. It checks native VS Code startup logs for the observed update-lock failure.

Close requires the same registered path, live original process, matching process creation time, exact private profile argument, and exactly one visible window owned by that process. It rechecks ownership and sends WM_CLOSE. It verifies that the window disappeared or its process exited; unsaved-work prompts remain for the user. No terminate, kill, taskkill or broad process matching is used by editor close. Legacy background-project run/stop tools remain separate.

Unregistered names do not become paths. Exact registered roots are accepted for existing planner dependencies; other paths are refused. Existing path guards remain in force. Ambiguous resolution and ambiguous search dependencies stop for clarification. Project aliases are generated/read from the registry and apply only inside project commands; ordinary conversational words are not replaced.

## Files changed

- app/voice/tts.py: bounded serialized worker transport; explicit unavailable/disabled behavior.
- app/voice/tts_worker.py (new): one-utterance engine lifecycle and completion validation.
- app/voice/runtime.py: one formatted output path, visible failures, audio serialization, exception recovery, punctuation-safe confirmations, EOF exit.
- app/voice/stt.py: unknown transcript confidence instead of fabricated certainty.
- app/voice/models.py: optional confidence default.
- app/voice/microphone.py: recording-state cleanup and partial-WAV cleanup.
- app/projects/commands.py (new): typed contextual open/close command parsing.
- app/projects/lifecycle.py (new): editor state, verified Windows ownership, startup readiness, graceful closing.
- app/projects/resolver.py: contextual close extraction and accurate debug diagnostics.
- app/tools/projects.py: registry-only launch roots, native executable discovery, tracked launch/readiness, close and editor status; ambiguous search stops dependent plans.
- app/tools/registry.py: close registration and truthful failed-open ToolResult conversion.
- app/brain/intent.py: deterministic structured project action routing.
- app/brain/permissions.py: explicit graceful close policy matching existing LOW-risk application close.
- app/brain/orchestrator.py: deterministic clarification and permission diagnostics.
- app/utils/logger.py: configurable debug logging.
- tests/test_voice_reliability.py (new): repeated speech/voice, recovery, ownership, state, unknown/ambiguous requests, real readiness semantics and continuous mocked integration.
- tests/test_projects.py: retain existing assertions; mock window readiness in unit tests.
- tests/test_project_resolver.py: retain existing assertions; mock editor launch/readiness to prevent unintended desktop launches.
- tests/test_voice_project_pipeline.py: retain existing assertions; mock editor launch/readiness.
- scripts/verify_editor_lifecycle.py (new): opt-in real isolated-editor smoke test.
- scripts/verify_voice_session.ps1 (new): actual app.main --voice acceptance session with checklist and transcript capture.
- README.md: virtual-environment launch instructions and runtime/lifecycle constraints.
- V04_RUNTIME_REPORT.md (new): this evidence and limitations report.

Runtime verification also produces logs/jarvis.log, data/v04-tests.txt, data/v04-live-console.txt and VS Code profile/log directories under data/editor-sessions/. Existing test runs use the normal test database and audit files.

## Automated tests

Final full run: total **181**, passed **181**, failed **0**, skipped **0**, duration **41.931 seconds**.

Command: `.\venv\Scripts\python.exe -m unittest discover -s tests -q`. Evidence: `data/v04-tests.txt`. The deliberate TTS-error lines at the end are from failure-injection regressions, not failed tests. Existing 156 tests are preserved and 25 regression tests were added. The final suite includes confirmation, path permissions, ambiguity, isolated ownership, recovery and continuous mocked voice execution.

Adding the ambiguous-search guard exposed an existing exact-name search case where JARVIS_v0.3_patch competed with the registered JARVIS root; exact registered identities now take precedence while genuinely ambiguous queries still stop. That regression was repaired before the final passing run.

## Manual runtime verification

The user ran the actual `app.main --voice` process continuously from 23:43:08 to 23:47:15 on 2026-09-23, then exited with q. PowerShell transcription only retained the last native-console response, so the detailed evidence below comes from the correlated application STT and real pyttsx3 completion records in logs/jarvis.log. Concurrent automated-test MockTTS records are excluded.

Five actual microphone captures were recorded, not eight:

1. STT at 23:43:45: `It will means this stuff information.` Intent=chat; operation=none; project=none. The intended system-information command was misrecognized and produced a conversational response. TTS attempted; backend completed at 23:44:28.
2. STT at 23:44:36: empty transcript. Intent=chat; operation=none; project=none. Response: `I didn't catch that.` TTS attempted; backend completed at 23:44:39.
3. STT at 23:44:47: `Open Streetlight.` Intent=project; operation=open_project; canonical=Streetlight Fault Reporting System; registered path=C:\Users\Ashwin Rathinakumar\streetlight-backend; permission=allow. Execution FAILED: the VS Code update lock prevented startup. The actual failure response was spoken; backend completed at 23:45:28.
4. STT at 23:45:39: `Sentinel AI.` Intent=chat; operation=none; project=none (no action verb was recognized). Execution produced a conversational response, not a project launch. TTS attempted; backend completed at 23:46:16.
5. STT at 23:46:47: `You bring system information.` Intent=system; operation=system_information (normal classifier fallback); project=none; permission=allow. Execution succeeded and returned system information. TTS attempted; backend completed at 23:47:03.

Every recorded real response has a completed speech acknowledgement: 5/5. The user explicitly confirmed: "Yes, all five were audible." Repeated audible speech is therefore verified in this continuous session, including the failed project-open response.

Required sequence coverage: the initial system request was misrecognized; Streetlight opening failed; Streetlight closing was not recorded; Sentinel's action verb was missing; Sentinel closing was not recorded; K.E.E.R. opening and closing were not recorded; the final system-information operation succeeded. Thus the required continuous eight-command acceptance criterion is NOT satisfied.

Before this session, three real isolated Streetlight open/close smoke attempts were blocked by VS Code's update mutex. The revised code reported startup failure and did not claim to close any window. Safe actual close remains unverified on this desktop. The independent five-response real TTS check passed in one provider instance.

## Remaining limitations

- Real editor and the full eight-command microphone acceptance must pass before v0.4 can be declared complete. The active VS Code updater must release its startup lock; an existing shared Code window opening is not proof that an isolated Code process can start. Save editor work and finish the normal VS Code update/restart flow before rerunning scripts/verify_editor_lifecycle.py and scripts/verify_voice_session.ps1. No updater process or unrelated editor was killed.
- Live STT misrecognized two system requests and omitted Sentinel's action verb. Those input errors were not silently rewritten into executable commands. Further microphone testing is required; the temporary recordings were correctly removed, so no retained waveform is available for retrospective analysis.
- Separate VS Code instances have separate user settings/trust state, consume additional resources, and can be blocked by an active VS Code update.
- Ownership tracking is in-memory. Previously opened/untracked editors are deliberately not adopted or closed after a JARVIS restart.
- More than one visible window in a tracked instance is refused. Unsaved-work dialogs require user action; no forced close occurs.
- Private profile directories are retained to avoid deleting unsaved editor recovery data.
- The 90-second speech deadline intentionally bounds native backend hangs; very long utterances can exceed it.
- Transcription confidence is unknown, not calibrated.
