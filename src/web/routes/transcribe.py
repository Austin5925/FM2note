from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from src.config import load_config
from src.transcribe_flow import preview_episode, transcribe_single_url
from src.web.paths import CONFIG_PATH
from src.web.progress import ProgressEvent, get_bus
from src.web.services.error_messages import friendly_transcribe_error

router = APIRouter(prefix="/api")


@router.get("/episode/preview")
async def episode_preview(url: str) -> dict[str, Any]:
    """Lightweight metadata fetch for the URL input failover.

    Used by the frontend on blur to show the user what they're about to transcribe.
    Always returns 200; on failure the dict has ``error`` populated.
    """
    if not url.strip():
        raise HTTPException(status_code=400, detail="url is required")
    try:
        return await preview_episode(url)
    except Exception as e:
        logger.warning("preview failed for {}: {}: {}", url, type(e).__name__, e)
        return {"error": f"{type(e).__name__}: {e}", "audio_url": url}


@router.post("/transcribe")
async def submit_transcribe(payload: dict) -> dict:
    """Create a transcribe task and return its task_id.

    The actual work runs as a background asyncio task; clients subscribe to
    ``GET /api/transcribe/{task_id}/stream`` for SSE progress.
    """
    url = (payload or {}).get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    try:
        config = load_config(CONFIG_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"load_config failed: {e}") from e

    bus = get_bus()
    task_id, _queue = bus.create()

    loop = asyncio.get_running_loop()

    def callback(stage: str, status: str, message: str) -> None:
        # Called from worker code; relay onto the bus via the event loop.
        bus.publish(task_id, ProgressEvent(stage=stage, status=status, message=message))  # type: ignore[arg-type]

    async def _run() -> None:
        try:
            outcome = await transcribe_single_url(
                url, config, progress_callback=callback
            )
            obsidian_url = _make_obsidian_url(config.vault_path, outcome.note_path)
            bus.update_record(
                task_id,
                note_path=str(outcome.note_path),
                title=outcome.title,
                podcast_name=outcome.podcast_name,
                char_count=outcome.char_count,
                paragraph_count=outcome.paragraph_count,
                elapsed_ms=outcome.elapsed_ms,
                summary_failed=outcome.summary_failed,
            )
            bus.publish(
                task_id,
                ProgressEvent(
                    stage="write",
                    status="done",
                    message="complete",
                    extra={
                        "note_path": str(outcome.note_path),
                        "obsidian_url": obsidian_url,
                        "char_count": outcome.char_count,
                        "paragraph_count": outcome.paragraph_count,
                        "elapsed_ms": outcome.elapsed_ms,
                        "title": outcome.title,
                        "podcast_name": outcome.podcast_name,
                        "summary_failed": outcome.summary_failed,
                    },
                ),
            )
        except Exception as e:
            logger.warning("transcribe task {} failed: {}", task_id, type(e).__name__)
            friendly = friendly_transcribe_error(e)
            bus.update_record(task_id, error=friendly)
            bus.publish(
                task_id,
                ProgressEvent(stage="write", status="error", message=friendly),
            )
        finally:
            bus.close(task_id)

    loop.create_task(_run())
    return {"task_id": task_id}


@router.get("/transcribe/{task_id}/stream")
async def stream_progress(task_id: str, request: Request) -> StreamingResponse:
    bus = get_bus()
    queue = bus.get_queue(task_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="task_id not found or already expired")

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    # heartbeat to keep proxies happy and detect client disconnect
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    yield "event: end\ndata: {}\n\n"
                    break
                payload = json.dumps(item.to_dict(), ensure_ascii=False)
                yield f"event: progress\ndata: {payload}\n\n"
        except asyncio.CancelledError:
            raise

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _make_obsidian_url(vault_path: str, note_path) -> str:
    """Build an obsidian:// deep link for the just-written note.

    Format: obsidian://open?vault=<vault-name>&file=<relative-path-without-extension>
    """
    from pathlib import Path

    vault = Path(vault_path).resolve()
    note = Path(note_path).resolve()
    try:
        rel = note.relative_to(vault).with_suffix("")
    except ValueError:
        return ""
    return f"obsidian://open?vault={quote(vault.name)}&file={quote(str(rel))}"
