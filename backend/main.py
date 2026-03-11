"""
Brew backend: FastAPI WebSocket server with ADK run_live() for real-time voice ordering.
"""
import asyncio
import warnings
from dotenv import load_dotenv
load_dotenv()

# ADK internally defaults response_modalities to ["AUDIO"] as a plain string,
# which triggers a harmless Pydantic serialization warning. Suppress it.
warnings.filterwarnings(
    "ignore",
    message=".*PydanticSerializationUnexpectedValue.*response_modalities.*",
    category=UserWarning,
)

import json
import logging
import os
import time
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import root_agent, set_current_session
from menu import get_menu_dict
from order_state import (
    get_order_state,
    register_order_state,
    restore_order_state,
    unregister_order_state,
)
try:
    from firestore_session_service import FirestoreSessionService
    _USE_FIRESTORE = True
except ImportError:
    _USE_FIRESTORE = False

from pathlib import Path

# Use /app/debug_logs in Docker; backend/debug_logs when running locally (e.g. uvicorn from repo root or backend/)
def _log_dir() -> Path:
    if Path("/app/debug_logs").exists():
        return Path("/app/debug_logs")
    try:
        Path("/app/debug_logs").mkdir(parents=True, exist_ok=True)
        return Path("/app/debug_logs")
    except OSError:
        pass
    local = Path(__file__).resolve().parent / "debug_logs"
    local.mkdir(parents=True, exist_ok=True)
    return local

LOG_DIR = _log_dir()
LOG_FILE = LOG_DIR / "backend.log"
TURN_TRACE_FILE = LOG_DIR / "turn_trace.log"

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(logging.StreamHandler())
root_logger.addHandler(file_handler)

# Specific loggers for visibility
for logger_name in ["google.adk", "google.genai", "uvicorn", "uvicorn.access"]:
    l = logging.getLogger(logger_name)
    l.setLevel(logging.DEBUG)
    l.addHandler(file_handler)

turn_trace_logger = logging.getLogger("turn_trace")
turn_trace_logger.setLevel(logging.INFO)
turn_trace_logger.propagate = False
if not any(
    isinstance(h, logging.FileHandler) and Path(getattr(h, "baseFilename", "")) == TURN_TRACE_FILE
    for h in turn_trace_logger.handlers
):
    _tth = logging.FileHandler(TURN_TRACE_FILE)
    _tth.setFormatter(logging.Formatter("%(message)s"))
    turn_trace_logger.addHandler(_tth)

logger = logging.getLogger(__name__)

MAX_TRANSIENT_LIVE_RETRIES = 8
PROACTIVE_RECONNECT_S = 8 * 60  # reconnect before the 10-min hard limit


def _is_transient_live_exception(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(h in text for h in ("1007", "1008", "1011", "service is currently unavailable", "deadline expired", "invalid argument", "connection is closed", "connection closed"))


# Increase verbosity specifically for the agent frameworks
logging.getLogger("google.adk").setLevel(logging.DEBUG)
logging.getLogger("google.genai").setLevel(logging.DEBUG)

APP_NAME = "brew"

app = FastAPI(title="Brew")

# CORS: allow cross-origin for Cloud Run (frontend + backend on different domains)
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if _USE_FIRESTORE:
    session_service = FirestoreSessionService()
    logger.info("Using FirestoreSessionService for cloud-native session persistence")
else:
    session_service = InMemorySessionService()
    logger.info("Firestore unavailable, using InMemorySessionService")

runner = Runner(
    app_name=APP_NAME,
    agent=root_agent,
    session_service=session_service,
)


@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: str,
    session_id: str,
) -> None:
    await websocket.accept()
    connection_id = f"ws_{uuid.uuid4().hex[:8]}"
    register_order_state(user_id, session_id)
    # If Firestore is enabled and this is a reconnect from a different instance,
    # restore the cart state from Firestore
    if get_order_state(user_id, session_id) is not None:
        existing = get_order_state(user_id, session_id)
        if not existing._items:  # Empty cart — try to restore
            await restore_order_state(user_id, session_id)
    live_request_queue: LiveRequestQueue | None = None
    live_queue_ref: dict[str, LiveRequestQueue | None] = {"queue": None}
    tool_gate: dict[str, object] = {"pending": False, "ids": set()}


    turn_counter = {"next": 1}

    def _log_turn(turn: dict, reason: str) -> None:
        turn["reason"] = reason
        turn["ended_at_ms"] = int(time.time() * 1000)
        payload = json.dumps(turn, ensure_ascii=False, default=str)
        logger.info("TURN_TRACE %s", payload)
        turn_trace_logger.info(payload)

    def _new_turn() -> dict:
        tid = turn_counter["next"]
        turn_counter["next"] = tid + 1
        return {
            "connection_id": connection_id,
            "session_id": session_id,
            "turn_id": tid,
            "started_at_ms": int(time.time() * 1000),
            "tool_calls": [],
            "tool_responses": [],
            "assistant_audio_events": 0,
            "interrupted": False,
        }

    try:
        session = await session_service.get_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if not session:
            await session_service.create_session(
                app_name=APP_NAME,
                user_id=user_id,
                session_id=session_id,
            )

        # Omit response_modalities so ADK uses its default (AUDIO for live); passing it triggers
        # Pydantic serialization warning where a downstream model expects enum but receives str.
        # Disable transcription config: native-audio model can return 1007 "invalid argument"
        # when transcription is enabled; transcriptions may still appear in events from the API.
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            input_audio_transcription=None,
            output_audio_transcription=None,
        )
        live_request_queue = LiveRequestQueue()
        live_queue_ref["queue"] = live_request_queue

        async def upstream_task() -> None:
            dropped_audio_chunks = 0
            try:
                while True:
                    try:
                        raw = await websocket.receive()
                    except WebSocketDisconnect:
                        break
                    except Exception:
                        break
                    if "bytes" in raw and raw["bytes"]:
                        if bool(tool_gate["pending"]):
                            dropped_audio_chunks += 1
                            if dropped_audio_chunks % 200 == 0:
                                logger.debug(
                                    "Dropped %s audio chunks while tool call pending.",
                                    dropped_audio_chunks,
                                )
                            continue
                        blob = types.Blob(
                            mime_type="audio/pcm;rate=16000",
                            data=raw["bytes"],
                        )
                        queue = live_queue_ref.get("queue")
                        if queue is not None:
                            try:
                                queue.send_realtime(blob)
                            except Exception:
                                pass
                    elif "text" in raw and raw["text"]:
                        try:
                            msg = json.loads(raw["text"])

                            if msg.get("type") == "turn_complete":
                                if bool(tool_gate["pending"]):
                                    logger.debug("Ignored turn_complete while tool call pending.")
                                continue

                            if msg.get("type") == "text" and "text" in msg:
                                content = types.Content(
                                    parts=[types.Part(text=msg["text"])]
                                )
                                queue = live_queue_ref.get("queue")
                                if queue is not None:
                                    try:
                                        queue.send_content(content)
                                    except Exception:
                                        pass
                        except json.JSONDecodeError:
                            content = types.Content(
                                parts=[types.Part(text=raw["text"])]
                            )
                            queue = live_queue_ref.get("queue")
                            if queue is not None:
                                try:
                                    queue.send_content(content)
                                except Exception:
                                    pass
            except Exception as e:
                logger.warning("Upstream task: %s", e)

        async def downstream_task() -> None:
            set_current_session(user_id, session_id)
            last_order_snapshot: list | None = None
            last_menu_context: str | None = None
            last_tool_gate_state = False
            transient_retry_count = 0
            current_turn: dict | None = None

            live_session_start: float = time.monotonic()
            total_events_received: int = 0
            last_event_summary: str = "(none)"

            async def _reset_live_stream(reason: str) -> None:
                nonlocal last_tool_gate_state, current_turn
                if current_turn:
                    _log_turn(current_turn, f"live_stream_reset:{reason}")
                    current_turn = None
                old_queue = live_queue_ref.get("queue")
                if old_queue is not None:
                    try:
                        old_queue.close()
                    except Exception:
                        pass
                new_queue = LiveRequestQueue()
                live_queue_ref["queue"] = new_queue
                tool_gate["pending"] = False
                ids = tool_gate.get("ids")
                if isinstance(ids, set):
                    ids.clear()
                if last_tool_gate_state:
                    last_tool_gate_state = False
                    await websocket.send_text(
                        json.dumps({"type": "realtime_input_gate", "blocked": False})
                    )

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
                    try:
                        new_queue.send_content(
                            types.Content(parts=[types.Part(text=ctx)])
                        )
                        logger.info("Injected order context after reset (%d items)", len(items))
                    except Exception:
                        pass

                logger.warning("Live stream reset: %s", reason)

            try:
                while websocket.client_state.name == "CONNECTED":
                    queue = live_queue_ref.get("queue")
                    if queue is None:
                        await asyncio.sleep(0.05)
                        continue
                    saw_event = False
                    try:
                        async for event in runner.run_live(
                            user_id=user_id,
                            session_id=session_id,
                            live_request_queue=queue,
                            run_config=run_config,
                        ):
                            saw_event = True
                            total_events_received += 1
                            transient_retry_count = 0
                            if websocket.client_state.name != "CONNECTED":
                                break

                            evt_parts_summary = ""
                            if event.content and event.content.parts:
                                evt_parts_summary = ",".join(
                                    "audio" if getattr(p, "inline_data", None)
                                    else "fc" if getattr(p, "function_call", None)
                                    else "fr" if getattr(p, "function_response", None)
                                    else "thought" if getattr(p, "thought", False)
                                    else "text"
                                    for p in event.content.parts
                                )
                            tc = "tc" if getattr(event, "turn_complete", False) else ""
                            err = f"err={event.error_code}" if event.error_code else ""
                            last_event_summary = "|".join(filter(None, [evt_parts_summary, tc, err]))

                            has_function_call = False
                            has_function_response = False
                            function_call_ids: set[str] = set()
                            function_response_ids: set[str] = set()
                            if event.content and event.content.parts:
                                for p in event.content.parts:
                                    fc = getattr(p, "function_call", None)
                                    fr = getattr(p, "function_response", None)
                                    if fc is not None:
                                        has_function_call = True
                                        fc_id = getattr(fc, "id", None)
                                        if fc_id:
                                            function_call_ids.add(fc_id)
                                        if current_turn is None:
                                            current_turn = _new_turn()
                                        current_turn["tool_calls"].append({
                                            "id": str(fc_id or ""),
                                            "name": str(getattr(fc, "name", "")),
                                            "args": str(getattr(fc, "args", ""))[:200],
                                        })
                                    if fr is not None:
                                        has_function_response = True
                                        fr_id = getattr(fr, "id", None)
                                        if fr_id:
                                            function_response_ids.add(fr_id)
                                        if current_turn is None:
                                            current_turn = _new_turn()
                                        current_turn["tool_responses"].append({
                                            "id": str(fr_id or ""),
                                            "name": str(getattr(fr, "name", "")),
                                            "result": str(getattr(fr, "response", ""))[:200],
                                        })

                            if has_function_call:
                                tool_gate["pending"] = True
                                ids = tool_gate["ids"]
                                if isinstance(ids, set):
                                    ids.update(function_call_ids)

                            if has_function_response:
                                ids = tool_gate["ids"]
                                if isinstance(ids, set):
                                    if function_response_ids:
                                        ids.difference_update(function_response_ids)
                                    else:
                                        ids.clear()
                                    if not ids:
                                        tool_gate["pending"] = False
                                else:
                                    tool_gate["pending"] = False

                            tool_call_cancellation = getattr(event, "tool_call_cancellation", None)
                            if tool_call_cancellation is not None:
                                cancel_ids = getattr(tool_call_cancellation, "ids", None) or []
                                ids = tool_gate["ids"]
                                if isinstance(ids, set):
                                    if cancel_ids:
                                        ids.difference_update(cancel_ids)
                                    else:
                                        ids.clear()
                                    if not ids:
                                        tool_gate["pending"] = False
                                else:
                                    tool_gate["pending"] = False

                            is_tool_gate_active = bool(tool_gate["pending"]) or bool(tool_gate["ids"])
                            if is_tool_gate_active != last_tool_gate_state:
                                last_tool_gate_state = is_tool_gate_active
                                await websocket.send_text(
                                    json.dumps({"type": "realtime_input_gate", "blocked": is_tool_gate_active})
                                )

                            if getattr(event, "interrupted", False):
                                logger.debug("Barge-in detected: sending interrupt signal.")
                                if current_turn is None:
                                    current_turn = _new_turn()
                                current_turn["interrupted"] = True
                                await websocket.send_text(
                                    json.dumps({"type": "interrupted", "interrupted": True})
                                )

                            if event.error_code:
                                code = str(event.error_code)
                                elapsed_s = time.monotonic() - live_session_start
                                logger.warning(
                                    "DIAG Live API error: code=%s message=%s | elapsed=%.1fs events=%d last_event=[%s] session=%s conn=%s",
                                    code, event.error_message or "",
                                    elapsed_s, total_events_received, last_event_summary,
                                    session_id, connection_id,
                                )
                                await websocket.send_text(
                                    json.dumps({
                                        "type": "error",
                                        "code": code,
                                        "message": event.error_message or "",
                                        "diag": {
                                            "elapsed_s": round(elapsed_s, 1),
                                            "total_events": total_events_received,
                                            "last_event": last_event_summary,
                                        },
                                    })
                                )
                                if code in {"1007", "1008", "1011"}:
                                    raise RuntimeError(f"Transient live API error code={code}")
                                continue

                            order = get_order_state(user_id, session_id)
                            if order:
                                current = order.snapshot()
                                if current != last_order_snapshot:
                                    last_order_snapshot = current
                                    await websocket.send_text(
                                        json.dumps({"type": "order_state", "payload": current})
                                    )
                                if getattr(order, 'menu_context', None) != last_menu_context:
                                    last_menu_context = order.menu_context
                                    await websocket.send_text(
                                        json.dumps({"type": "ui_context_change", "context": order.menu_context})
                                    )

                            if event.content and event.content.parts:
                                has_function = any(
                                    getattr(p, 'function_call', None) or getattr(p, 'function_response', None)
                                    for p in event.content.parts
                                )
                                if not has_function:
                                    is_thought_only = all(
                                        getattr(p, 'thought', False) and not getattr(p, 'inline_data', None)
                                        for p in event.content.parts
                                    )
                                    if is_thought_only:
                                        continue

                            has_audio = (
                                event.content
                                and event.content.parts
                                and any(getattr(p, "inline_data", None) for p in event.content.parts)
                            )

                            turn_complete_flag = bool(getattr(event, "turn_complete", False))

                            if has_audio:
                                if current_turn is None:
                                    current_turn = _new_turn()
                                current_turn["assistant_audio_events"] += 1
                                for part in event.content.parts:
                                    if getattr(part, "inline_data", None):
                                        await websocket.send_bytes(part.inline_data.data)
                                meta = event.model_dump(
                                    exclude={"content": {"parts": {"__all__": {"inline_data"}}}},
                                    exclude_none=True,
                                    by_alias=True,
                                )
                                if "content" in meta and "parts" in meta["content"]:
                                    for p in meta["content"]["parts"]:
                                        p.pop("inlineData", None)
                                        p.pop("inline_data", None)
                                await websocket.send_text(json.dumps(meta))
                            else:
                                await websocket.send_text(
                                    event.model_dump_json(exclude_none=True, by_alias=True)
                                )

                            if turn_complete_flag and current_turn:
                                _log_turn(current_turn, "turn_complete")
                                current_turn = None

                            if turn_complete_flag and not bool(tool_gate["pending"]):
                                elapsed_s = time.monotonic() - live_session_start
                                if elapsed_s >= PROACTIVE_RECONNECT_S:
                                    logger.info(
                                        "Proactive reconnect at %.0fs (limit %ds) session=%s conn=%s",
                                        elapsed_s, PROACTIVE_RECONNECT_S, session_id, connection_id,
                                    )
                                    await _reset_live_stream("proactive_timer")
                                    live_session_start = time.monotonic()
                                    total_events_received = 0
                                    last_event_summary = "(proactive_reset)"
                                    transient_retry_count = 0
                                    break

                        if websocket.client_state.name != "CONNECTED":
                            break

                        if last_event_summary == "(proactive_reset)":
                            continue

                        elapsed_s = time.monotonic() - live_session_start
                        transient_retry_count += 1
                        if transient_retry_count > MAX_TRANSIENT_LIVE_RETRIES:
                            logger.error(
                                "DIAG Live stream ended repeatedly; giving up after %s retries | elapsed=%.1fs events=%d last_event=[%s] session=%s conn=%s",
                                transient_retry_count,
                                elapsed_s, total_events_received, last_event_summary,
                                session_id, connection_id,
                            )
                            break
                        backoff_s = min(5.0, 0.5 * (2 ** (transient_retry_count - 1)))
                        logger.warning(
                            "DIAG Live stream ended silently; retrying in %.1fs (attempt %s) | elapsed=%.1fs events=%d saw_event=%s last_event=[%s] session=%s conn=%s",
                            backoff_s, transient_retry_count,
                            elapsed_s, total_events_received, saw_event, last_event_summary,
                            session_id, connection_id,
                        )
                        await _reset_live_stream(f"stream_end attempt={transient_retry_count}")
                        live_session_start = time.monotonic()
                        total_events_received = 0
                        last_event_summary = "(reset)"
                        await asyncio.sleep(backoff_s)

                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        if websocket.client_state.name != "CONNECTED":
                            break
                        elapsed_s = time.monotonic() - live_session_start
                        if _is_transient_live_exception(e):
                            transient_retry_count += 1
                            if transient_retry_count > MAX_TRANSIENT_LIVE_RETRIES:
                                logger.error(
                                    "DIAG Live stream gave up after %s retries: %s(%s) | elapsed=%.1fs events=%d last_event=[%s] session=%s conn=%s",
                                    transient_retry_count, type(e).__name__, e,
                                    elapsed_s, total_events_received, last_event_summary,
                                    session_id, connection_id,
                                )
                                break
                            backoff_s = min(5.0, 0.5 * (2 ** (transient_retry_count - 1)))
                            logger.warning(
                                "DIAG Transient error; retrying in %.1fs (attempt %s): %s(%s) | elapsed=%.1fs events=%d last_event=[%s] session=%s conn=%s",
                                backoff_s, transient_retry_count, type(e).__name__, e,
                                elapsed_s, total_events_received, last_event_summary,
                                session_id, connection_id,
                            )
                            await _reset_live_stream(f"exception attempt={transient_retry_count}")
                            live_session_start = time.monotonic()
                            total_events_received = 0
                            last_event_summary = "(reset)"
                            await asyncio.sleep(backoff_s)
                            continue
                        logger.error(
                            "DIAG Non-transient exception: %s(%s) | elapsed=%.1fs events=%d last_event=[%s] session=%s conn=%s",
                            type(e).__name__, e,
                            elapsed_s, total_events_received, last_event_summary,
                            session_id, connection_id,
                        )
                        raise
            except Exception as e:
                elapsed_s = time.monotonic() - live_session_start
                logger.warning(
                    "DIAG Downstream task ended: %s(%s) | elapsed=%.1fs events=%d last_event=[%s] session=%s conn=%s",
                    type(e).__name__, e,
                    elapsed_s, total_events_received, last_event_summary,
                    session_id, connection_id,
                )

        await asyncio.gather(
            upstream_task(),
            downstream_task(),
            return_exceptions=True,
        )
    finally:
        queue = live_queue_ref.get("queue")
        if queue is not None:
            queue.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/menu")
def menu():
    return get_menu_dict()
