# Brew — Suggested Improvements (Code, Architecture, Prompts)

This document is based on a deep pass over the codebase, architecture, and prompts. Suggestions are grouped by area and ordered by impact vs. effort where useful.

---

## 1. Architecture

### 1.1 Single source of truth for menu

**Current:** Menu content lives in two places:

- **Backend:** `backend/menu.json` + `menu.py` (authoritative for prices, categories, modifiers). The system prompt is built from this and sent to the agent.
- **Frontend:** `SmartMenu.tsx` hardcodes `MENU_CATEGORIES` with the same item names.

**Risk:** Adding or renaming an item in `menu.json` without updating the frontend can leave the UI out of sync (wrong tab, missing item, or duplicate names).

**Suggestion:**

- **Option A (quick):** Add a small backend endpoint, e.g. `GET /menu`, that returns the same structure used for the prompt (or a subset: categories + item names + base prices). Frontend fetches once on load and drives `SmartMenu` (and any other menu UI) from that. Keep `menu.json` as the only source of truth.
- **Option B (longer-term):** If you introduce a CMS or admin flow for the menu, keep `menu.json` (or a DB) as the single source and have both agent prompt builder and frontend consume it via API or build-time generation.

### 1.2 Session vs. cart state

**Current:** Two separate persistence layers:

- **ADK SessionService** (InMemory or Firestore): Used by `Runner` for conversation/session state (e.g. event history). Stored in `brew_sessions`.
- **Order state (cart):** In-memory `OrderState` keyed by `(user_id, session_id)`, with optional Firestore sync in `brew_carts` for cross-instance recovery.

**Observation:** This is a reasonable split (conversation vs. domain state). The only coupling is that the same `user_id`/`session_id` is used for both. Document this clearly so future changes (e.g. “restore last order”) don’t conflate the two.

**Suggestion:** In `README` or `docs/architecture.md`, add a short “State and persistence” section: what lives in ADK sessions, what lives in order state, and when Firestore is used for each (e.g. “Cart is in `brew_carts`; ADK session state is in `brew_sessions`”).

### 1.3 Cloud Run and WebSocket lifecycle

**Current:** Backend runs on Cloud Run with `--timeout=300` and `--session-affinity`. WebSocket connections can outlive request timeouts if the platform supports long-lived connections.

**Suggestions:**

- Confirm Cloud Run timeout and any proxy timeouts allow your target session length (e.g. 10+ minutes). If you hit 1011 or connection drops at a fixed duration, consider documenting “max session length” and/or enabling **session resumption** in `RunConfig` so that when the Live API reconnects, the same conversation can continue (see also `docs/apierror-1008-troubleshooting.md`).
- If you add more health checks, consider a **liveness** endpoint that only checks process health, and keep `/health` as the main readiness check (e.g. for load balancers).

---

## 2. Backend code

### 2.1 Logging and config duplication

**Current:** In `main.py`, `LOG_DIR` and `LOG_FILE` are set twice (lines 43–45 and 47–50). Same block runs twice.

**Suggestion:** Keep a single definition of `LOG_DIR` / `LOG_FILE` and use it for both the `Path` setup and the `FileHandler`.

### 2.2 GCP project and Firestore

**Current:** `order_state.py` and `firestore_session_service.py` use `os.getenv("GCP_PROJECT_ID", "brew-488719")`. The default is a concrete project ID that may not be yours.

**Suggestion:**

- Prefer no default, or a placeholder like `""`, so misconfiguration fails fast: e.g. `os.getenv("GCP_PROJECT_ID")` and log a clear error if missing when Firestore is used.
- Document in `README` and `.env.example`: “For Firestore (cart + optional ADK session persistence), set `GCP_PROJECT_ID` to your project.”

### 2.3 RunConfig: session resumption and context compression

**Current:** `RunConfig` sets `streaming_mode=StreamingMode.BIDI` and disables input/output transcription. It does not set session resumption or context-window compression.

**Suggestion (from ADK docs and `apierror-1008-troubleshooting.md`):**

- For production, enable **session resumption** so that when the Live API closes the connection (e.g. ~10 min or 1011), the client can reconnect and continue the same session:
  - `session_resumption=types.SessionResumptionConfig()`
- If you expect long conversations (e.g. many items, long back-and-forth), consider **context_window_compression** so the session doesn’t hit token limits and get cut off. Tune `trigger_tokens` / `target_tokens` to your model (e.g. 128k for native-audio).

### 2.4 Tool return format (agent.py)

**Current:** Tools return Python-dict-style strings with single quotes, e.g. `"{'status': 'success', 'action': 'added_item', ...}"`. The model reads these as plain text; there is no frontend parsing of tool results.

**Suggestion:** Functionally this is fine. If you later add logging/analytics or server-side parsing of tool outcomes, consider returning **valid JSON** (e.g. `json.dumps({"status": "success", "action": "added_item", ...})`) so you can parse it reliably. Optional: add a one-line comment in `agent.py` that tool returns are for the LLM only and are intentionally human-readable.

### 2.5 Restore logic when cart is empty

**Current:** In `websocket_endpoint`, you only call `restore_order_state` when `existing._items` is empty. So you restore from Firestore only when the in-memory cart is empty but the session already exists.

**Suggestion:** Confirm intended behavior: “On every new WebSocket connection for a given `(user_id, session_id)`, if we have no in-memory cart (or cart empty), try Firestore restore.” If the first connection after a restart always has an empty cart, the current check is correct. Add a one-line comment above the block so future readers don’t assume “restore only on reconnect”; clarify that it also covers “first request after process restart.”

---

## 3. Prompts (system_prompt.md + menu.py)

### 3.1 Structure and clarity

**Current:** `system_prompt.md` is a single block: identity, language rules, anti-hallucination, tool rule, greeting, ordering rules, menu switching, style, then `{menu_text}`.

**Suggestions:**

- Add a short **role line** at the very top that can be used in logs or A/B tests, e.g. “You are Brew, a friendly drive-thru barista. Respond only with spoken audio.” (You already have this; keeping it as the first line is good.)
- Keep **CRITICAL / IMPORTANT** for safety and tool-use rules. Consider a single “ORDERING RULES” section with sub-bullets so the model consistently finds “how to add items,” “how to handle modifiers,” “when to call get_order_summary,” etc.
- Explicitly state that **item names and modifier values must match the injected menu exactly** (you imply this with “use these exact names”); one line like “Use only item and modifier names from the MENU section below; do not invent names” can reduce drift.

### 3.2 Language mirroring and noise

**Current:** You have strong rules: respond in the same language as the customer; do not switch on background noise or short mumbling; only switch on clear, deliberate full sentences; default to English when unsure.

**Suggestion:** This is already strong. If you see mis-switches in production, consider adding one example in the prompt, e.g. “Example: If the customer says only ‘gracias’ after you list the total, you may continue in English unless they then speak a full sentence in Spanish.”

### 3.3 Hot/iced and size mapping

**Current:** Prompt says: for generic drinks (e.g. Latte), ask hot/iced before `add_item`; map small→Tall, medium→Grande, large→Venti.

**Suggestion:** Make size mapping explicit in the injected menu or in one line of the prompt: “Size mapping: small = Tall, medium = Grande, large = Venti. For drinks, always pass one of: Tall, Grande, Venti.” This reinforces the tool contract (`add_item(..., size=...)`) and avoids the model inventing “Small” or “Medium.”

### 3.4 End of order and get_order_summary

**Current:** “When done, call `get_order_summary`, read back total, say ‘You can pull up to the window!’ (in the customer’s language).”

**Suggestion:** Add that the agent should **confirm** the customer is done (e.g. “Anything else?” or “Is that everything?”) before treating the order as final and calling `get_order_summary`. That reduces accidental “pull up” when the customer was mid-sentence.

### 3.5 Menu injection (menu.py)

**Current:** `get_system_prompt()` loads `menu.json`, builds `menu_lines` (drinks, breakfast, desserts, modifiers), and injects `menu_text` into the template. Sizes and base prices are included.

**Suggestion:** No change required for correctness. If the full prompt ever approaches model context limits, you could optionally trim the menu to “item name + base price” and list modifier types and option names in a more compact format (e.g. one line per modifier type). For current menu size, this is not necessary.

---

## 4. Frontend

### 4.1 Menu data source (SmartMenu)

**Current:** `MENU_CATEGORIES` in `SmartMenu.tsx` is a hardcoded list of item names per category.

**Suggestion:** Drive this from an API that reads from `menu.json` (see “Single source of truth” above). That way new drinks, breakfast items, or desserts only need to be added in one place.

### 4.2 Realtime input gate (1008 workaround) — UX

**Current:** When the backend sends `realtime_input_gate: { blocked: true }`, the frontend stops sending audio and `turn_complete`. The user may keep talking without realizing the mic is effectively “paused” during tool execution.

**Suggestion:** Optional UX improvement: when `realtimeInputBlockedRef.current` becomes true, show a short, non-intrusive hint (e.g. “Adding to order…” or a small spinner) so the user understands why the agent isn’t responding yet. You can clear it when `blocked` goes false. This is optional and can be subtle to avoid distraction.

### 4.3 Error display and recovery

**Current:** `state.error` is shown in the header. On WebSocket error or 1008/1011, the user sees the message but may not know whether to “Drive Up” again or refresh.

**Suggestion:** For known error codes (e.g. 1008, 1011), show a short, friendly message and a single “Try again” or “Start over” action that clears the error and optionally starts a new session (new session_id and “Drive Up”). This improves recovery without requiring a full page reload.

### 4.4 Accessibility (a11y)

**Current:** Buttons and layout are clear; transcript is shown in a footer.

**Suggestions:**

- Ensure “Drive Up,” “Tap to Order,” and “Pull Forward” buttons have clear `aria-label`s if the visible text isn’t sufficient (e.g. for “Pull Forward”).
- If the transcript is important for accessibility, consider `aria-live="polite"` on the transcript container so screen readers announce new text.
- If you add the “Adding to order…” state (above), make it announced to screen readers (e.g. `aria-live="polite"` and a short status message).

### 4.5 WELCOME_TRIGGER and startOrder

**Current:** On first “open” connection, `useEffect` calls `startOrder()`, which sends `WELCOME_TRIGGER` after 500 ms and starts mic capture. `startOrder` depends on `sendAudio`, `sendText`; it does not list `sendTurnComplete` in the dependency array but uses it inside the callback passed to `startMicCapture`.

**Suggestion:** Include `sendTurnComplete` in the dependency array of `startOrder` (and ensure `startOrder` is stable or the effect that calls it is correct) so that if the WebSocket hook ever recreated `sendTurnComplete`, the latest reference is used. This is a minor correctness improvement.

---

## 5. Deployment and operations

### 5.1 Environment variables

**Current:** Backend uses `GOOGLE_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`, optional `BREW_AGENT_MODEL`, optional `ALLOWED_ORIGINS`. Firestore uses `GCP_PROJECT_ID` (with a default in code). CI passes `GOOGLE_API_KEY` and `GOOGLE_GENAI_USE_VERTEXAI=FALSE`.

**Suggestions:**

- In `.env.example`, list **all** optional vars with short comments: `GCP_PROJECT_ID` (for Firestore), `BREW_AGENT_MODEL`, `ALLOWED_ORIGINS`, and, if you add them, `ADK_SESSION_RESUMPTION`, etc.
- In README, add a one-line note: “For Cloud Run, ensure `GCP_PROJECT_ID` is set if you use Firestore.”

### 5.2 Cloud Run deploy flags

**Current:** Backend is deployed with `--memory=512Mi`, `--timeout=300`, `--session-affinity`, `--allow-unauthenticated`. No `GCP_PROJECT_ID` or `BREW_AGENT_MODEL` in the workflow.

**Suggestion:** If you want to use Firestore or a different model in production, add those env vars to the Cloud Run deploy step (e.g. from GitHub secrets or workflow env), and document them in the README.

### 5.3 Observability

**Current:** Logging goes to stdout and `/app/debug_logs/backend.log`. No metrics or tracing.

**Suggestions (optional, as you scale):**

- Emit a simple metric (e.g. “session started,” “order completed”) to Cloud Monitoring or a logging-based metric so you can see usage and error rates.
- Add a **request or session ID** to log lines in the WebSocket handler (e.g. `session_id` or a short correlation id) so you can trace one session across logs.
- If you use Firestore, consider logging (at INFO) “cart restored” and “cart persisted” with session id and item count to verify restore behavior in production.

---

## 6. Security and performance

### 6.1 CORS and ALLOWED_ORIGINS

**Current:** `ALLOWED_ORIGINS` defaults to `"*"` when unset. That’s convenient for development but permissive in production.

**Suggestion:** In production, set `ALLOWED_ORIGINS` to your frontend origin(s) (e.g. `https://your-frontend.run.app`). Document in README.

### 6.2 WebSocket auth

**Current:** WebSocket path includes `user_id` and `session_id`; there is no server-side authentication. Anyone who can reach the backend can open a connection with any ids.

**Suggestion:** For a public demo or hackathon this may be acceptable. For production with real users, add authentication (e.g. validate a token in the WebSocket handshake or in the first message) and tie `user_id` to the authenticated identity. Optionally rate-limit by IP or user to avoid abuse.

### 6.3 Audio and tool-gate performance

**Current:** During tool execution, audio chunks are dropped in the backend and the frontend stops sending. No buffering or replay.

**Suggestion:** Current behavior is correct to avoid 1008. If you ever need to “replay” the last N seconds of audio after the gate opens, you could buffer on the frontend and send after `blocked: false`; that’s a larger change and only needed if the model or product requires it.

---

## 7. Testing

**Current:** No automated tests in the repo; only a few manual test scripts under `frontend/`.

**Suggestions:**

- **Backend:** Add a minimal test (pytest) that builds the system prompt from `menu.json` and checks that it contains expected item names and “add_item” / “get_order_summary.” That guards against menu or prompt refactors breaking the agent.
- **Backend:** Unit tests for `OrderState`: add_item, add_modifier, undo, snapshot, and (if possible) Firestore sync with a mock or emulator.
- **Frontend:** Smoke test that the app loads, “Drive Up” connects, and (if you have a test backend) that order_state updates when the backend sends `order_state` messages.
- **E2E (optional):** One Playwright (or similar) flow: open app → Drive Up → speak a simple order (or send a text message) → assert cart or transcript change. This can run in CI against a staging backend.

---

## 8. Documentation

**Current:** README covers setup, env vars, and deployment. `docs/apierror-1008-troubleshooting.md` covers 1008 and workarounds. There is an architecture diagram.

**Suggestions:**

- Add **docs/IMPROVEMENTS.md** (this file) to the README under “Project structure” or “Docs” so new contributors see it.
- In README, add a “State and persistence” subsection (see Architecture above).
- If you add session resumption or context compression, document the relevant env vars and behavior in README and, briefly, in the 1008 doc.

---

## 9. Prioritized summary

| Priority | Area | Suggestion | Effort |
|----------|------|------------|--------|
| High | Prompts | Add “confirm customer is done” before get_order_summary / “pull up”; clarify size mapping (Tall/Grande/Venti). | Low |
| High | Config | Remove or replace hardcoded `brew-488719`; require `GCP_PROJECT_ID` when Firestore is used. | Low |
| High | RunConfig | Enable session resumption for production; consider context_window_compression for long sessions. | Low |
| Medium | Menu | Single source of truth: expose GET /menu from backend; frontend SmartMenu consumes it. | Medium |
| Medium | Frontend | Better error recovery UX for 1008/1011 (message + “Try again” / new session). | Low |
| Medium | Backend | Deduplicate LOG_DIR/LOG_FILE in main.py; add session_id (or correlation id) to key log lines. | Low |
| Medium | Docs | Document state (ADK session vs. cart) and Firestore collections in README or architecture. | Low |
| Lower | Tool returns | Optionally return JSON from tools for future parsing/analytics. | Low |
| Lower | Frontend | Optional “Adding to order…” when realtime gate is active; a11y (aria-live, aria-label). | Low |
| Lower | Tests | Pytest for prompt build + OrderState; optional E2E smoke. | Medium |
| Lower | Security | Restrict ALLOWED_ORIGINS in production; add WebSocket auth for production. | Medium |

---

*Document generated from a full pass over the Brew codebase (backend, frontend, prompts, deployment). Apply changes incrementally and adjust priorities to match your roadmap.*
