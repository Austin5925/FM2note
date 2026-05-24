from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from loguru import logger
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from src.web.paths import SUBSCRIPTIONS_PATH
from src.web.services import locks
from src.web.services.subscription_resolver import detect_rsshub_base, resolve_subscription_input
from src.web.services.yaml_writer import dump_yaml, load_yaml

router = APIRouter(prefix="/api")


def _to_dict(item) -> dict:
    if not isinstance(item, dict):
        return {}
    tags = item.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return {
        "name": str(item.get("name", "")),
        "rss_url": str(item.get("rss_url", "")),
        "tags": [str(t) for t in tags],
    }


def _ensure_doc_with_seq(doc):
    """Return ``(doc, podcasts_seq)`` ensuring ``doc['podcasts']`` is a sequence.

    Raises HTTP 400 if a corrupt structure prevents safe editing.
    """
    if doc is None:
        doc = CommentedMap()
        doc["podcasts"] = CommentedSeq()
        return doc, doc["podcasts"]
    if not isinstance(doc, dict):
        raise HTTPException(status_code=400, detail="subscriptions.yaml root must be a mapping")
    podcasts = doc.get("podcasts")
    if podcasts is None:
        doc["podcasts"] = CommentedSeq()
        return doc, doc["podcasts"]
    if not isinstance(podcasts, list):
        raise HTTPException(
            status_code=400, detail="`podcasts` must be a list in subscriptions.yaml"
        )
    return doc, podcasts


@router.get("/subscriptions")
async def list_subs() -> dict:
    if not Path(SUBSCRIPTIONS_PATH).exists():
        return {"path": SUBSCRIPTIONS_PATH, "subscriptions": []}
    doc = load_yaml(SUBSCRIPTIONS_PATH)
    _doc, items = _ensure_doc_with_seq(doc)
    return {
        "path": SUBSCRIPTIONS_PATH,
        "subscriptions": [{"index": i, **_to_dict(it)} for i, it in enumerate(items)],
    }


@router.get("/subscriptions/defaults")
async def subscription_defaults() -> dict:
    return {"rsshub_base": detect_rsshub_base(), "path": SUBSCRIPTIONS_PATH}


@router.post("/subscriptions/resolve")
async def resolve_sub(payload: dict) -> dict:
    input_text = (payload or {}).get("input", "").strip()
    if not input_text:
        raise HTTPException(status_code=400, detail="input is required")
    rsshub_base = (payload or {}).get("rsshub_base", "").strip()
    try:
        return await resolve_subscription_input(input_text, rsshub_base)
    except Exception as e:
        logger.warning("subscription resolve failed: {}", type(e).__name__)
        return {
            "ok": False,
            "error": f"自动识别失败：{type(e).__name__}",
            "rsshub_base": detect_rsshub_base(),
        }


@router.post("/subscriptions")
async def add_sub(payload: dict) -> dict:
    new_item = _validate_payload(payload)
    Path(SUBSCRIPTIONS_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with locks.yaml_lock:
        doc = load_yaml(SUBSCRIPTIONS_PATH)
        doc, items = _ensure_doc_with_seq(doc)
        items.append(_to_commented_map(new_item))
        dump_yaml(SUBSCRIPTIONS_PATH, doc)
        return {"ok": True, "index": len(items) - 1}


@router.put("/subscriptions/{index}")
async def update_sub(index: int, payload: dict) -> dict:
    new_item = _validate_payload(payload)
    async with locks.yaml_lock:
        doc = load_yaml(SUBSCRIPTIONS_PATH)
        doc, items = _ensure_doc_with_seq(doc)
        if index < 0 or index >= len(items):
            raise HTTPException(status_code=404, detail="subscription not found")
        items[index] = _to_commented_map(new_item)
        dump_yaml(SUBSCRIPTIONS_PATH, doc)
        return {"ok": True, "index": index}


@router.delete("/subscriptions/{index}")
async def delete_sub(index: int) -> dict:
    async with locks.yaml_lock:
        doc = load_yaml(SUBSCRIPTIONS_PATH)
        doc, items = _ensure_doc_with_seq(doc)
        if index < 0 or index >= len(items):
            raise HTTPException(status_code=404, detail="subscription not found")
        removed = items.pop(index)
        dump_yaml(SUBSCRIPTIONS_PATH, doc)
        return {"ok": True, "removed": _to_dict(removed)}


@router.post("/subscriptions/test")
async def test_sub(payload: dict) -> dict:
    """Probe an RSS URL with feedparser. Validates scheme to mitigate SSRF.

    Note: we intentionally do **not** block RFC-1918 / loopback addresses —
    legitimate self-hosted RSSHub setups commonly live on the local network,
    and the web server is bound to 127.0.0.1 so the only attacker who could
    abuse this already has local code execution.
    """
    url = (payload or {}).get("rss_url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="rss_url is required")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": f"不支持的协议: {parsed.scheme or '(空)'}"}
    if not parsed.hostname:
        return {"ok": False, "error": "URL 缺少主机名"}

    try:
        import feedparser

        feed = feedparser.parse(url)
    except Exception as e:
        logger.warning("rss test failed for {}: {}", url, type(e).__name__)
        return {"ok": False, "error": f"{type(e).__name__}"}

    if getattr(feed, "bozo", 0) and not feed.entries:
        reason = getattr(feed, "bozo_exception", None)
        return {"ok": False, "error": f"无法解析 RSS：{reason}"}

    feed_title = feed.feed.get("title", "") if hasattr(feed.feed, "get") else ""
    latest_title = feed.entries[0].get("title", "") if feed.entries else ""
    return {
        "ok": True,
        "feed_title": feed_title,
        "episode_count": len(feed.entries),
        "latest_title": latest_title,
    }


def _validate_payload(payload: dict) -> dict:
    name = (payload or {}).get("name", "").strip()
    rss_url = (payload or {}).get("rss_url", "").strip()
    tags = (payload or {}).get("tags") or []
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not rss_url:
        raise HTTPException(status_code=400, detail="rss_url is required")
    if not isinstance(tags, list):
        raise HTTPException(status_code=400, detail="tags must be a list")
    return {"name": name, "rss_url": rss_url, "tags": [str(t) for t in tags]}


def _to_commented_map(item: dict) -> CommentedMap:
    """Convert a plain dict to a CommentedMap for ruamel insertion."""
    cm = CommentedMap()
    for k, v in item.items():
        if isinstance(v, list):
            seq = CommentedSeq()
            for vv in v:
                seq.append(vv)
            cm[k] = seq
        else:
            cm[k] = v
    return cm
