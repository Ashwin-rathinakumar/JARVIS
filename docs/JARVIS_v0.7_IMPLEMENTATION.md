# JARVIS v0.7 — Controlled Agentic Planning & Multi-Step Execution

## Architecture

v0.7 builds on the v0.6 provider layer without changing deterministic routing. Explicit investigation/diagnostic task language may create one `AgentRun` per session. Nemotron proposes JSON; JARVIS parses and validates it, looks up an allowlisted registered action, applies the existing permission policy, pauses on the existing confirmation token system, executes one tool, records a bounded observation, and asks for the next proposal.

There is no raw-shell capability and no model output is passed to `subprocess`. The only subprocess introduced is `run_project_tests`, whose command, working directory, and timeout come from trusted project configuration.

## Run and step state

`AgentRun` records run/session IDs, objective, timestamps, explicit status, current step, steps, observations, limits, confirmation token, and final summary. Statuses are `PENDING`, `PLANNING`, `WAITING_FOR_CONFIRMATION`, `EXECUTING`, `OBSERVING`, `REPLANNING`, `COMPLETED`, `FAILED`, `CANCELLED`, and `STEP_LIMIT_REACHED`.

Each `AgentStep` contains only an allowlisted action, schema-validated arguments, reason, status, permission level, bounded result, and retry count. Each `AgentObservation` records success, bounded evidence, data, and error.

## Initial capability registry

The machine-readable registry exposes only `inspect_project`, `project_status`, `list_project_files`, `read_project_file`, `search_project_text`, `run_project_tests`, `system_information`, and `get_weather`. Capability descriptions and risk levels are generated from this registry and the existing permission map.

Project file operations require a registered project, resolve relative paths under its trusted root, reject traversal/absolute paths, and bound file size, lines, searches, and returned content. Project tests use the registered `test_command` list with `shell=False`, a bounded timeout, and captured output. Sentinel has a trusted pytest command; projects without one return an unsupported result.

## Validation, permission, and confirmation

Plans reject unknown actions/projects, unknown arguments, command/shell/URL arguments, unsafe paths, malformed structures, and excess steps before execution. Every step is validated again immediately before action. Existing `PermissionEngine` decisions remain authoritative. Medium-risk test execution pauses in `WAITING_FOR_CONFIRMATION`; approval consumes the existing confirmation token, and denial cancels the run without execution.

## Loop, limits, cancellation, and audit

The loop is plan → validate → execute one registered step → bounded observation → replan. Defaults are eight steps, one retry, and 300 seconds overall. Permission denial and invalid plans are never retried. Only one unfinished run is permitted per session. Cancellation removes a pending confirmation and marks the run cancelled.

Every executed step uses the existing SQLite audit writer with run ID, session ID, step ID, action, risk, permission decision, result, and `source=agent`. Lifecycle transitions also emit structured log metadata.

Final summaries label actual observations separately from the model's proposed conclusion, preventing inference from being presented as execution evidence.

## Configuration

```env
JARVIS_AGENT_ENABLED=true
JARVIS_AGENT_MAX_STEPS=8
JARVIS_AGENT_MAX_RETRIES=1
JARVIS_AGENT_MAX_RUNTIME_SECONDS=300
JARVIS_AGENT_OBSERVATION_CHARS=6000
```

## Tests and limitations

Coverage includes creation, conversation bypass, plan-act-observe-replan completion, generated capability discovery, unknown and hostile actions, traversal and unknown projects, step/retry/time limits, confirmation approval/denial, cancellation, provider failure, malformed plans, audit calls, and persistent-runtime recovery.

The final suite passed 236 tests with no failures or skips. Acceptance used a scripted reasoning provider and mocked registered-tool results: the Sentinel run executed project inspection, paused before medium-risk tests, consumed approval, observed a failing test result, replanned, and completed with two observations. A PowerShell deletion proposal was rejected with zero executions. A separate test-run proposal reached `WAITING_FOR_CONFIRMATION` with an existing confirmation token and zero execution before approval.

A second acceptance run used the real registered `system_information` tool through the complete reason → validate → permission → execute → observe → replan → finish path. It completed with one successful audited observation and a grounded final summary.

v0.7 is read/diagnostic-first. It does not apply patches, expose shell commands, run concurrent agents, browse autonomously, control the desktop, or execute distributed workers. Phase 8 is not started.
