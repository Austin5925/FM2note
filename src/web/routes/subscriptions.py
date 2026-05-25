from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from loguru import logger
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from src.config import load_config
from src.web.paths import CONFIG_PATH, SUBSCRIPTIONS_PATH
from src.web.services import locks
from src.web.services.feed_preview import (
    estimate_cost_cny,
    filter_for_backfill,
    project_feed,
)
from src.web.services.state_singleton import get_state_manager
from src.web.services.subscription_resolver import detect_rsshub_base, resolve_subscription_input
from src.web.services.yaml_writer import dump_yaml, load_yaml

router = APIRouter(prefix="/api")

# Backfill strategies accepted by POST /api/subscriptions
_VALID_BACKFILL_STRATEGIES = {"all", "new_only", "recent_n", "since_date"}


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
    """Add a subscription, with an explicit backfill strategy.

    v1.4.15: ``backfill_strategy`` is REQUIRED so the user can never
    silently burn DashScope quota on every episode already in the feed.
    See ``POST /api/subscriptions/preview`` for the per-episode counts and
    cost estimate the UI should show before calling this endpoint.

    Body shape::

        {
          "name": "...",
          "rss_url": "https://...",
          "tags": [...],
          "backfill_strategy": "all" | "new_only" | "recent_n" | "since_date",
          "recent_n": 3,                # required if strategy == recent_n
          "since_date": "2026-01-01"    # required if strategy == since_date (YYYY-MM-DD)
        }
    """
    new_item = _validate_payload(payload)

    strategy = (payload or {}).get("backfill_strategy", "").strip()
    if strategy not in _VALID_BACKFILL_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=(f"backfill_strategy 必填，可选值: {sorted(_VALID_BACKFILL_STRATEGIES)}"),
        )
    recent_n = (payload or {}).get("recent_n")
    since_date = (payload or {}).get("since_date")
    # Code Review I4 (v1.4.15): recent_n must be a *positive* int. Without
    # the lower bound, -5 silently clamped to 0 (skip everything) inside
    # filter_for_backfill while the response reported strategy=recent_n.
    if strategy == "recent_n" and (not isinstance(recent_n, int) or recent_n < 1):
        raise HTTPException(status_code=400, detail="strategy=recent_n 需要正整数 recent_n")
    if strategy == "since_date" and not (isinstance(since_date, str) and since_date.strip()):
        raise HTTPException(
            status_code=400, detail="strategy=since_date 需要 YYYY-MM-DD since_date"
        )

    Path(SUBSCRIPTIONS_PATH).parent.mkdir(parents=True, exist_ok=True)
    # Hold yaml_lock across the entire validate-and-commit so:
    #  * Code Review I1: concurrent POSTs for the same URL can't both pass
    #    the dup-check and both append (duplicate subscription rows).
    #  * Codex BUG 11: if _apply_backfill_strategy raises (feed unreachable
    #    / unparseable), we MUST NOT append — otherwise the subscription
    #    sits in yaml with no skip-marks and the next poll re-transcribes
    #    every episode, reintroducing the very quota-burn this feature
    #    exists to prevent.
    async with locks.yaml_lock:
        doc = load_yaml(SUBSCRIPTIONS_PATH)
        doc, items = _ensure_doc_with_seq(doc)

        existing_urls = {str(it.get("rss_url", "")).strip() for it in items if isinstance(it, dict)}
        if new_item["rss_url"] in existing_urls:
            raise HTTPException(
                status_code=409,
                detail=f"该 rss_url 已经订阅过：{new_item['rss_url']}",
            )

        # Now apply backfill inside the lock. _apply_backfill_strategy raises
        # HTTPException on fetch/parse failure for any non-"all" strategy so
        # we never proceed to dump_yaml with an un-marked feed.
        skipped_count = await _apply_backfill_strategy(
            rss_url=new_item["rss_url"],
            podcast_name=new_item["name"],
            strategy=strategy,
            recent_n=recent_n,
            since_date=since_date,
        )

        items.append(_to_commented_map(new_item))
        dump_yaml(SUBSCRIPTIONS_PATH, doc)
        return {
            "ok": True,
            "index": len(items) - 1,
            "backfill_strategy": strategy,
            "backfill_skipped_count": skipped_count,
        }


async def _apply_backfill_strategy(
    *,
    rss_url: str,
    podcast_name: str,
    strategy: str,
    recent_n: int | None,
    since_date: str | None,
) -> int:
    """Resolve the feed, decide which episodes to skip, mark them in state.db.

    Returns the number of episodes actually marked as ``backfill_skipped``.
    Strategy ``all`` is a no-op (every episode will go through the pipeline).

    Raises ``HTTPException`` for any non-``all`` strategy when the feed can't
    be fetched or parsed — the caller (``add_sub``) MUST treat this as fatal
    and NOT append the subscription, otherwise the user thinks they chose
    ``new_only`` but the next poll would re-transcribe every historical episode
    (Codex v1.4.15 audit BUG 11).
    """
    if strategy == "all":
        # v1.5.4 Codex audit FAIL d: with the new daemon auto-protect, leaving
        # state.db empty here would cause the next poll to mark every episode
        # as ``backfill_skipped`` (= silently turn the user's "transcribe all"
        # choice into "skip all"). Write a ``pending`` row per current episode
        # so:
        #   * ``has_any_recorded_in`` returns True → auto-protect skips this sub
        #   * ``is_processed`` returns False on pending → daemon still picks
        #     them up and transcribes normally on next poll
        # Fetch the feed once to know what episodes exist; failure raises so
        # add_sub doesn't commit a yaml entry that would still get auto-marked
        # by the daemon.
        import feedparser

        try:
            feed = await asyncio.to_thread(feedparser.parse, rss_url)
        except Exception as e:
            logger.warning(
                "feedparser raised during all-strategy seed for {}: {}",
                rss_url,
                type(e).__name__,
            )
            raise HTTPException(
                status_code=502,
                detail=(f"无法获取 RSS feed（{type(e).__name__}）；订阅未保存，请稍后重试"),
            ) from e

        if getattr(feed, "bozo", 0) and not getattr(feed, "entries", None):
            reason = getattr(feed, "bozo_exception", "unknown parse error")
            raise HTTPException(
                status_code=502,
                detail=f"RSS feed 无法解析（{reason}）；订阅未保存，请检查 URL",
            )

        episodes = project_feed(feed)
        if episodes:
            config = load_config(CONFIG_PATH)
            state = await get_state_manager(config.db_path)
            for ep in episodes:
                await state.mark_status(
                    ep.guid,
                    "pending",
                    podcast_name=podcast_name,
                    title=ep.title,
                )
        return 0

    import feedparser

    # Code Review C1 (v1.4.15): feedparser.parse is synchronous and does its
    # own DNS + HTTP. Run it in a worker thread so the event loop stays
    # responsive (otherwise every SSE stream and health check stalls until
    # the feed times out).
    try:
        feed = await asyncio.to_thread(feedparser.parse, rss_url)
    except Exception as e:
        logger.warning("feedparser raised during backfill for {}: {}", rss_url, type(e).__name__)
        raise HTTPException(
            status_code=502,
            detail=f"无法获取 RSS feed（{type(e).__name__}）；订阅未保存，请稍后重试",
        ) from e

    # feedparser doesn't always raise on bad feeds — it sets bozo=1 and
    # leaves entries empty. Either way we have no episodes to mark, which
    # is indistinguishable from "feed temporarily down" and would silently
    # leave a subscription that re-transcribes everything on next poll.
    if getattr(feed, "bozo", 0) and not getattr(feed, "entries", None):
        reason = getattr(feed, "bozo_exception", "unknown parse error")
        raise HTTPException(
            status_code=502,
            detail=f"RSS feed 无法解析（{reason}）；订阅未保存，请检查 URL",
        )

    episodes = project_feed(feed)
    _, to_skip = filter_for_backfill(episodes, strategy, recent_n=recent_n, since_date=since_date)
    if not to_skip:
        return 0

    config = load_config(CONFIG_PATH)
    # v1.5.2: shared StateManager singleton (was per-call connection)
    state = await get_state_manager(config.db_path)
    return await state.mark_backfill_skipped([(e.guid, podcast_name, e.title) for e in to_skip])


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


@router.post("/subscriptions/preview")
async def preview_sub(payload: dict) -> dict:
    """Fetch the feed and project a per-episode + cost preview for the UI.

    v1.4.15: the missing piece before ``POST /api/subscriptions`` so users
    see exactly how many episodes a fresh subscription will burn quota on
    BEFORE committing. Returns:

        {
          "ok": true,
          "feed_title": "...",
          "episode_count": 23,
          "unprocessed_count": 23,          # not yet in state.db
          "total_duration_sec": 51840,       # sum of itunes:duration when available
          "estimated_cost_cny": 11.4,        # 0 if no duration info
          "asr_engine": "funasr",
          "episodes": [
            {"guid": "...", "title": "...", "pub_date": "2026-05-01", "duration_sec": 3600},
            ...
          ]
        }
    """
    url = (payload or {}).get("rss_url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="rss_url is required")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": f"不支持的协议: {parsed.scheme or '(空)'}"}
    if not parsed.hostname:
        return {"ok": False, "error": "URL 缺少主机名"}

    import feedparser

    # Code Review C1 (v1.4.15): wrap blocking feedparser.parse in to_thread
    # so a slow feed doesn't freeze the entire event loop (every SSE stream
    # and other endpoint would stall until the socket timeout).
    try:
        feed = await asyncio.to_thread(feedparser.parse, url)
    except Exception as e:
        logger.warning("preview rss fetch failed for {}: {}", url, type(e).__name__)
        return {"ok": False, "error": f"{type(e).__name__}"}

    if getattr(feed, "bozo", 0) and not feed.entries:
        reason = getattr(feed, "bozo_exception", None)
        return {"ok": False, "error": f"无法解析 RSS：{reason}"}

    episodes = project_feed(feed)

    # Cross-reference state.db to compute "unprocessed_count" (so the UI can
    # warn correctly even on a re-add of an existing subscription).
    unprocessed = len(episodes)
    try:
        config = load_config(CONFIG_PATH)
        # v1.5.2: shared singleton — no more per-preview connection churn
        state = await get_state_manager(config.db_path)
        unprocessed = 0
        for episode in episodes:
            if not await state.is_processed(episode.guid):
                unprocessed += 1
        asr_engine = config.asr_engine
    except Exception as e:
        # Don't fail the preview just because state.db / config is unavailable.
        # v1.5.4: full traceback (was just type name) so the next regression
        # like "TypeError out of nowhere" is debuggable from logs alone.
        logger.exception("preview state lookup failed: {}", type(e).__name__)
        asr_engine = "funasr"

    total_duration_sec = sum(e.duration_sec for e in episodes)
    missing_duration_count = sum(1 for e in episodes if e.duration_sec == 0)
    estimated_cost_cny = estimate_cost_cny(total_duration_sec, asr_engine)

    feed_title = ""
    if hasattr(feed.feed, "get"):
        feed_title = str(feed.feed.get("title", ""))
    return {
        "ok": True,
        "feed_title": feed_title,
        "episode_count": len(episodes),
        "unprocessed_count": unprocessed,
        "total_duration_sec": total_duration_sec,
        # v1.5.4: surface count of episodes without itunes:duration so the UI
        # can warn that the cost estimate is a lower bound (many Xiaoyuzhou
        # feeds omit duration → those episodes contribute 0 to total_sec).
        "missing_duration_count": missing_duration_count,
        "estimated_cost_cny": estimated_cost_cny,
        "asr_engine": asr_engine,
        "episodes": [e.to_dict() for e in episodes],
    }


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

        # v1.5.2 Code Review A1 fix: feedparser.parse is synchronous and
        # does DNS + HTTP — without to_thread it would freeze the event
        # loop for up to ~30s on a slow feed (same bug fixed for /preview
        # in v1.4.15 but was missed here).
        feed = await asyncio.to_thread(feedparser.parse, url)
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
    # SSRF guard (Codex v1.4.15 audit BUG 10): we hand rss_url to feedparser
    # which does its own HTTP fetch. Reject any non-http(s) scheme up front so
    # an attacker (or accidental paste) can't make us request file:// or
    # gopher:// URLs.
    parsed = urlparse(rss_url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail=f"rss_url 不支持的协议: {parsed.scheme or '(空)'}（只接受 http/https）",
        )
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="rss_url 缺少主机名")
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
