from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.config import load_config
from src.summarizer.factory import create_summarizer
from src.summarizer.pending import (
    _get_pending_dir,
    insert_summary_into_note,
    load_all_pending,
    remove_pending,
)
from src.web.paths import CONFIG_PATH
from src.web.services.obsidian_url import build_obsidian_url
from src.web.services.state_singleton import get_state_manager

router = APIRouter(prefix="/api")

# pending summary filenames are MD5(guid)[:16] hex — strict allowlist
_SAFE_ID = re.compile(r"^[A-Fa-f0-9]{1,32}$")


def _from_processed(ep, vault_path: str) -> dict[str, Any]:
    return {
        "guid": ep.guid,
        "title": ep.title,
        "podcast_name": ep.podcast_name,
        "status": ep.status,
        "error_msg": ep.error_msg,
        "retry_count": ep.retry_count,
        "note_path": ep.note_path,
        "obsidian_url": build_obsidian_url(vault_path, ep.note_path) if ep.note_path else "",
        "updated_at": ep.updated_at.isoformat() if ep.updated_at else None,
    }


def _resolve_pending(target_id: str) -> Path:
    """Resolve a pending-summary id to its file path, defending against path traversal."""
    if not _SAFE_ID.match(target_id):
        raise HTTPException(status_code=400, detail="invalid id format")
    pending_root = _get_pending_dir().resolve()
    candidate = (pending_root / f"{target_id}.json").resolve()
    try:
        candidate.relative_to(pending_root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid id") from e
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="pending entry not found")
    return candidate


@router.get("/history")
async def list_history(limit: int = 20) -> dict:
    """List recent processed episodes + pending summaries.

    Returns ``{"episodes": [...], "pending_summaries": [...]}``.
    Episodes are sorted by ``updated_at`` descending.
    """
    try:
        config = load_config(CONFIG_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"load_config failed: {e}") from e

    # v1.5.2 audit fix (Code Review A3 + StateManager-singleton work): use the
    # shared FastAPI-lifespan-owned StateManager AND query with SQL LIMIT +
    # filter so the DB does the sort/slice work instead of pulling every row
    # (including backfill_skipped) into Python memory.
    state = await get_state_manager(config.db_path)
    rows = await state.get_recent_history(limit=max(1, limit))
    episodes = [_from_processed(r, config.vault_path) for r in rows]

    pending: list[dict[str, Any]] = []
    for item in load_all_pending():
        pending.append(
            {
                "id": Path(item["_filepath"]).stem,
                "filepath": item["_filepath"],
                "guid": item.get("guid", ""),
                "title": item.get("title", ""),
                "podcast_name": item.get("podcast_name", ""),
                "note_path": item.get("note_path", ""),
            }
        )

    return {"episodes": episodes, "pending_summaries": pending}


@router.post("/history/retry-summary")
async def retry_summary(payload: dict) -> dict:
    """Retry a single pending summary by its safe-format ``id``."""
    target_id = (payload or {}).get("id", "").strip()
    if not target_id:
        raise HTTPException(status_code=400, detail="id is required")

    try:
        config = load_config(CONFIG_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"load_config failed: {e}") from e

    summarizer = create_summarizer(config)
    if summarizer is None:
        raise HTTPException(
            status_code=409, detail="未配置摘要服务（请在设置页配置 Poe / OpenAI key）"
        )

    target_path = _resolve_pending(target_id)
    item = json.loads(target_path.read_text(encoding="utf-8"))

    try:
        result = await summarizer.summarize(item["text"], item.get("title", ""))
    except Exception as e:
        logger.warning("retry summary failed: {}", type(e).__name__)
        return {"ok": False, "error": type(e).__name__}

    if not insert_summary_into_note(item["note_path"], result):
        return {"ok": False, "error": "无法定位笔记中的摘要占位（请检查笔记是否被改动）"}

    remove_pending(str(target_path))
    return {"ok": True, "title": item.get("title", "")}


@router.post("/history/retry-all")
async def retry_all_summaries() -> dict:
    """Trigger retry for every pending summary, sequentially."""
    try:
        config = load_config(CONFIG_PATH)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"load_config failed: {e}") from e

    summarizer = create_summarizer(config)
    if summarizer is None:
        raise HTTPException(
            status_code=409, detail="未配置摘要服务（请在设置页配置 Poe / OpenAI key）"
        )

    pending = load_all_pending()
    total = len(pending)
    success = 0
    failed = 0

    for item in pending:
        try:
            result = await summarizer.summarize(item["text"], item.get("title", ""))
            if insert_summary_into_note(item["note_path"], result):
                remove_pending(item["_filepath"])
                success += 1
            else:
                failed += 1
        except Exception as e:
            logger.warning("retry summary failed for {}: {}", item.get("title"), type(e).__name__)
            failed += 1

    return {"total": total, "success": success, "failed": failed}
