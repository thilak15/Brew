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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import root_agent, set_current_session
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

LOG_DIR = Path("/app/debug_logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "backend.log"

# Logging setup
LOG_DIR = Path("/app/debug_logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "backend.log"

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

logger = logging.getLogger(__name__)

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
    register_order_state(user_id, session_id)
    # If Firestore is enabled and this is a reconnect from a different instance,
    # restore the cart state from Firestore
    if get_order_state(user_id, session_id) is not None:
        existing = get_order_state(user_id, session_id)
        if not existing._items:  # Empty cart — try to restore
            await restore_order_state(user_id, session_id)
    live_request_queue: LiveRequestQueue | None = None

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

        async def upstream_task() -> None:
            try:
                while True:
                    try:
                        raw = await websocket.receive()
                    except WebSocketDisconnect:
                        break
                    except Exception:
                        # e.g. "Cannot call receive once a disconnect message has been received" on reload
                        break
                    if "bytes" in raw and raw["bytes"]:
                        blob = types.Blob(
                            mime_type="audio/pcm;rate=16000",
                            data=raw["bytes"],
                        )
                        live_request_queue.send_realtime(blob)
                    elif "text" in raw and raw["text"]:
                        try:
                            msg = json.loads(raw["text"])
                            if msg.get("type") == "text" and "text" in msg:
                                content = types.Content(
                                    parts=[types.Part(text=msg["text"])]
                                )
                                live_request_queue.send_content(content)
                        except json.JSONDecodeError:
                            content = types.Content(
                                parts=[types.Part(text=raw["text"])]
                            )
                            live_request_queue.send_content(content)
            except Exception as e:
                logger.warning("Upstream task: %s", e)

        async def downstream_task() -> None:
            set_current_session(user_id, session_id)
            last_order_snapshot: list | None = None
            last_menu_context: str | None = None
            try:
                async for event in runner.run_live(
                    user_id=user_id,
                    session_id=session_id,
                    live_request_queue=live_request_queue,
                    run_config=run_config,
                ):
                    if websocket.client_state.name != "CONNECTED":
                        break
                    if event.error_code:
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "error",
                                    "code": event.error_code,
                                    "message": event.error_message or "",
                                }
                            )
                        )
                        continue
                    # ALWAYS check and send order state + menu context, even for thought events
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
                    # Skip thought-only events (internal AI reasoning with no audio)
                    # These cause silence because the frontend receives content but no audio to play.
                    # NEVER skip events that contain function_call or function_response parts.
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
                                logger.debug("Skipping thought-only event (no audio)")
                                continue
                    has_audio = (
                        event.content
                        and event.content.parts
                        and any(
                            getattr(p, "inline_data", None)
                            for p in event.content.parts
                        )
                    )
                    if has_audio:
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
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Downstream task: %s", e)

        await asyncio.gather(
            upstream_task(),
            downstream_task(),
            return_exceptions=True,
        )
    finally:
        if live_request_queue is not None:
            live_request_queue.close()
        # Persist order state so it survives reconnects!
        # unregister_order_state(user_id, session_id)


@app.get("/health")
def health():
    return {"status": "ok"}
