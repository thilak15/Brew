# Gemini Live / Native Audio Repetition: Research & Fixes

This document summarizes **repetition/duplicate response issues** reported by others with the Gemini Live API and native-audio models, how they solved them, and how our code compares. Use it to debug ongoing repetition in the Brew voice agent.

---

## Implementation status (Brew codebase)

| Recommendation | Status | Where |
|----------------|--------|--------|
| No injection on stream_end | Done | `main.py`: inject only when `"stream_end" not in reason` |
| Proactive 8-min reconnect disabled by default | Done | `main.py`: `PROACTIVE_RECONNECT_S=0` |
| Strong “no audio” wording when we do inject | Done | `main.py`: `[CONTEXT-ONLY — DO NOT REPLY WITH ANY AUDIO. REMAIN SILENT.]` |
| frequency_penalty in GenerateContentConfig | Done | `agent.py`: `frequency_penalty=0.5` |
| Prompt: one confirmation, no repeat | Done | `system_prompt_10.md` (loaded via `menu.py`) |
| Upgrade ADK (≥1.17 for #2588 fix) | Done | `requirements.txt`: `google-adk>=1.17.0` |
| Log resets and injections | Done | `main.py`: `Live stream reset: %s`, `Injected order context after reset (%d items)` |
| Model: use latest native audio (e.g. 12-25) | Done | `.env.example`: `BREW_AGENT_MODEL=gemini-2.5-flash-native-audio-preview-12-2025` |
| Optional: client-side audio dedup | Not done | Optional workaround; would be in frontend (e.g. `audioPipeline.ts`) |

**Not code (debugging / product):** “Confirm repetition type” (same phrase twice vs two replies) and “try different model” are things you do when testing; logging is already in place to support that.

---

## 1. What Others Report

### 1.1 Duplicate or repeated **full responses**

| Source | Symptom | Cause / Fix |
|--------|---------|-------------|
| **livekit/agents #2884** | Back-to-back duplicate responses when sending **text** messages; more likely **after function calls**. Voice input often OK. | **Workaround:** Downgrade `livekit-plugins-google` to **1.0.23** (issue gone for both 2.0 and 2.5). **Fix in stack:** Resolved in LiveKit 1.2.1 for some. |
| **google/adk-python #3395** | Agent responds **N+1 times** after tool calls when using **multi-agent** (parent → sub-agent); also **unprompted response on session resumption** (history truncated to last agent transfer, last role = user, so model “replies” again). | **Root cause (multi-agent):** Parent and child both processed the same function response (parent connection not closed before child). **Fix:** ADK PR **#2588** – close parent’s live connection before starting child’s. **Session resumption:** Model/server issue; full history not sent on resume. |
| **Google AI forum** | Gemini Live “repeats responses and ignores follow-up queries” when certain new features are enabled. | Product/API behavior; no code fix given. |

### 1.2 Last **audio chunks** repeated (tail repetition)

| Source | Symptom | Cause / Fix |
|--------|---------|-------------|
| **google-gemini/live-api-web-console #48** | Short reply like “Hello, how can I help you today?” is followed by a **repeated tail**: “you today?”. More at **session start**; longer replies often fine. | Attributed to **server-side** (audio chunk handling). **Status:** Reporter said **fixed in the same experimental model** (Feb 2025). |
| **googleapis/js-genai #707** | **turnComplete** fires while content is still **incomplete** (response cut off). | **turn_complete** / turn-detection behavior; affects when the server considers a turn “done”. |

### 1.3 Repetitive **token sequences** (text generation)

| Source | Symptom | Cause / Fix |
|--------|---------|-------------|
| **google-gemini/cookbook #220, #368** | Model enters **repetitive loops** (same sentence repeated until token limit), e.g. long legal/technical text. | **Model behavior** (e.g. gemini-1.5-flash). **Workarounds suggested elsewhere:** `frequency_penalty`, lower temperature, avoid very long single-turn generation. |

---

## 2. Model & API Notes

- **Gemini 2.5** (e.g. native-audio): Duplicate responses and “double reaction” to text/tool turns are reported **more** than with 2.0.
- **Voice vs text:** Several issues appear mainly when **sending text** into the Live API; voice-only sometimes avoids them.
- **Tool/function calls:** Duplicate or N+1 responses are **more likely after tool/function calls** (LiveKit issue, ADK multi-agent issue).
- **Session resumption:** If history is sent with **last role = user**, the model will **respond again** without new user input (ADK #3395).

---

## 3. Our Setup vs Theirs

### 3.1 What we do (Brew backend)

- **Single agent** (no parent/sub-agent, no `transfer_to_agent`).
- **RunConfig:** `StreamingMode.BIDI`, `input_audio_transcription=None`, `output_audio_transcription=None`. **No** `session_resumption`, **no** `response_modalities` override.
- **Session:** We pass `user_id`, `session_id`, `live_request_queue`, `run_config` to `runner.run_live()`. Session service (Firestore or in-memory) stores state; we do **not** use ADK’s SessionResumption for reconnect.
- **Reconnect:** On **stream_end** or transient errors we replace the `LiveRequestQueue` and retry. We **do not** inject any context when the reason is **stream_end** (to avoid prompting the model again). We **only** inject order context when the reset is **proactive_timer** or **exception** (and proactive is disabled by default).
- **turn_complete:** We only **observe** `event.turn_complete` (logging, proactive reconnect when enabled). We do **not** send `turn_complete` from client to the Live API as part of our reconnect logic.

### 3.2 Differences that matter

| Aspect | Reference (e.g. ADK #3395) | Brew |
|--------|----------------------------|------|
| Multi-agent | Yes; duplicate response fixed by closing parent connection before child (PR #2588). | No; single agent. |
| Session resumption | Uses ADK `session_resumption`; history truncation caused “reply again” on resume. | We don’t use session resumption; we replace queue and optionally inject context (and skip injection on stream_end). |
| Post–tool-call behavior | Double processing when parent and child both handled same function response. | Single agent; no transfer. If repetition still happens after tools, could be server turn detection or stream_end triggering a new “turn.” |
| Injection after reconnect | Not used in the reported ADK examples. | We used to inject after every reset (including stream_end), which could prompt the model to speak again; we now **skip injection on stream_end**. |

---

## 4. Recommended Fixes and Checks

### 4.1 Already done in our code

- **No injection on stream_end** – Avoids prompting the model again when the stream “just ended” (often after a turn).
- **Proactive 8-min reconnect disabled by default** – Removes that source of resets; does not fix early (1–2 min) repetition.
- **Strong “no audio” wording when we do inject** – For proactive/exception resets only.
- **frequency_penalty (e.g. 0.5)** in agent `GenerateContentConfig` – Reduces in-response phrase repetition.
- **Prompt rules** – One confirmation per turn; do not repeat the same sentence twice.

### 4.2 What to do next

1. **Upgrade ADK**  
   Ensure **google-adk** is at a version that includes the fix for **double function response processing** (PR #2588, merged Nov 2025). We use a single agent, but the same ADK code path may affect event handling.  
   - In `backend/requirements.txt` set `google-adk>=1.17.0` (or latest), then `pip install -r backend/requirements.txt --upgrade`.

2. **Confirm whether repetition is “same phrase twice” vs “two separate replies”**  
   - **Same phrase twice in one response** → Model/sampling; keep/strengthen `frequency_penalty` and prompt (“one short confirmation only”).  
   - **Two separate replies (e.g. confirm, then “Anything else?” again)** → Likely an extra “turn” (e.g. stream_end → new queue → model thinks it should speak again). Our “no injection on stream_end” targets this; if it persists, log when stream_end happens (e.g. right after turn_complete) and consider not replacing the queue on stream_end when we just had a normal turn_complete (if the API allows).

3. **Log resets and injections**  
   We already log `Live stream reset: <reason>` and `Injected order context after reset (N items)`. Watch for:
   - Resets in the **first 1–2 minutes** (confirms stream_end or errors, not the 8-min timer).
   - Any injection when you hear repetition (we should see **no** injection when reason is `stream_end`).

4. **Try a different model or version**  
   Some issues were reported as **fixed in a newer experimental/model version** (e.g. live-api-web-console #48). If you’re on an older native-audio or live model, try the latest recommended model for your region.

5. **Optional: client-side dedup**  
   If the server sends the **same last audio chunks twice** (tail repetition), you can try deduplicating on the client (e.g. skip or shorten the last N ms of audio if it matches the previous chunk). This is a workaround, not a root-cause fix.

---

## 5. References

- [Duplicate response with Gemini Live API · livekit/agents #2884](https://github.com/livekit/agents/issues/2884) – Text/tool-related duplicates; downgrade 1.0.23 or 1.2.1 fix.
- [[Live] Multiple responses after agent transfer and repeat response on session resumption · google/adk-python #3395](https://github.com/google/adk-python/issues/3395) – Multi-agent + session resumption; fix in ADK PR #2588.
- [fix: double function response processing issue · google/adk-python #2588](https://github.com/google/adk-python/pull/2588) – Close parent connection before child in live multi-agent.
- [Last audio chunks are repeated twice · google-gemini/live-api-web-console #48](https://github.com/google-gemini/multimodal-live-api-web-console/issues/48) – Tail repetition; reported fixed in model (Feb 2025).
- [Gemini Live API responses cut off prematurely with turnComplete · googleapis/js-genai #707](https://github.com/googleapis/js-genai/issues/707) – turnComplete / turn detection.
- [Bug Report: repetitive sequences of tokens · google-gemini/cookbook #220](https://github.com/google-gemini/cookbook/issues/220) – Long-text repetition (model behavior; frequency_penalty/temperature as levers).

---

## 6. Short “How to fix” checklist

- [x] **No injection on stream_end** – Done in `main.py`; verify in logs that after stream_end we do **not** log “Injected order context”.
- [x] **Upgrade ADK** – Done: `google-adk>=1.17.0` in `requirements.txt`.
- [x] **Keep frequency_penalty** – Done: 0.5 in `agent.py` `GenerateContentConfig`.
- [x] **Log reset reasons** – Done: `main.py` logs `Live stream reset: <reason>`; use logs to see if repetition correlates with resets.
- [x] **Prompt** – Done: `system_prompt_10.md` has one confirmation per turn and “do not repeat the same sentence”.
- [x] **Model** – Done: `.env.example` uses `gemini-2.5-flash-native-audio-preview-12-2025` (Gemini API, not Vertex).
- [ ] **Optional: client-side audio dedup** – Not implemented; add in frontend if tail chunk repetition persists.
