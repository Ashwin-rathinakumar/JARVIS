# JARVIS v0.5 — Persistent Runtime & Desktop Presence

## Baseline

v0.4 provided deterministic routing, provider-backed general conversation, local push-to-talk voice, tool permissions, confirmation tokens, project lifecycle management, and weather. The pre-change suite passed 206 tests.

## Runtime architecture

`JarvisRuntime` owns one session, voice adapters, the observable `RuntimeStateMachine`, optional wake worker, and optional tray controller. It calls the existing `VoiceRuntime` and `JarvisOrchestrator`; it does not make an LLM a runtime controller.

States are `IDLE`, `LISTENING`, `TRANSCRIBING`, `THINKING`, `EXECUTING`, `SPEAKING`, `ERROR`, `STOPPING`, and `STOPPED`. Transitions are locked and observable through `RuntimeTransition` observers.

## Short-term context

`SessionState` now has `ConversationContext`: last intent, tool, project, location, and compact entities. Successful deterministic actions update it. The runtime resolves only narrow, safe follow-ups: weather “What about tomorrow?” inherits the previous weather location; “Close it” inherits the most recently resolved project. No destructive tool is inferred from a pronoun, and permissions/confirmation remain authoritative.

General LLM history remains bounded by `MAX_CONTEXT_MESSAGES`; `MAX_CONTEXT_CHARS` is documented for provider implementations.

## Voice activation and VAD

Push-to-talk remains available. `WakeWordProvider` supplies disabled and mock implementations; no fragile third-party wake engine was added. `VoiceActivityDetector` and `SilenceThresholdVAD` provide a tested local-capture seam without changing microphone behavior. A real wake/VAD engine requires later hardware validation.

## Desktop presence and lifecycle

`TrayController` provides independent callbacks for status, listening, TTS muting, console/status, and quit. It starts a `pystray` icon when its optional dependencies are installed; tray failures are logged and cannot stop the core. `shutdown()` is idempotent: it stops the wake worker, shuts down adapters/tray, releases microphone state, and enters `STOPPED`.

Launch persistent desktop mode with:

```powershell
python -m app.main --runtime
```

## Provider readiness and safety

The established `BaseLLMProvider` keeps Ollama, Gemini, and a future Nemotron provider interchangeable. Deterministic routes and all permission, confirmation, path, and project safety checks are unchanged.

## Validation and limitations

Automated coverage includes state legality/recovery, multiple turns, weather/project follow-up context, context safety, wake events, VAD semantics, and idempotent shutdown. A continuous headless acceptance session completed: greeting, Chennai weather, tomorrow follow-up, Sentinel open/close, system information, general knowledge, K.E.E.R. open/close, then shutdown. Every turn returned to `IDLE`; shutdown reached `STOPPED`; nine mocked TTS responses completed.

The real tray requires optional `pystray` and Pillow; real wake-word/VAD and microphone acceptance remain local hardware tests.
