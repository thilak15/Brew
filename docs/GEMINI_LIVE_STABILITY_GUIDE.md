# Brew — Gemini Live API Stability & Error Handling Guide

**Date:** 2026-03-11
**Scope:** Complete documentation of every WebSocket error encountered, root causes, diagnostic process, and implemented solutions.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Error 1008 — Policy Violation](#2-error-1008--policy-violation)
3. [Error 1011 — Deadline Expired / Internal Error](#3-error-1011--deadline-expired--internal-error)
4. [The Tool Gate — Preventing 1008 During Tool Calls](#4-the-tool-gate--preventing-1008-during-tool-calls)
5. [The Thought-State Race Condition — Why 1008 Still Happens](#5-the-thought-state-race-condition--why-1008-still-happens)
6. [Reconnection & Context Recovery](#6-reconnection--context-recovery)
7. [Order State Persistence Across Reconnects](#7-order-state-persistence-across-reconnects)
8. [Audio Replay — Attempted and Removed](#8-audio-replay--attempted-and-removed)
9. [Diagnostic Logging System](#9-diagnostic-logging-system)
10. [Approaches Considered](#10-approaches-considered)
11. [Current Architecture (Final)](#11-current-architecture-final)
12. [Known Limitations](#12-known-limitations)
13. [Timeline of Changes](#13-timeline-of-changes)
14. [References](#14-references)

---

## 1. Architecture Overview

Brew uses a real-time voice ordering system built on:

```
┌──────────┐    WebSocket     ┌──────────────┐    BIDI Stream    ┌────────────────┐
│ Frontend │ ◄──────────────► │   Backend    │ ◄───────────────► │ Gemini Live API│
│ (Next.js)│   audio + JSON   │  (FastAPI)   │   audio + events  │ (Google)       │
└──────────┘                  └──────────────┘                   └────────────────┘
                                    │
                                    ▼
                              ┌──────────┐
                              │OrderState│  (in-memory + Firestore)
                              └──────────┘
```

**Key components:**

| Component | File | Role |
|-----------|------|------|
| WebSocket handler | `backend/main.py` | Bridges frontend ↔ Gemini Live API via ADK `run_live()` |
| Agent definition | `backend/agent.py` | Defines the Brew agent with tools (add_item, set_modifier, etc.) |
| Order state | `backend/order_state.py` | Server-side cart persistence (in-memory + Firestore sync) |
| System prompt | `backend/system_prompt_09.md` | Behavioral instructions for the Gemini model |
| Frontend hook | `frontend/lib/useBrewWebSocket.ts` | Manages client WebSocket, audio gate, and state dispatch |
| Audio pipeline | `frontend/lib/audioPipeline.ts` | Captures mic audio and plays back model audio |

**Model:** `gemini-2.5-flash-native-audio-preview-12-2025` via Gemini API (not Vertex AI).

**Streaming mode:** `StreamingMode.BIDI` — bidirectional audio streaming where the user and model can speak simultaneously.

---

## 2. Error 1008 — Policy Violation

### What It Is

```
google.genai.errors.APIError: 1008 None. Operation is not implemented, or supported, or enabled.
websockets.exceptions.ConnectionClosedError: received 1008 (policy violation)
```

WebSocket close code **1008** means the server rejected client input because it violated a protocol policy. The Gemini Live API sends this when the client sends audio or input at a time the server considers invalid.

### Root Cause

The Gemini Live API does **not allow client input** (audio or text) while the model is:
1. Processing a **tool call** (function_call event has been emitted but function_response hasn't been sent back yet)
2. In a **"thought" state** (the model is internally reasoning before emitting a function_call)

If audio bytes arrive at the server during either of these states, the server immediately closes the WebSocket with code 1008.

### How We Discovered It

**Scenario:** User orders multiple items rapidly in one continuous sentence (e.g., "I'll have an iced latte, egg bites, and a cake pop").

**What happens internally:**
1. User speaks continuously — audio chunks stream to the server at ~50 chunks/second
2. Model begins "thinking" about the first tool call (enters `[thought]` state)
3. Audio chunks continue arriving during the thought state
4. Server rejects the audio → **1008 Policy Violation** → WebSocket closed

**Diagnostic evidence from GCP logs:**
```
DIAG Transient error; retrying in 0.5s (attempt 1): APIError(1008 None. Operation is not
implemented, or supported, or enabled.) | elapsed=26.2s events=63 last_event=[thought]
session=session_n81h1yn conn=ws_e551435f
```

The `last_event=[thought]` confirms the crash happens during the model's thinking phase, before a `function_call` event is ever emitted.

### Timing Diagram

```
Time ──────────────────────────────────────────────────────►

User audio:    ████████████████████████████████████████████
                                    ▲
Model state:   [listening]──────────[thought]──[function_call]──[processing]──[response]
                                    │
                                    ╰── Server rejects audio here → 1008
                                         (our tool gate can't activate
                                          because function_call hasn't
                                          arrived yet)
```

---

## 3. Error 1011 — Deadline Expired / Internal Error

### What It Is

```
google.genai.errors.APIError: 1011 None. Deadline expired before operation could complete.
websockets.exceptions.ConnectionClosedError: received 1011 (internal error)
  The service is currently unavailable.
```

WebSocket close code **1011** means the server encountered an internal error. In the Gemini Live API context, this has multiple causes.

### Root Causes

| Cause | When It Happens | Frequency |
|-------|----------------|-----------|
| **10-minute session limit** | Hard limit on BIDI streaming connections. Server sends `GoAway` at ~9 min, closes at 10 min. | Common for long orders |
| **Long model responses** | Model generates a response that exceeds the server-side deadline | Occasional |
| **Server-side transient failures** | Google infrastructure hiccups | Rare, unpredictable |
| **Resource exhaustion** | API quota limits exceeded | Rare |

### Key Limitation

The model we use (`gemini-2.5-flash-native-audio-preview-12-2025`) on the Gemini API **does not support session resumption**. This was confirmed by Google engineer @klateefa in [google/adk-python#4140](https://github.com/google/adk-python/issues/4140). Session resumption only works on Vertex AI models or certain `gemini-live-*` models.

This means when a 1011 occurs at the 10-minute mark, we cannot transparently resume — we must start a new Gemini session and re-inject context.

---

## 4. The Tool Gate — Preventing 1008 During Tool Calls

### What It Does

The **tool gate** is a mechanism that blocks the frontend from sending audio to the Gemini API while tool calls are being processed. This prevents the most common trigger of 1008 errors.

### How It Works

```
┌──────────┐                    ┌──────────────┐                  ┌─────────────┐
│ Frontend │ ── audio chunks ──►│   Backend    │ ── audio blob ──►│ Gemini API  │
│          │                    │              │                   │             │
│          │◄── gate:blocked ───│  Tool Gate   │◄── function_call─│             │
│          │    (stop sending)  │  pending=True│                   │             │
│          │                    │              │── tool response ─►│             │
│          │◄── gate:unblocked ─│  pending=Fals│◄── func_response─│             │
│          │    (resume sending)│              │                   │             │
└──────────┘                    └──────────────┘                  └─────────────┘
```

### Implementation

**Backend (`main.py`):**

```python
tool_gate: dict[str, object] = {"pending": False, "ids": set()}
```

When a `function_call` event arrives from Gemini:
1. Set `tool_gate["pending"] = True`
2. Track the function call ID in `tool_gate["ids"]`
3. Send `{"type": "realtime_input_gate", "blocked": true}` to the frontend

When a `function_response` event arrives:
1. Remove the function call ID from `tool_gate["ids"]`
2. If no more pending IDs, set `tool_gate["pending"] = False`
3. Send `{"type": "realtime_input_gate", "blocked": false}` to the frontend

**Backend — audio dropping while gated:**

```python
if bool(tool_gate["pending"]):
    dropped_audio_chunks += 1
    continue  # silently drop the audio chunk
```

**Frontend (`useBrewWebSocket.ts`):**

```typescript
if (msg.type === "realtime_input_gate") {
    realtimeInputBlockedRef.current = Boolean(msg.blocked);
}

// In sendAudio:
if (wsRef.current?.readyState === WebSocket.OPEN && !realtimeInputBlockedRef.current) {
    wsRef.current.send(chunk);
}
```

### What It Covers

- Audio chunks are blocked on both sides (frontend stops sending, backend drops any that slip through)
- `turn_complete` signals are also blocked during tool calls
- Tool call cancellations properly clear the gate
- Multiple concurrent tool calls are tracked individually by ID

### What It Does NOT Cover

The tool gate activates when a `function_call` event arrives. But the 1008 can happen **before** that event, during the `[thought]` state. See section 5.

---

## 5. The Thought-State Race Condition — Why 1008 Still Happens

### The Gap

There is a timing gap between when the model starts thinking about a tool call and when the `function_call` event is emitted to our code. During this gap:

- The model is in `[thought]` state internally
- The server considers audio input invalid
- Our tool gate has NOT been activated (no `function_call` event yet)
- Audio continues streaming → **1008**

### Why We Can't Fully Prevent It

We considered gating audio during `[thought]` events too ("thought gate"), but rejected it because:

1. **Thought events are frequent** — the model thinks before many actions, not just tool calls
2. **False positives** — blocking audio during all thoughts would drop legitimate user speech when the model is just thinking about what to say (not making a tool call)
3. **User experience** — pausing the mic during thoughts creates unnatural gaps where the user speaks but nothing happens

### Our Strategy: Accept and Recover

Since we can't prevent the 1008 during the thought-to-function_call gap, we **accept that it will happen** and focus on **fast, seamless recovery**. See section 6.

---

## 6. Reconnection & Context Recovery

### The Retry Loop

When a 1008 or 1011 occurs, the backend catches it as a transient exception and retries:

```python
MAX_TRANSIENT_LIVE_RETRIES = 8

def _is_transient_live_exception(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(h in text for h in (
        "1008", "1011", "service is currently unavailable",
        "deadline expired", "connection is closed", "connection closed"
    ))
```

**Retry behavior:**
- Up to **8 retries** with exponential backoff
- Backoff: 0.5s → 1s → 2s → 4s → 5s (capped)
- Each retry creates a **new** `LiveRequestQueue` and starts a fresh `run_live()` session

### The `_reset_live_stream` Function

On each retry, `_reset_live_stream()` performs:

1. **Close the old queue** — stops the previous Gemini session
2. **Create a new queue** — fresh `LiveRequestQueue` for the new session
3. **Clear the tool gate** — reset `pending=False`, clear tracked IDs
4. **Unblock the frontend** — send `realtime_input_gate: false` so audio resumes
5. **Inject order context** — send the current cart state as a text message to the new session (see below)

### Context Injection

The critical part of recovery is telling the new Gemini session about the existing order. Since the new session has no memory of the previous conversation, we inject a text message:

```python
order = get_order_state(user_id, session_id)
if order:
    items = order.snapshot()
    if items:
        item_lines = []
        for it in items:
            mods = [m.get("name", "") for m in it.get("modifiers", [])]
            mod_str = f" (with {', '.join(mods)})" if mods else ""
            item_lines.append(f"- {it.get('name')} {it.get('size', '')}{mod_str}")
        ctx = (
            "[SYSTEM OVERRIDE — DO NOT GREET] "
            "You are mid-conversation with a customer. "
            "You have ALREADY greeted them. Do NOT say 'Hi' or 'Welcome to Brew' again. "
            "Their current order so far:\n"
            + "\n".join(item_lines)
            + "\nSay something brief like 'Alright, what else can I add?' or "
            "'Sure thing, anything else?' and continue taking their order."
        )
    else:
        ctx = (
            "[SYSTEM OVERRIDE — DO NOT GREET] "
            "You are mid-conversation with a customer. "
            "You have ALREADY greeted them. Do NOT say 'Hi' or 'Welcome to Brew' again. "
            "The customer's cart is empty so far. "
            "Say something brief like 'What can I get for you?' and continue."
        )
    new_queue.send_content(types.Content(parts=[types.Part(text=ctx)]))
```

### Why "[SYSTEM OVERRIDE — DO NOT GREET]"

The system prompt (`system_prompt_09.md`) contains:

> `GREETING: Immediately greet: "Hi, welcome to Brew! What can I get started for you today?"`

When a new `run_live()` session starts, the model sees this instruction and immediately greets. On a reconnect, this is wrong — the customer has already been greeted and is mid-order.

The `[SYSTEM OVERRIDE — DO NOT GREET]` prefix in the context injection is a strong signal to the model that this is a continuation, not a fresh start. It explicitly tells the model:
- You have already greeted
- Here is the current order
- Continue from where you left off

### What the User Experiences

**Before our fix:** 1008 crash → reconnect → model says "Hi, welcome to Brew!" again → user confused, order lost from model's perspective.

**After our fix:** 1008 crash → reconnect in ~0.5s → model says "Alright, what else can I add?" → user may notice a brief pause but conversation continues naturally.

---

## 7. Order State Persistence Across Reconnects

### Why the Order Is Never Lost

The order state is stored **server-side** in `OrderState` objects, completely independent of the Gemini session:

```
OrderState (Python object in backend memory)
    ├── _items: [{name: "Iced Latte", size: "Grande", item_id: "item_1", modifiers: [...]}]
    ├── _history: [previous snapshots for undo]
    └── menu_context: "Drinks"
```

**Storage layers:**

| Layer | Scope | Survives |
|-------|-------|----------|
| `_session_states` dict | In-memory per process | WebSocket reconnects, Gemini session resets |
| Firestore `brew_carts` | Cloud-persistent | Process restarts, Cloud Run instance changes |

### Flow on Reconnect

```
1008 crash
    │
    ▼
_reset_live_stream()
    │
    ├── OrderState still in memory (untouched by Gemini crash)
    ├── order.snapshot() returns current cart items
    ├── Cart items injected as text to new Gemini session
    │
    ▼
New run_live() starts
    │
    ├── Model sees cart context in text message
    ├── Model continues taking order
    ├── New tool calls (add_item, etc.) modify the SAME OrderState object
    │
    ▼
Order is continuous — nothing lost
```

### Firestore Sync

Every mutation to `OrderState` (add, remove, modify) triggers an async Firestore write:

```python
async def _sync_to_firestore(self):
    db = _db()
    if db is None:
        return
    doc_ref = db.collection(_CART_COLLECTION).document(self._session_key)
    await doc_ref.set({"items": self._items, "updated_at": ...})
```

On a new WebSocket connection, if the in-memory cart is empty, it's restored from Firestore:

```python
if not existing._items:
    await restore_order_state(user_id, session_id)
```

---

## 8. Audio Replay — Attempted and Removed

### What We Tried

We implemented an **audio ring buffer** that stored the last N seconds of user audio. On reconnect, we replayed these audio chunks to the new Gemini session so the model could "hear" what the user was saying when the crash happened.

```python
# REMOVED — kept here for documentation
AUDIO_RING_SECONDS = 5  # later reduced to 2
AUDIO_CHUNKS_PER_SECOND = 50
audio_ring: collections.deque[bytes] = collections.deque(
    maxlen=AUDIO_RING_SECONDS * AUDIO_CHUNKS_PER_SECOND
)

# On every incoming audio chunk:
audio_ring.append(raw["bytes"])

# On reconnect:
for chunk in list(audio_ring):
    new_queue.send_realtime(types.Blob(mime_type="audio/pcm;rate=16000", data=chunk))
```

### Why We Removed It

| Problem | Impact |
|---------|--------|
| **Latency** | Replaying 250 chunks (5s) or 100 chunks (2s) added noticeable delay before the model could respond. The model had to process all replayed audio before generating a response. |
| **Model confusion** | The model received decontextualized audio fragments with no prior conversation context. It couldn't make sense of partial speech. |
| **Re-greeting** | Despite the audio replay, the model still followed the system prompt's greeting instruction, ignoring both the replayed audio and the context injection text. |
| **No benefit** | The order state is already preserved server-side. The only thing "lost" is the last 1-2 seconds of speech, which the user naturally repeats when the model asks "what else?" |

### Current Approach

No audio replay. Only text-based context injection of the current cart state. This is faster, more reliable, and the model responds correctly.

---

## 9. Diagnostic Logging System

### What We Added

To diagnose the errors, we added comprehensive logging that tracks:

**Per-session timing:**
```python
live_session_start: float = time.monotonic()
total_events_received: int = 0
last_event_summary: str = "(none)"
```

**Event categorization:**
```python
evt_parts_summary = ",".join(
    "audio" if getattr(p, "inline_data", None)
    else "fc" if getattr(p, "function_call", None)
    else "fr" if getattr(p, "function_response", None)
    else "thought" if getattr(p, "thought", False)
    else "text"
    for p in event.content.parts
)
```

**DIAG log format:**
```
DIAG Transient error; retrying in 0.5s (attempt 1): APIError(1008 None. ...)
  | elapsed=26.2s events=63 last_event=[thought] session=session_xxx conn=ws_xxx
```

This tells us:
- **elapsed**: How long the session ran before crashing (helps distinguish 10-min limit from race condition)
- **events**: Total events received (indicates how active the session was)
- **last_event**: What the model was doing when it crashed (`[thought]` = race condition, `[audio]` = normal, `[fc]` = during tool call)
- **session/conn**: For correlating across log entries

### Turn Trace Log

Every model turn is logged to `debug_logs/turn_trace.log` as JSON:

```json
{
  "connection_id": "ws_fa56c343",
  "session_id": "session_19i26dq",
  "turn_id": 2,
  "started_at_ms": 1773247222412,
  "tool_calls": [
    {"id": "function-call-978...", "name": "add_item", "args": "{'name': 'Iced Latte', 'size': 'Grande'}"}
  ],
  "tool_responses": [
    {"id": "function-call-978...", "name": "add_item", "result": "{'result': '{\"status\": \"success\"...'}"}
  ],
  "assistant_audio_events": 44,
  "interrupted": false,
  "reason": "turn_complete",
  "ended_at_ms": 1773247248090
}
```

This allows post-mortem analysis of every interaction: what tools were called, how long each turn took, and whether the model was interrupted.

---

## 10. Approaches Considered

### Approach 1: Thought Gate (Rejected)

**Idea:** Block audio during `[thought]` events too, not just during `function_call` events.

**Why rejected:**
- Thought events happen frequently, not just before tool calls
- Would drop legitimate user speech during normal model thinking
- Creates unnatural pauses in conversation
- User was uncomfortable with this approach

### Approach 2: Proactive Reconnect Timer (Not Yet Implemented)

**Idea:** Reset the live stream every ~8 minutes to avoid the 10-minute hard limit.

**Status:** Documented as a future improvement. Not yet needed since most orders complete within 10 minutes.

### Approach 3: Accept 1008, Smart Retry (Implemented — Current)

**Idea:** Let the 1008 happen, but recover gracefully by:
1. Reconnecting quickly (0.5s backoff)
2. Injecting the current order state as text
3. Instructing the model to continue (not re-greet)

**Why chosen:** Minimal latency impact, preserves natural conversation flow, doesn't drop user audio during normal operation.

### Approach 3a: Smart Retry + Audio Replay (Tried, Then Removed)

**Idea:** Same as Approach 3, but also replay the last few seconds of audio.

**Why removed:** Added latency, confused the model, didn't improve recovery quality. See section 8.

### Approach 4: Switch to Vertex AI (Future Option)

**Idea:** Use Vertex AI models that support session resumption natively.

**Trade-off:** The 12-2025 model has better audio quality and instruction following than alternatives. Vertex AI requires different authentication setup.

---

## 11. Current Architecture (Final)

### Error Handling Flow

```
                          ┌─────────────────────┐
                          │  Normal Operation    │
                          │  Audio streaming     │
                          │  Tool calls working  │
                          └──────────┬──────────┘
                                     │
                              1008 or 1011
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │ _is_transient?       │
                          │ Yes → retry          │
                          │ No  → raise          │
                          └──────────┬──────────┘
                                     │ Yes
                                     ▼
                          ┌─────────────────────┐
                          │ _reset_live_stream() │
                          │                     │
                          │ 1. Close old queue   │
                          │ 2. Create new queue  │
                          │ 3. Clear tool gate   │
                          │ 4. Unblock frontend  │
                          │ 5. Read OrderState   │
                          │ 6. Inject cart text  │
                          │    with NO-GREET     │
                          └──────────┬──────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │ Backoff sleep        │
                          │ 0.5s → 1s → 2s → 5s │
                          └──────────┬──────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │ New run_live()       │
                          │ Model sees context   │
                          │ Continues order      │
                          └─────────────────────┘
```

### What Persists Across Reconnects

| Data | Persists? | How |
|------|-----------|-----|
| Order items (cart) | Yes | `OrderState` in memory + Firestore |
| Order modifiers | Yes | Part of `OrderState._items` |
| Menu context (active tab) | Yes | `OrderState.menu_context` |
| Conversation history | No | Gemini session is new; only cart summary injected |
| Model's "memory" of discussion | No | Lost; model only knows current cart state |
| Frontend WebSocket | Yes | Same connection; only backend↔Gemini link resets |
| Frontend audio pipeline | Yes | Uninterrupted; mic stays active |

### What the Frontend Sees

The frontend WebSocket connection to the backend is **not affected** by Gemini reconnects. From the frontend's perspective:

1. Audio stops being returned for ~0.5-2 seconds (during backoff + reconnect)
2. A `realtime_input_gate: false` message arrives (unblocking audio if it was gated)
3. Model audio resumes with a continuation message

The frontend does receive `{"type": "error", "code": "1008", ...}` but currently only displays it briefly — the retry happens server-side automatically.

---

## 12. Known Limitations

### 1. The Thought-State Gap Is Unavoidable

We cannot prevent 1008 during the `[thought]` → `[function_call]` gap without blocking audio during all thought events, which degrades UX. This is a Gemini Live API limitation.

### 2. No Session Resumption on This Model

`gemini-2.5-flash-native-audio-preview-12-2025` on Gemini API does not support `SessionResumptionConfig`. Each reconnect starts a fresh Gemini session with no conversation history.

### 3. Conversation Context Is Limited to Cart State

After reconnect, the model only knows the current cart contents. It does not know:
- What the customer previously asked about (e.g., "what desserts do you have?")
- Any preferences mentioned (e.g., "I'm vegan")
- The tone/flow of the conversation

### 4. 10-Minute Hard Limit

Long ordering sessions will hit the 10-minute wall. The retry mechanism handles this, but the model loses all conversation context each time. For very long sessions, this could happen multiple times.

### 5. No Frontend Auto-Reconnect

If the backend WebSocket itself drops (not just the Gemini stream), the frontend does not auto-reconnect. The user must click "Drive Up" again.

---

## 13. Timeline of Changes

| Date | Change | Reason |
|------|--------|--------|
| Pre-2026-03-11 | Tool gate implemented | Prevent 1008 during tool calls |
| 2026-03-11 | Added diagnostic logging (DIAG prefix, elapsed_s, last_event) | Determine root cause of persistent 1008/1011 |
| 2026-03-11 | Deployed diagnostics to GCP | Capture production error patterns |
| 2026-03-11 | Confirmed 1008 at 26.2s with `last_event=[thought]` | Identified thought-state race condition |
| 2026-03-11 | Confirmed 1011 at ~10min | Confirmed session limit as separate issue |
| 2026-03-11 | Implemented audio ring buffer (5s) + context injection | Approach 3a: smart retry with audio replay |
| 2026-03-11 | Reduced audio ring buffer to 2s | Reduce replay latency |
| 2026-03-11 | Removed audio replay entirely | Caused latency + model confusion + re-greeting |
| 2026-03-11 | Added `[SYSTEM OVERRIDE — DO NOT GREET]` to context injection | Prevent model from re-greeting after reconnect |
| 2026-03-11 | Cleaned up unused `collections` import and `audio_ring` code | Code hygiene |

---

## 14. References

| Source | URL | Key Finding |
|--------|-----|-------------|
| GitHub Issue #985 | [googleapis/python-genai#985](https://github.com/googleapis/python-genai/issues/985) | 1011 at 10-min mark is expected; use session resumption |
| GitHub Issue #812 | [googleapis/python-genai#812](https://github.com/googleapis/python-genai/issues/812) | Long responses trigger 1011 timeout |
| GitHub Issue #4140 | [google/adk-python#4140](https://github.com/google/adk-python/issues/4140) | 12-2025 model does NOT support session resumption on Gemini API |
| ADK Discussion #3360 | [google/adk-python#3360](https://github.com/google/adk-python/discussions/3360) | Resource exhaustion and model incompatibility cause 1011 |
| Google AI Forum | [discuss.ai.google.dev](https://discuss.ai.google.dev/t/gemini-live-api-issues-1008-1011-disconnects-per-session-cost-function-calling-api-logs/116509) | Comprehensive 1008/1011 analysis with workarounds |
| Session Management Docs | [ai.google.dev](https://ai.google.dev/gemini-api/docs/live-session) | Official session resumption and compression docs |
| Google Engineer (@klateefa) | [github comment](https://github.com/google/adk-python/issues/4140) | Confirmed 12-2025 model limitation |

### WebSocket Close Codes Quick Reference

| Code | Name | Meaning in Gemini Context |
|------|------|--------------------------|
| 1000 | Normal Closure | Clean shutdown |
| 1006 | Abnormal Closure | Network drop, no close frame |
| 1007 | Invalid Payload | Bad config (e.g., transcription on unsupported model) |
| 1008 | Policy Violation | Audio sent during tool call or thought state |
| 1011 | Internal Error | Session timeout (10 min) or server failure |
