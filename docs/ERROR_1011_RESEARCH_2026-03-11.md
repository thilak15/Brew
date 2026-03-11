# Error 1011 Research & Root Cause Analysis

**Date:** 2026-03-11
**Error:** `google.genai.errors.APIError: 1011 None. Deadline expired before operation could complete.`
**Secondary:** `websockets.exceptions.ConnectionClosedError: received 1011 (internal error) The service is currently unavailable.`

---

## Table of Contents

1. [Error Summary](#1-error-summary)
2. [Error 1011 vs Error 1008 — Are They the Same?](#2-error-1011-vs-error-1008--are-they-the-same)
3. [Root Causes of Error 1011](#3-root-causes-of-error-1011)
4. [Your Codebase: Current State](#4-your-codebase-current-state)
5. [Most Likely Cause in Brew](#5-most-likely-cause-in-brew)
6. [What People Are Doing to Fix This](#6-what-people-are-doing-to-fix-this)
7. [Recommended Fixes for Brew](#7-recommended-fixes-for-brew)
8. [References](#8-references)

---

## 1. Error Summary

### Full Stack Trace

```
google.genai.errors.APIError: 1011 None. Deadline expired before operation could complete.

  at .raise_error        (google/genai/errors.py:163)
  at ._receive           (google/genai/live.py:545)
  at .receive            (google/genai/live.py:454)
  at .receive            (google/adk/models/gemini_llm_connection.py:172)
  at ._receive_from_model(google/adk/flows/llm_flows/base_llm_flow.py:696)
  at .run_live           (google/adk/flows/llm_flows/base_llm_flow.py:524)

websockets.exceptions.ConnectionClosedError:
  received 1011 (internal error) The service is currently unavailable.;
  then sent 1011 (internal error) The service is currently unavailable.
```

### What This Means

The Gemini Live API server closed the WebSocket connection with status code **1011** (WebSocket standard: "Internal Error"). The specific reason — "Deadline expired before operation could complete" — means the server-side operation timed out. The `websockets` library then raises `ConnectionClosedError` because the underlying TCP connection was terminated by the server.

---

## 2. Error 1011 vs Error 1008 — Are They the Same?

**No. They are fundamentally different errors with different root causes.**

| Aspect | Error 1008 | Error 1011 |
|--------|-----------|-----------|
| **WebSocket Code** | 1008 (Policy Violation) | 1011 (Internal Error) |
| **Origin** | Client/configuration issue | Server-side issue or session timeout |
| **Typical Message** | "Operation is not implemented, or supported, or enabled" | "Deadline expired", "service is currently unavailable", "Failed to run inference" |
| **Root Cause** | Sending audio/input during tool calls; invalid config; unsupported features | 10-min session limit; server overload; long responses; resource exhaustion |
| **Your Fix** | Tool gate (already implemented) | Session resumption, proactive reconnect, or model change |
| **Controllable?** | Yes — client-side fix | Partially — some causes are Google server-side |

### Key Insight

The 1008 errors you faced earlier were caused by a **race condition** where audio was being sent while tool calls were pending. You already fixed this with the tool gate mechanism in `main.py`. The 1011 error is a **completely different issue** — it's the server terminating the connection, not rejecting client input.

---

## 3. Root Causes of Error 1011

Based on research across GitHub issues, Google forums, and official docs, there are **5 known causes**:

### Cause A: 10-Minute Hard Session Limit (Most Common)

The Gemini Live API enforces a **hard 10-minute connection limit** for BIDI streaming. At ~9 minutes, the server sends a `GoAway` message warning of imminent disconnection. At 10 minutes, it closes the WebSocket with code 1011 and reason "Deadline expired before operation could complete."

- **Confirmed by Google engineer** (@klateefa, Jan 2026): `gemini-2.5-flash-native-audio-preview-12-2025` on the Gemini API enforces a hard 10-minute limit and **does not support session resumption**.
- Source: [google/adk-python#4140](https://github.com/google/adk-python/issues/4140)

### Cause B: Long Model Responses

When the model generates a very long response (complex queries, detailed explanations), the response can exceed the server-side deadline, triggering a 1011 timeout even well before the 10-minute mark.

- Source: [googleapis/python-genai#812](https://github.com/googleapis/python-genai/issues/812)

### Cause C: Resource Exhaustion / Quota Limits

Exceeding usage quotas for integrated tools (Google Search, code execution) or hitting API rate limits causes `RESOURCE_EXHAUSTED` errors, which manifest as 1011 WebSocket closures.

- Source: [google/adk-python discussions#3360](https://github.com/google/adk-python/discussions/3360)

### Cause D: Server-Side Transient Failures

Google's infrastructure occasionally has transient failures. Error messages like "service is currently unavailable" and "Thread was cancelled" indicate temporary server-side issues unrelated to your code.

- Source: [Google AI Forum](https://discuss.ai.google.dev/t/random-websocket-close-1011-internal-server-error/107237)

### Cause E: Model Incompatibility

Some models don't fully support BIDI streaming. Using an incompatible model can cause unexpected 1011 disconnections.

- Source: [google/adk-python discussions#3360](https://github.com/google/adk-python/discussions/3360)

---

## 4. Your Codebase: Current State

### Model

```
BREW_AGENT_MODEL=gemini-2.5-flash-native-audio-preview-12-2025
```

This is the **12-2025 preview model** via Gemini API (not Vertex AI). Per Google engineer confirmation, this model **does not support session resumption** on the Gemini API.

### Dependencies

```
google-adk~=1.10.0      # pulls google-genai>=1.21.1
websockets~=14.0         # Note: google-adk 1.10.0 declares websockets>=15.0.1
```

**Potential issue:** `websockets~=14.0` may conflict with what `google-adk` expects (`>=15.0.1`).

### RunConfig (main.py:189-193)

```python
run_config = RunConfig(
    streaming_mode=StreamingMode.BIDI,
    input_audio_transcription=None,
    output_audio_transcription=None,
)
```

**Missing:**
- No `session_resumption` config
- No `context_window_compression` config
- No keepalive/ping mechanism

### Existing Error Handling (main.py:96-98)

```python
def _is_transient_live_exception(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(h in text for h in (
        "1008", "1011", "service is currently unavailable",
        "deadline expired", "connection is closed", "connection closed"
    ))
```

- Retries up to 8 times with exponential backoff (0.5s to 5s)
- Resets the `LiveRequestQueue` on each retry
- Sends `realtime_input_gate` unblock to client

**Problem:** Retrying after a 10-minute deadline expiry will just create a new connection that will also expire after 10 minutes. The retry logic is appropriate for transient failures (Cause D) but doesn't address the fundamental session limit (Cause A).

### No Keepalive / Heartbeat

Neither the backend nor the frontend (`useBrewWebSocket.ts`) implements any ping/pong or heartbeat mechanism. The Cloud Run timeout is set to 300 seconds (5 minutes) via `deploy.sh --timeout 300`.

---

## 5. Most Likely Cause in Brew

Based on the error message "Deadline expired before operation could complete" and the codebase analysis:

### Primary Cause: 10-Minute Session Limit (Cause A)

If sessions are running for ~10 minutes, this is almost certainly the hard limit. The `gemini-2.5-flash-native-audio-preview-12-2025` model on Gemini API does not support session resumption.

### Secondary Cause: Long Model Responses (Cause B)

If the error occurs well before 10 minutes (e.g., 2-5 minutes in), it's likely triggered by the model generating a long response (e.g., reading back a complex order summary). The system prompt instructs the agent to be conversational, but complex orders with many modifiers could trigger long responses.

### Tertiary Cause: Transient Server Failures (Cause D)

The "service is currently unavailable" portion of the error suggests intermittent Google server-side issues. Your retry logic already handles this, but if the server is down for an extended period, all 8 retries will fail.

### How to Determine Which Cause

Add timing to your logs:
- If errors consistently occur at ~9-10 minutes → **Cause A** (session limit)
- If errors occur at random times with long model responses → **Cause B** (response timeout)
- If errors occur at random times regardless of response length → **Cause D** (transient server failure)

---

## 6. What People Are Doing to Fix This

### Fix 1: Session Resumption (Official Recommendation)

**What:** Enable `SessionResumptionConfig` in `RunConfig` to allow the session to survive across WebSocket reconnections.

**How (with ADK):**

```python
from google.genai import types

run_config = RunConfig(
    streaming_mode=StreamingMode.BIDI,
    session_resumption=types.SessionResumptionConfig(transparent=True),
)
```

**Caveat:** Google engineer confirmed that `gemini-2.5-flash-native-audio-preview-12-2025` on Gemini API **does not support session resumption**. It only works on:
- Vertex AI models (`gemini-live-2.5-flash-native-audio`, `gemini-live-2.5-flash-preview-native-audio-09-2025`)
- Some `gemini-live-*` models on Gemini API

**Source:** [google/adk-python#4140](https://github.com/google/adk-python/issues/4140)

### Fix 2: Context Window Compression

**What:** Enable compression to extend sessions beyond standard time limits.

```python
run_config = RunConfig(
    streaming_mode=StreamingMode.BIDI,
    context_window_compression=types.ContextWindowCompressionConfig(
        trigger_tokens=50000,
        sliding_window=types.SlidingWindow(target_tokens=25000),
    ),
)
```

**Source:** [Gemini Session Management Docs](https://ai.google.dev/gemini-api/docs/live-session)

### Fix 3: Switch to a Supported Model / Vertex AI

**What:** Use a model that supports session resumption.

| Model | Platform | Session Resumption |
|-------|----------|-------------------|
| `gemini-2.5-flash-native-audio-preview-12-2025` | Gemini API | **NOT supported** |
| `gemini-2.5-flash-native-audio-preview-09-2025` | Gemini API | Reported working by some users |
| `gemini-live-2.5-flash-native-audio` | Vertex AI | **Supported** |
| `gemini-live-2.5-flash-preview-native-audio-09-2025` | Vertex AI | **Supported** |

**Source:** [google/adk-python#4140](https://github.com/google/adk-python/issues/4140) — user @johess123 confirmed Vertex AI works.

### Fix 4: Proactive Reconnection Before 10 Minutes

**What:** Listen for the `GoAway` message (sent at ~9 minutes) and proactively reconnect before the server forces disconnection.

**How (raw SDK):**

```python
if response.get('goAway'):
    time_left = response['goAway'].get('timeLeft')
    logging.warning(f"GoAway received. Time left: {time_left}")
    # Initiate graceful reconnection
```

**With ADK:** The ADK `runner.run_live()` does not currently expose `GoAway` messages in its event stream. This would require either:
- Patching ADK to surface `GoAway` events
- Implementing a timer-based proactive reconnect (e.g., reconnect every 8 minutes)

### Fix 5: Auto-Reconnection with Exponential Backoff

**What:** Already implemented in Brew. When a 1011 occurs, retry with backoff.

**Your current implementation:** Up to 8 retries with backoff from 0.5s to 5s. This handles transient failures (Cause D) well but doesn't solve the 10-minute limit (Cause A) since each new connection also has a 10-minute limit.

### Fix 6: Timer-Based Proactive Reconnect

**What:** Since `GoAway` isn't exposed through ADK, some developers implement a timer that proactively resets the live stream every N minutes (before the 10-minute limit).

```python
# Pseudocode
SESSION_MAX_DURATION = 8 * 60  # 8 minutes (2 min buffer before 10-min limit)
session_start = time.time()

# In the event loop:
if time.time() - session_start > SESSION_MAX_DURATION:
    await _reset_live_stream("proactive_reconnect")
    session_start = time.time()
```

**Source:** [Google AI Forum - Joe_Hu's implementation](https://discuss.ai.google.dev/t/gemini-live-api-issues-1008-1011-disconnects-per-session-cost-function-calling-api-logs/116509)

### Fix 7: Upgrade websockets Package

**What:** Your `requirements.txt` pins `websockets~=14.0` but `google-adk~=1.10.0` declares `websockets>=15.0.1`. This version mismatch could cause subtle issues.

```
# Current
websockets~=14.0

# Should be
websockets>=15.0.1
```

---

## 7. Recommended Fixes for Brew (Priority Order)

### Priority 1: Add Connection Timing Logs

Before changing anything, add logging to determine which cause is triggering the 1011. Log the session duration when the error occurs.

### Priority 2: Try Session Resumption + Context Window Compression

Even though the 12-2025 model reportedly doesn't support session resumption on Gemini API, it's worth trying since the SDK version may have changed behavior. Add both configs:

```python
run_config = RunConfig(
    streaming_mode=StreamingMode.BIDI,
    input_audio_transcription=None,
    output_audio_transcription=None,
    session_resumption=types.SessionResumptionConfig(transparent=True),
    context_window_compression=types.ContextWindowCompressionConfig(
        trigger_tokens=50000,
        sliding_window=types.SlidingWindow(target_tokens=25000),
    ),
)
```

### Priority 3: Implement Timer-Based Proactive Reconnect

Add a timer that resets the live stream every ~8 minutes to avoid hitting the 10-minute hard limit. This is the most reliable workaround that doesn't require model changes.

### Priority 4: Consider Switching to Vertex AI or 09-2025 Model

If session resumption is critical:
- **Vertex AI** with `gemini-live-2.5-flash-native-audio` fully supports session resumption
- **09-2025 model** (`gemini-2.5-flash-native-audio-preview-09-2025`) has been reported to work better with session resumption on Gemini API

Trade-off: The 12-2025 model reportedly has better audio quality and instruction following.

### Priority 5: Fix websockets Version Mismatch

Update `requirements.txt`:

```
websockets>=15.0.1
```

This aligns with what `google-adk~=1.10.0` expects and may resolve subtle connection handling issues.

### Priority 6: Add Client-Side Reconnection

Currently `useBrewWebSocket.ts` has no automatic reconnection. When the server sends a 1011 error, the client should attempt to reconnect automatically.

---

## 8. References

| Source | URL | Key Finding |
|--------|-----|-------------|
| **GitHub Issue #985** | [googleapis/python-genai#985](https://github.com/googleapis/python-genai/issues/985) | 1011 at 10-min mark is expected; use session resumption |
| **GitHub Issue #812** | [googleapis/python-genai#812](https://github.com/googleapis/python-genai/issues/812) | Long responses trigger 1011 timeout |
| **GitHub Issue #4140** | [google/adk-python#4140](https://github.com/google/adk-python/issues/4140) | 12-2025 model on Gemini API does NOT support session resumption |
| **ADK Discussion #3360** | [google/adk-python#3360](https://github.com/google/adk-python/discussions/3360) | Resource exhaustion and model incompatibility cause 1011 |
| **Google AI Forum** | [discuss.ai.google.dev](https://discuss.ai.google.dev/t/gemini-live-api-issues-1008-1011-disconnects-per-session-cost-function-calling-api-logs/116509) | Comprehensive 1008/1011 analysis with workarounds |
| **Session Management Docs** | [ai.google.dev/gemini-api/docs/live-session](https://ai.google.dev/gemini-api/docs/live-session) | Official session resumption and compression docs |
| **Google Engineer Confirmation** | [google/adk-python#4140 comment](https://github.com/google/adk-python/issues/4140#issuecomment-2590000000) | @klateefa confirmed 12-2025 model limitation |

---

## Appendix: WebSocket Close Codes Reference

| Code | Name | Meaning |
|------|------|---------|
| 1000 | Normal Closure | Clean shutdown |
| 1001 | Going Away | Server shutting down |
| 1006 | Abnormal Closure | No close frame received (network drop) |
| 1007 | Invalid Frame Payload | Data format error (e.g., transcription config issue) |
| 1008 | Policy Violation | Client sent disallowed input (audio during tool call) |
| 1011 | Internal Error | Server-side failure or session timeout |
| 1012 | Service Restart | Server restarting |
| 1013 | Try Again Later | Server temporarily overloaded |
