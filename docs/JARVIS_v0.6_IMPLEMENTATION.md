# JARVIS v0.6 — Nemotron Intelligence Layer

## Previous architecture

JARVIS v0.5 already separated deterministic routing and execution from provider-backed conversation. v0.6 extends the existing `BaseLLMProvider`; JARVIS remains the authority for tools, permissions, confirmation, project resolution, and runtime lifecycle.

## Nemotron integration

`NemotronProvider` uses an OpenAI-compatible HTTP API: `GET /models` for health and `POST /chat/completions` for conversation. The base URL is configuration-only, so localhost, private LAN, and remote endpoints use the same code. API keys are optional and are never included in status output or logs.

Configuration:

```env
JARVIS_LLM_PROVIDER=nemotron
JARVIS_LLM_BASE_URL=http://127.0.0.1:8000/v1
JARVIS_LLM_MODEL=nvidia/nemotron
JARVIS_LLM_TIMEOUT=45
JARVIS_LLM_API_KEY=
JARVIS_LLM_TEMPERATURE=0.3
JARVIS_LLM_MAX_TOKENS=1024
JARVIS_LLM_FALLBACK=ollama
JARVIS_LLM_FALLBACK_ENABLED=true
MAX_CONTEXT_MESSAGES=10
MAX_CONTEXT_CHARS=6000
```

`JarvisBrain` selects Nemotron, Ollama, Gemini, or the test-only mock through the provider factory. A failed primary request gets at most one configured fallback attempt, with an explicit log entry. If both providers fail, conversation receives a truthful error while deterministic tools remain available.

## Context and prompting

Nemotron receives a focused JARVIS reasoning system prompt, bounded recent turns, relevant structured context, and the current request. It is told that tool awareness grants no execution authority and that it must not invent operation results. Voice waits for the complete response before TTS; `stream()` exists as a cancellable future desktop-UI seam.

## Plan proposals and execution boundary

`ReasoningPlan` accepts validated JSON proposals containing an objective, textual steps, a tool requirement flag, and proposed-action labels. Parsing has no executor reference and never runs a proposal. Malformed or hostile output returns no plan. Any future conversion to executable actions must still use registered tools, plan validation, permissions, confirmation, and the existing executor.

## Status and observability

“What model are you using?” and “Model status” route to a read-only local tool. It reports provider, model, availability, endpoint category (`local`, `LAN`, or `remote`), and fallback without revealing credentials. Provider logs contain model, endpoint category, latency, timeout, and fallback metadata, not conversation history or API keys.

## Security

Deterministic routing remains first. Nemotron never receives direct subprocess, shell, filesystem, project, or process-control authority. Model paths, commands, URLs, tool names, and arguments remain untrusted text. Existing project registry, workspace rules, permission levels, and confirmation tokens are unchanged.

## Verification and limitations

Tests cover provider selection, OpenAI-compatible requests, LAN transparency, deterministic bypass, fallback and total failure, timeout recovery to `IDLE`, bounded multi-turn context through one persistent runtime, inert plan parsing, hostile proposals, and safe model status. Existing v0.5 weather and project context tests remain part of the full suite. The completed suite contains 225 passing tests with no failures or skips.

A continuous contract-level acceptance session handled four general turns through mock Nemotron with bounded history, then weather, system information, Sentinel open/close context, and model status through deterministic tools. Every turn returned to `IDLE`, all nine responses reached mock TTS, and quit reached `STOPPED`.

No configured live Nemotron endpoint was assumed and no model was downloaded. Live endpoint, model-quality, streaming-server compatibility, and microphone acceptance remain deployment tests. Autonomous execution and distributed JARVIS server architecture are outside v0.6.
