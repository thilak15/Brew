# APIError 1008 Troubleshooting Guide (Brew)

## Error You Are Seeing

```
google.genai.errors.APIError: 1008 None. Operation is not implemented, or supported, or enabled.
```

This happens inside ADK `run_live()` while using Gemini Live API over WebSocket.

## What This Usually Means

`1008` is a Live API WebSocket close code. In practice, for Gemini/ADK, it most commonly means one of these:

1. The selected model is not stable for the requested live operation (or has a temporary backend issue).
2. Model + platform mismatch (AI Studio model name vs Vertex model name).
3. A feature combination is unsupported for that model/version (for example, function-calling edge cases in some preview native-audio builds).
4. Capability/enablement mismatch in project/account/region/tier.

## What Is True In Your Current Brew Code

From your codebase:

- `backend/agent.py` defaults to:
  - `gemini-2.5-flash-native-audio-preview-09-2025`
- `backend/.env.example` and `README.md` configure:
  - `GOOGLE_GENAI_USE_VERTEXAI=FALSE` (AI Studio API key path, not Vertex)
- `backend/main.py` uses:
  - `Runner.run_live(...)` with `StreamingMode.BIDI` and raw PCM live audio
- Your frontend sends proper PCM blobs (`audio/pcm;rate=16000`) and backend sends 24kHz PCM out.

Runtime evidence from your backend logs shows many historical `1008` occurrences, and recent `1011 Deadline expired` closures. This indicates live-session instability and timeout handling are both relevant.

## Most Likely Root Causes (Ranked)

### 1) Preview model instability/regression (highest likelihood)

Your default model is a preview build (`...preview-12-2025`). Public issues report intermittent `1008` on this family, especially around live audio + tool-calling.

- Example issue: [js-genai #1236](https://github.com/googleapis/js-genai/issues/1236)

### 2) Model/provider mismatch

AI Studio and Vertex use different model namespaces in many cases:

- AI Studio-style: `gemini-2.5-flash-native-audio-preview-...`
- Vertex-style: `gemini-live-2.5-flash-native-audio` / `gemini-live-...`

Using a model name that does not match your provider mode can produce policy/unsupported errors.

### 3) Unsupported operation combo for specific preview versions

Known reports show `1008` occurring only in certain turns (for example, when tool-calling is triggered), even if basic conversation works.

### 4) Session lifecycle hardening gaps

Live API connections naturally close around time limits; if session resumption/reconnect handling is not robust, failures can surface as API errors.

### 5) Quota/tier/enablement constraints

If concurrency/session or entitlement constraints are hit, Live API can close with policy-like behavior.

## Recommended Fix Plan

## Phase A - Immediate Stabilization (quickest path)

0. **Gate realtime input during pending tool calls**
   - Community reports (2026) show a reproducible `1008` pattern when audio/activity frames are sent while a tool call is pending.
   - This is not yet clearly documented as an official protocol requirement, but it is a practical and low-risk mitigation.
   - In Brew, this is implemented by pausing/dropping realtime audio/activity signals from the moment a function call is observed until function response/cancellation is observed.

1. **Set an explicit model in `backend/.env`**
   - Do not rely on implicit default in `agent.py`.
2. **Try a fallback model version known to be more stable in your environment**
   - For AI Studio mode (`GOOGLE_GENAI_USE_VERTEXAI=FALSE`), test:
     - `BREW_AGENT_MODEL=gemini-2.5-flash-native-audio-preview-09-2025`
   - If this reduces/disables `1008`, the issue is model-version specific.
3. **Rebuild/restart backend container** and test 10-15 voice sessions.

## Phase B - Production-Grade Stability

1. **Migrate to Vertex Live GA model for best stability**
   - Use Vertex auth and set:
     - `GOOGLE_GENAI_USE_VERTEXAI=TRUE`
     - `BREW_AGENT_MODEL=gemini-live-2.5-flash-native-audio`
2. **Enable session resumption in `RunConfig`**
   - Helps survive normal connection turnover and reduce fragile reconnect behavior.
3. **Add controlled fallback/retry policy**
   - If model returns `1008` during setup/first turn, switch once to backup model and continue.
4. **Keep response modality single for ADK BIDI**
   - `AUDIO` only; avoid enabling optional features until baseline is stable.

## Concrete Changes To Make

### 1) Environment configuration

In `backend/.env`:

```env
# Current path: AI Studio key mode
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=...
BREW_AGENT_MODEL=gemini-2.5-flash-native-audio-preview-09-2025
```

If migrating to Vertex:

```env
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=...
GOOGLE_CLOUD_LOCATION=us-central1
BREW_AGENT_MODEL=gemini-live-2.5-flash-native-audio
```

### 2) Make model choice explicit in code

In `backend/agent.py`, keep env-driven model selection and avoid hard-coded preview-only defaults for production.

### 3) Harden run config in `backend/main.py`

Use:

- `streaming_mode=StreamingMode.BIDI`
- `session_resumption=types.SessionResumptionConfig()` (recommended)
- Keep audio transcription disabled until stable baseline is confirmed.

### 4) Improve transient error handling

Classify live errors:

- Retryable/transient: `1011`, network close, deadline close
- Model capability errors: repeated `1008` on same model -> switch model version/provider path
- Tool-call window race: if `1008` correlates with function-calling turns, keep realtime-input gate enabled during pending tool calls

## Verification Checklist

After applying changes, run this acceptance test:

1. Start backend and frontend.
2. Run 10+ voice sessions (with tool-calling prompts).
3. Confirm:
   - No `APIError 1008` in backend logs.
   - No session drop before first response.
   - Tool calls still execute.
   - Audio round-trip remains stable.
4. Run one long session (>10 min) and ensure reconnect/resumption works cleanly.

## Quick Diagnostic Commands

Use these from repo root:

```bash
docker compose up -d --build
docker logs -f brew-backend-1
```

Look for:

- bad: `APIError: 1008 ... not implemented/supported/enabled`
- bad: repeated `1011 Deadline expired` without graceful recovery
- good: stable turns, normal tool calls, predictable session closes and reconnects

## When the agent goes silent (local or Docker)

If the agent stops speaking mid-order, check backend logs to see why.

### Where logs are written

- **Local run** (e.g. `cd backend && uvicorn main:app --port 8000`): `backend/debug_logs/backend.log` (and stdout).
- **Docker Compose:** `./debug_logs/backend.log` (mounted from container `/app/debug_logs`).

### What to look for

1. **Thought-only events** — Model is “thinking” but not producing audio; we skip those so the client doesn’t get empty content.  
   - Log: `Skipping thought-only event (no audio) — agent is thinking, not speaking`  
   - If you see many of these in a row, the model may be stuck in a long chain of thought. Try speaking again or a shorter prompt.

2. **Live API error** — Connection or server error; client should show an error.  
   - Log: `Live API error: code=... message=...`  
   - Codes 1008 / 1011: see the rest of this doc and the tool-call gating workaround.

3. **Downstream task exception** — The event loop crashed (e.g. after 1011).  
   - Log: `Downstream task: ...`  
   - Restart the backend and try again.

4. **Tool gate** — Audio from the client is dropped while a tool call is pending. That doesn’t by itself make the *agent* silent; if the model never gets a tool response (bug or timeout), it might not speak.  
   - Log: `Dropped ... audio chunks while tool call pending`  
   - Check that tool calls complete (e.g. `TOOL SUCCESS` in logs from `agent.py`).

### Common cause: client closed before agent finished speaking

If the log shows **`connection closed`** (uvicorn) and then **right after** the backend receives a `server_content` message with **audio** from the model, the client (browser) disconnected before the agent’s response was sent. So the user never hears that last phrase — it “went silent” because the connection was already closed. Typical causes:

- User clicked **“Pull Forward”** (or closed the tab) before the agent finished the final readback (“You can pull up to the window!”).
- Network drop or frontend error closing the WebSocket.

**Mitigation:** Avoid closing the WebSocket as soon as the user taps “Pull Forward.” For example: wait for `turnComplete` or add a short delay so the last agent audio can be sent and played, or show “Agent is finishing up…” and disable the button until the current turn is complete.

### Quick commands

```bash
# Local: tail backend log
tail -f backend/debug_logs/backend.log

# Docker Compose: tail backend log (log file can be large; use tail -n to limit)
tail -n 5000 debug_logs/backend.log | grep -E "Skipping thought-only|Live API error|Downstream task|connection closed|TOOL CALL|TOOL SUCCESS|CLOSE"

# Grep for silence-related lines (on a recent slice to avoid slow full-file grep)
tail -n 10000 debug_logs/backend.log | grep -E "Skipping thought-only|Live API error|Downstream task|Dropped.*audio chunks|TOOL CALL|TOOL SUCCESS"
```

## References

- Gemini Live API overview:
  - https://cloud.google.com/vertex-ai/generative-ai/docs/live-api
- Gemini 2.5 Flash Live model docs:
  - https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash-live-api
- ADK streaming RunConfig guide:
  - https://google.github.io/adk-docs/streaming/dev-guide/part4/
- Public issue tracking intermittent 1008:
  - https://github.com/googleapis/js-genai/issues/1236
