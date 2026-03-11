# Brew — Full Codebase Review

**Date:** 2026-03-11
**Scope:** Every file in the repository, line by line
**Categories:** Critical, High, Medium, Low

---

## Executive Summary

| Severity | Count | Status |
|----------|-------|--------|
| **Critical** | 10 | Must fix before production / hackathon demo |
| **High** | 16 | Should fix soon |
| **Medium** | 22 | Improve when possible |
| **Low** | 14 | Nice to have |

The app works well functionally. The biggest gaps are **security** (no auth, open CORS, API key exposure), **reliability** (no tests, unpinned deps, no CI quality gates), and **code hygiene** (dead code, inconsistent patterns, memory leaks).

---

## CRITICAL Issues (10)

### C1. Invalid JSON in tool return values — `agent.py`
Some tool functions return double-quoted valid JSON, others return single-quoted Python dict strings. Single-quoted strings are **not valid JSON** and can confuse the model.

**Affected:** `add_modifier`, `remove_modifier`, `set_modifier`, `set_ice_level`, `undo_last_change`, `clear_order`
**Working by accident:** The model treats them as text, not parsed JSON. But it's fragile.
**Fix:** Standardize all returns to use `json.dumps()` or consistent double-quoted f-strings.

### C2. `add_item` doesn't handle `None` return from loop guard — `agent.py`
When `OrderState.add_item()` returns `None` (loop guard triggered), the tool function embeds literal `"None"` as the `item_id` in the success response. The model thinks the item was added.

**Fix:** Check for `None` and return an error response.

### C3. CORS wildcard with credentials — `main.py`
`ALLOWED_ORIGINS` defaults to `"*"` with `allow_credentials=True`. This is a security vulnerability — any website can make authenticated cross-origin requests.

**Fix:** Set explicit allowed origins in production. Remove `allow_credentials=True` if using `*`.

### C4. No WebSocket authentication — `main.py`
The `/ws/{user_id}/{session_id}` endpoint has zero auth. Anyone who guesses a URL can connect, impersonate users, or hijack sessions.

**Fix:** Add token-based auth (e.g., short-lived JWT passed as query param on WebSocket connect).

### C5. No rate limiting — `main.py`
No limit on WebSocket connections, message frequency, or audio blob size. A single client can open unlimited connections and burn through Gemini API quota.

**Fix:** Add per-IP connection limits and per-session message rate limits.

### C6. API key exposed as Cloud Run env var — `deploy.yml` / `deploy.sh`
`GOOGLE_API_KEY` is passed as a plain environment variable to Cloud Run. It's visible in the Cloud Run console, `gcloud run services describe`, and audit logs.

**Fix:** Use GCP Secret Manager with `--set-secrets` instead of `--set-env-vars`.

### C7. No CI quality gates — `deploy.yml`
The pipeline goes straight from checkout to build+deploy. No linting, type checking, or tests. A broken commit on `main` goes live immediately.

**Fix:** Add `npm run lint`, `npm run build` (type check), and `python3 -m py_compile` steps before deploy.

### C8. No input validation on WebSocket path parameters — `main.py`
`user_id` and `session_id` are taken directly from the URL with no validation. They're used as Firestore document IDs and in log file paths — potential injection vectors.

**Fix:** Validate format (alphanumeric + underscore, max length).

### C9. Backend runs as root in Docker — `backend/Dockerfile`
No `USER` directive. The application runs as root inside the container, increasing the blast radius of any container escape.

**Fix:** Add `RUN useradd -m appuser` and `USER appuser`.

### C10. `--allow-unauthenticated` on backend Cloud Run — `deploy.yml`
The backend is open to the entire internet with no authentication layer.

**Fix:** For hackathon demo this may be acceptable, but note it for production. Consider Cloud Run IAM or an API gateway.

---

## HIGH Issues (16)

### H1. Memory leak — `_session_states` grows unboundedly — `main.py` / `order_state.py`
`unregister_order_state()` is imported but never called. The `_session_states` dict grows for the lifetime of the process.

**Fix:** Call `unregister_order_state(user_id, session_id)` in the `finally` block of the WebSocket handler.

### H2. Race condition on Firestore sync — `order_state.py`
Multiple tool calls mutate `_items` and each fires off an async Firestore write. Writes can complete out of order, causing Firestore to have stale data.

**Fix:** Use a version counter or serialize writes through a queue.

### H3. Mic stream leak on double-tap — `page.tsx`
`startOrder` can be called multiple times. If double-tapped, two mic streams open but only the second `stop` function is stored — the first stream leaks permanently.

**Fix:** Guard with `if (stopMicRef.current) return;` at the top of `startOrder`.

### H4. Race condition on unmount — `page.tsx`
`startMicCapture` is async but the `.then()` has no guard. If the component unmounts before the promise resolves, `setMicActive(true)` fires on an unmounted component.

**Fix:** Track a mounted/cancelled flag and clean up the timeout.

### H5. Duplicated `getWsUrl` — `useBrewWebSocket.ts` vs `backendUrl.ts`
`useBrewWebSocket.ts` has its own `getWsUrl()` that's nearly identical to `backendUrl.ts` but **without** `trimTrailingSlash`. If `NEXT_PUBLIC_WS_URL` has a trailing slash, the WebSocket URL gets a double slash.

**Fix:** Delete the local copy and import from `@/lib/backendUrl`.

### H6. Module-level mutable audio state — `audioPipeline.ts`
`playbackContext`, `playbackQueue`, `isPlaying`, `activeNode` are module-level singletons. In Next.js with HMR, these survive module reloads, causing ghost AudioContexts.

**Fix:** Expose a `destroyPlayback()` function called on unmount.

### H7. `playbackContext` never closed — `audioPipeline.ts`
When the user ends the order, the mic is stopped but the playback `AudioContext` is never closed. Browsers limit to ~6 AudioContexts before refusing to create more.

**Fix:** Export and call a `closePlayback()` function in `endOrder`.

### H8. XSS-adjacent `innerHTML` in SmartMenu — `SmartMenu.tsx`
`onError` handler sets `innerHTML` directly, bypassing React's virtual DOM. While the content is hardcoded emoji, this pattern is dangerous and can cause React DOM desync.

**Fix:** Use React state to track broken images and conditionally render the emoji fallback.

### H9. `requirements.txt` uses unpinned versions
All deps use `>=` minimum bounds. A new release of any dependency could break the build at any time.

**Fix:** Pin exact versions or use `pip freeze > requirements.txt`.

### H10. Debug logging at DEBUG level in production — `main.py`
Root logger is set to `DEBUG`, producing enormous log volumes. May log sensitive data.

**Fix:** Make log level configurable via `LOG_LEVEL` env var, default to `INFO` in production.

### H11. No concurrency control in CI — `deploy.yml`
Two pushes to `main` in quick succession run two deploys in parallel, potentially racing.

**Fix:** Add `concurrency: { group: deploy, cancel-in-progress: true }`.

### H12. No health check after deploy — `deploy.yml`
After deploying backend, there's no step that verifies the service is responding before deploying the frontend.

**Fix:** Add a `curl` step that hits the `/health` endpoint.

### H13. GCP credentials mounted in docker-compose
`~/.config/gcloud` is mounted into the container. If compromised, all GCP resources are exposed.

**Fix:** Use a service account key file with minimal permissions, or use Workload Identity.

### H14. Test files are ad-hoc and broken — `frontend/test_browser*.js`
Three Playwright scripts with no assertions, no test framework, and `playwright` not in dependencies.

**Fix:** Move to `tests/`, add `playwright` as devDependency, add real assertions, or remove.

### H15. ESLint errors ignored during builds — `next.config.mjs`
`ignoreDuringBuilds: true` means lint errors never block deployment.

**Fix:** Remove this setting and fix any lint errors.

### H16. `remove_modifier` and `set_modifier` log raw `item_id` instead of `resolved` — `agent.py`
Log messages and return values reference the unresolved `item_id` instead of the `resolved` variable, creating misleading logs.

**Fix:** Use `resolved` consistently in logs and return values.

---

## MEDIUM Issues (22)

### M1. Menu loaded from disk on every tool call — `menu.py`
`_load_menu()` reads and parses `menu.json` from disk on every single tool invocation. Multiple times per user utterance.

**Fix:** Cache with `@functools.lru_cache` or load once at module level.

### M2. Redundant `get_order_state` calls — `main.py` line 141-144
`get_order_state` is called twice in succession for the same arguments.

**Fix:** Store the result in a variable.

### M3. Accessing private `_items` from outside the class — `main.py` line 143
Breaks encapsulation. `OrderState` should expose an `is_empty()` method.

### M4. `_push_history` called even when operation fails — `order_state.py`
`remove_item`, `remove_item_by_description`, and `remove_modifier` push history before checking if the item exists. Failed operations create useless undo snapshots.

**Fix:** Move `_push_history()` after the success check.

### M5. `_generate_id` uses `hasattr` for lazy init — `order_state.py`
Fragile pattern. Initialize `_next_id` in `__init__`.

### M6. Global `_firestore_client` with no thread safety — `order_state.py`
Multiple concurrent connections could initialize multiple Firestore clients.

### M7. No TTL or cleanup for `_session_states` — `order_state.py`
Even if `unregister_order_state` is called, there's no periodic cleanup of stale sessions.

### M8. `import time` and `from menu import` inside method bodies — `order_state.py`
Should be top-level imports.

### M9. Weak session ID randomness — `page.tsx`
`Math.random().toString(36).substring(2, 9)` produces only ~36 bits of entropy. Use `crypto.randomUUID()`.

### M10. `error` state never clears — `orderReducer.ts`
Once an `ERROR` action is dispatched, the error banner persists forever.

**Fix:** Clear `error` on `CONNECTION` status `"open"` or add a `CLEAR_ERROR` action.

### M11. No WebSocket reconnection logic — `useBrewWebSocket.ts`
If the WebSocket drops mid-conversation, the user must manually click "Drive Up" again.

### M12. `WS_URL` computed at module load time — `useBrewWebSocket.ts`
During SSR, `window` is undefined, so `WS_URL` is permanently `""`. Fragile if ever imported server-side.

### M13. Production URL fallback hardcodes port 8000 — `backendUrl.ts`
In a typical production deployment behind a reverse proxy, port 8000 isn't exposed.

### M14. Vegan drink list hardcoded in SmartMenu — `SmartMenu.tsx`
Will silently become wrong if the menu changes. Should come from backend.

### M15. No loading state for menu fetch — `SmartMenu.tsx`
User sees fallback menu then it suddenly swaps when fetch completes.

### M16. `normalizeMenu` returns entire fallback if any category is empty — `SmartMenu.tsx`
If backend returns 50 drinks but 0 desserts, the entire menu reverts to fallback.

### M17. Dark mode CSS variables defined but never used — `globals.css`
Dark mode variables exist but all components use hardcoded Tailwind colors.

### M18. React Strict Mode disabled — `next.config.mjs`
Hides double-render bugs. Should be documented why it's disabled.

### M19. No maximum order size rule in prompt — `system_prompt_09.md`
A confused model in a loop could add hundreds of items.

### M20. No rule for handling unrecognized items in prompt
The model has no guidance on what to say when a customer asks for something not on the menu.

### M21. Contradiction on warming behavior between prompts
`system_prompt.md` says ask about warming; `system_prompt_09.md` says don't. If wrong prompt is selected, behavior flips.

### M22. `.gitignore` missing GCP credential patterns
Not ignoring `credentials.json`, `service-account*.json`, `*.pem`, `*.key`.

---

## LOW Issues (14)

### L1. Dead code: `_new_id()` in `order_state.py` — does nothing (`pass`)
### L2. Dead code: `TOOL_MAP` in `agent.py` — defined but never used
### L3. Dead code: `get_item_base_price()` in `menu.py` — defined but never called
### L4. `remove_item_by_description` is redundant — just delegates to `remove_item`
### L5. `import logging` separated from other imports — `agent.py` line 41
### L6. `live_request_queue` variable shadowed immediately — `main.py` line 145
### L7. Silent exception swallowing in upstream_task — `main.py`
### L8. No `aria-live` regions for accessibility — `page.tsx`, `AudioVisualizer.tsx`
### L9. Array index used as React key for modifiers — `LiveReceipt.tsx`
### L10. Deeply nested ternaries in `AudioVisualizer.tsx`
### L11. `disconnect` returned from hook but never used — `useBrewWebSocket.ts`
### L12. ScriptProcessor fallback is deprecated — `audioPipeline.ts`
### L13. No `engines` field in `package.json`
### L14. Custom scrollbar styles are WebKit-only — `globals.css`

---

## What Should Be Removed

| Item | Reason |
|------|--------|
| `docs/ORDER_INCIDENT_FORENSIC_2026-03-10.md` | Debug artifact, not user-facing |
| `docs/LAST_LOG_FORENSIC_2026-03-10_session_cwvps4z.md` | Debug artifact with internal session IDs |
| `docs/REPEATED_CONFIRMATION_ROOT_CAUSE_2026-03-10.md` | Debug artifact, overlaps with others |
| `docs/WHY_DOUBLE_CONFIRMATION_PERSISTS_2026-03-10.md` | Debug artifact, overlaps with others |
| `docs/CODE_FIXES_ASSESSMENT_2026-03-10.md` | Debug artifact |
| `frontend/test_browser.js` | Ad-hoc test, no assertions, playwright not in deps |
| `frontend/test_browser3.js` | Same |
| `frontend/test_browser_long.js` | Same |
| `_new_id()` in `order_state.py` | Dead function that does nothing |
| `TOOL_MAP` in `agent.py` | Defined but never used |
| `get_item_base_price()` in `menu.py` | Defined but never called |
| `remove_item_by_description` tool registration | Redundant, `remove_item` handles both cases |
| Dark mode CSS variables in `globals.css` | Defined but overridden by Tailwind everywhere |

---

## Recommended Architecture Improvements

### 1. Add WebSocket Auth (Critical for production)
Pass a short-lived token as a query parameter on WebSocket connect. Validate it server-side before accepting the connection. For the hackathon, even a simple shared secret would be better than nothing.

### 2. Cache Menu Data (Easy win)
`menu.json` is read from disk on every tool call. Add `@functools.lru_cache` to `_load_menu()` — one line change, eliminates dozens of disk reads per conversation.

### 3. Consolidate Firestore Persistence
Two separate systems (`order_state.py` -> `brew_carts`, `firestore_session_service.py` -> `brew_sessions`) with two Firestore clients. Consider merging into one persistence layer.

### 4. Add Structured Logging
Replace ad-hoc `logger.info(f"...")` with structured JSON logging. Include `connection_id`, `session_id`, `user_id` in every log entry for correlation.

### 5. Add Basic Tests
Even 5-10 unit tests for `order_state.py` (add/remove/modify/undo) would catch regressions. The state management logic is pure Python with no external dependencies — easy to test.

### 6. Use Secret Manager for API Keys
Move `GOOGLE_API_KEY` from Cloud Run env vars to GCP Secret Manager. One-time setup, significantly better security posture.

### 7. Pin Dependencies
Run `pip freeze > requirements.txt` and commit exact versions. Prevents surprise breakage from upstream changes.

---

## Quick Wins (< 30 min each)

1. **Fix `add_item` None handling** — 5 lines, prevents ghost items
2. **Standardize JSON returns** — find/replace single quotes to double quotes
3. **Cache `_load_menu()`** — 1 line decorator
4. **Guard `startOrder` against double-tap** — 1 line check
5. **Add `unregister_order_state` to finally block** — 1 line
6. **Add `.gitignore` entries for GCP credentials** — 3 lines
7. **Set `ALLOWED_ORIGINS` in deploy configs** — set to your actual frontend domain
8. **Fix `resolved` vs `item_id` in log messages** — 4 line changes
