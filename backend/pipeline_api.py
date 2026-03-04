"""
Pipeline API Router
===================
FastAPI router that exposes endpoints for the restaurant setup UI:

  POST /api/pipeline/run        — Start pipeline (form upload: name, id, url or images)
  GET  /api/pipeline/progress/{job_id}  — SSE stream of pipeline progress
  GET  /api/pipeline/active     — Get currently active restaurant
  POST /api/pipeline/confirm/{job_id}   — Set a completed job as the active restaurant
  GET  /api/pipeline/menu/{restaurant_id} — Get menu.json for a restaurant
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Path resolution — pipeline/ is a sibling of backend/
_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_PIPELINE_DIR = _PROJECT_ROOT / "pipeline"
_OUTPUT_DIR = _PIPELINE_DIR / "output"
_ACTIVE_FILE = _OUTPUT_DIR / "active_restaurant.json"

# Ensure pipeline is importable
sys.path.insert(0, str(_PIPELINE_DIR))

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# In-memory job store: job_id → { status, progress_messages, result, error }
_jobs: dict[str, dict[str, Any]] = {}


# ─── Helpers ────────────────────────────────────────────────────────────────

def _read_active() -> dict | None:
    if _ACTIVE_FILE.exists():
        try:
            return json.loads(_ACTIVE_FILE.read_text())
        except Exception:
            return None
    return None


def _write_active(restaurant_id: str, restaurant_name: str) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _ACTIVE_FILE.write_text(json.dumps({
        "restaurant_id": restaurant_id,
        "restaurant_name": restaurant_name,
    }, indent=2))


# ─── Background pipeline runner ─────────────────────────────────────────────

async def _run_pipeline_job(
    job_id: str,
    restaurant_name: str,
    restaurant_id: str,
    url: str | None,
    image_paths: list[str],
) -> None:
    job = _jobs[job_id]
    job["status"] = "running"

    def emit(msg: str) -> None:
        logger.info("[Job %s] %s", job_id, msg)
        job["progress"].append(msg)

    try:
        emit(f"🚀 Starting pipeline for **{restaurant_name}** (ID: `{restaurant_id}`)")

        # Import pipeline modules lazily (they need GOOGLE_API_KEY in env)
        from agent1_menu_analyzer import analyze_menu, save_menu
        from agent2_prompt_architect import generate_prompt, save_prompt

        # ── Agent 1: Menu Analysis ────────────────────────────────────────
        emit("🔍 Agent 1: Analyzing menu with Gemini multimodal...")
        loop = asyncio.get_event_loop()
        menu = await loop.run_in_executor(
            None,
            lambda: analyze_menu(
                restaurant_name=restaurant_name,
                restaurant_id=restaurant_id,
                image_paths=image_paths if image_paths else None,
                url=url if url else None,
            )
        )
        menu_path = save_menu(menu, restaurant_id)
        emit(f"✅ Menu extracted: **{len(menu.items)} items** across **{len(menu.categories)} categories**, **{len(menu.combos)} combos**")
        emit(f"📂 Categories: {', '.join(menu.categories)}")

        # ── Agent 2: Prompt Generation ────────────────────────────────────
        emit("✍️ Agent 2: Generating drive-through system prompt...")
        prompt_text = await loop.run_in_executor(
            None,
            lambda: generate_prompt(menu)
        )
        prompt_path = save_prompt(prompt_text, restaurant_id)
        emit(f"✅ System prompt generated ({len(prompt_text)} chars)")

        # ── Done ──────────────────────────────────────────────────────────
        emit("🎉 Pipeline complete! Review the menu below and confirm to activate.")
        job["status"] = "done"
        job["restaurant_id"] = restaurant_id
        job["restaurant_name"] = restaurant_name
        job["menu"] = menu.model_dump()

    except Exception as e:
        logger.exception("Pipeline job %s failed", job_id)
        job["status"] = "error"
        job["error"] = str(e)
        emit(f"❌ Error: {e}")
    finally:
        # Cleanup temp image files
        for p in image_paths:
            try:
                os.unlink(p)
            except Exception:
                pass


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/run")
async def run_pipeline(
    restaurant_name: str = Form(...),
    restaurant_id: str = Form(...),
    url: str = Form(""),
    images: list[UploadFile] = File(default=[]),
):
    """Start a pipeline job. Returns a job_id to poll progress via SSE."""
    if not url and not images:
        raise HTTPException(400, "Provide either a URL or at least one image")

    # Save uploaded images to temp files
    image_paths: list[str] = []
    for img in images:
        suffix = Path(img.filename or "menu.jpg").suffix or ".jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(await img.read())
        tmp.close()
        image_paths.append(tmp.name)

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "status": "pending",
        "progress": [],
        "restaurant_id": restaurant_id,
        "restaurant_name": restaurant_name,
        "menu": None,
        "error": None,
    }

    # Run pipeline in background
    asyncio.create_task(_run_pipeline_job(
        job_id=job_id,
        restaurant_name=restaurant_name,
        restaurant_id=restaurant_id,
        url=url or None,
        image_paths=image_paths,
    ))

    return {"job_id": job_id}


@router.get("/progress/{job_id}")
async def pipeline_progress(job_id: str):
    """SSE stream: sends progress messages as they come in, closes when done/error."""
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")

    async def event_stream() -> AsyncGenerator[str, None]:
        sent_index = 0
        job = _jobs[job_id]

        while True:
            messages = job["progress"]
            # Send any new messages
            while sent_index < len(messages):
                msg = messages[sent_index]
                yield f"data: {json.dumps({'type': 'progress', 'message': msg})}\n\n"
                sent_index += 1

            if job["status"] == "done":
                yield f"data: {json.dumps({'type': 'done', 'job_id': job_id, 'restaurant_id': job['restaurant_id'], 'restaurant_name': job['restaurant_name']})}\n\n"
                break
            elif job["status"] == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': job.get('error', 'Unknown error')})}\n\n"
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/menu/{restaurant_id}")
async def get_menu(restaurant_id: str):
    """Return the extracted menu.json for a completed restaurant."""
    menu_path = _OUTPUT_DIR / restaurant_id / "menu.json"
    if not menu_path.exists():
        raise HTTPException(404, f"No menu found for restaurant_id: {restaurant_id}")
    return json.loads(menu_path.read_text())


@router.post("/confirm/{job_id}")
async def confirm_restaurant(job_id: str):
    """Set the completed job's restaurant as the active one."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] != "done":
        raise HTTPException(400, "Job not completed yet")

    restaurant_id = job["restaurant_id"]
    restaurant_name = job["restaurant_name"]

    # Write active restaurant file
    _write_active(restaurant_id, restaurant_name)

    # Also update the env var in the running process so menu.py picks it up immediately
    os.environ["RESTAURANT_ID"] = restaurant_id

    # Force menu.py to reload by clearing its module-level cache
    import menu as menu_module
    menu_module.RESTAURANT_ID = restaurant_id

    logger.info("Active restaurant set to: %s (%s)", restaurant_name, restaurant_id)
    return {"status": "activated", "restaurant_id": restaurant_id, "restaurant_name": restaurant_name}


@router.get("/active")
async def get_active():
    """Get the currently active restaurant (if any)."""
    active = _read_active()
    # Also check env var (for CLI-set restaurants)
    env_id = os.getenv("RESTAURANT_ID", "")
    if not active and env_id:
        active = {"restaurant_id": env_id, "restaurant_name": env_id}
    return active or {}
