from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from loguru import logger

from src.web.paths import SUBSCRIPTIONS_PATH

_XIAOYUZHOU_HOSTS = frozenset({"www.xiaoyuzhoufm.com", "xiaoyuzhoufm.com"})
_RSSHUB_XIAOYUZHOU_ROUTE = "/xiaoyuzhou/podcast/"
_HTTP_URL_RE = re.compile(r"https?://[^\s<>'\"）)]+", re.IGNORECASE)
_RSSHUB_COMMENT_RE = re.compile(r"^\s*#\s*RSSHub:\s*(?P<base>\S+)\s*$", re.MULTILINE)
_RSS_URL_RE = re.compile(r"rss_url:\s*[\"']?(?P<url>https?://[^\"'\s]+)")
_PODCAST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,}$")
_PODCAST_PATH_RE = re.compile(r"/podcast/(?P<id>[A-Za-z0-9][A-Za-z0-9_-]*)")
_PERSONAL_RSSHUB_BASE = "https://macroclaw.app/rsshub"
_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(?P<body>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def detect_rsshub_base(path: str = SUBSCRIPTIONS_PATH) -> str:
    """Infer the current RSSHub base URL from env or existing subscriptions."""
    env_base = _clean_base(os.environ.get("FM2NOTE_RSSHUB_BASE", ""))
    if env_base:
        return env_base

    sub_path = Path(path)
    if not sub_path.exists():
        return _PERSONAL_RSSHUB_BASE

    try:
        text = sub_path.read_text(encoding="utf-8")
    except OSError:
        return _PERSONAL_RSSHUB_BASE

    comment_match = _RSSHUB_COMMENT_RE.search(text)
    if comment_match:
        base = _clean_base(comment_match.group("base"))
        if base:
            return base

    for match in _RSS_URL_RE.finditer(text):
        split = split_rsshub_podcast_url(match.group("url"))
        if split:
            return split[0]

    return _PERSONAL_RSSHUB_BASE


async def resolve_subscription_input(input_text: str, rsshub_base: str = "") -> dict[str, Any]:
    """Resolve pasted user input into a subscription draft.

    Supports:
    - Xiaoyuzhou podcast URLs
    - Xiaoyuzhou episode URLs (best-effort series extraction)
    - Existing RSSHub Xiaoyuzhou RSS URLs
    - Standard RSS/Atom feed URLs
    - Raw Xiaoyuzhou podcast IDs when an RSSHub base is available
    """
    candidate = extract_candidate_url(input_text)
    base = _clean_base(rsshub_base) or detect_rsshub_base()

    if _PODCAST_ID_RE.fullmatch(candidate):
        if not base:
            return _missing_rsshub_base()
        return await _xiaoyuzhou_result(candidate, base, fallback_name=f"小宇宙 {candidate}")

    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"ok": False, "error": "请粘贴有效的 http(s) 播客链接或 RSS 地址"}

    existing_rsshub = split_rsshub_podcast_url(candidate)
    if existing_rsshub:
        existing_base, podcast_id = existing_rsshub
        return await _xiaoyuzhou_result(
            podcast_id,
            existing_base,
            rss_url=candidate,
            fallback_name=f"小宇宙 {podcast_id}",
        )

    hostname = parsed.hostname.lower()
    if hostname in _XIAOYUZHOU_HOSTS:
        podcast_id = _podcast_id_from_path(parsed.path)
        fallback_name = f"小宇宙 {podcast_id}" if podcast_id else "小宇宙播客"
        if not podcast_id and parsed.path.startswith("/episode/"):
            page = await _fetch_xiaoyuzhou_html(candidate)
            podcast_id, episode_name = _extract_xiaoyuzhou_series(page)
            fallback_name = episode_name or fallback_name
        if not podcast_id:
            return {"ok": False, "error": "小宇宙链接请粘贴播客主页或剧集页"}
        if not base:
            return _missing_rsshub_base()
        return await _xiaoyuzhou_result(podcast_id, base, fallback_name=fallback_name)

    title = await probe_feed_title(candidate)
    return {
        "ok": True,
        "kind": "rss",
        "name": title or _fallback_name_from_url(candidate),
        "rss_url": candidate,
        "rsshub_base": base,
        "message": "已识别为标准 RSS/Atom feed",
    }


def extract_candidate_url(text: str) -> str:
    raw = str(text or "").strip()
    match = _HTTP_URL_RE.search(raw)
    candidate = match.group(0) if match else raw
    candidate = candidate.strip().strip("<>\"'").rstrip(".,，。;；)")
    if not candidate:
        return ""

    parsed = urlparse(candidate)
    if not parsed.scheme:
        lowered = candidate.lower()
        if (
            lowered.startswith(("www.xiaoyuzhoufm.com/", "xiaoyuzhoufm.com/"))
            or "." in candidate.split("/", 1)[0]
        ):
            candidate = "https://" + candidate
    return candidate


def split_rsshub_podcast_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    path = parsed.path.rstrip("/")
    marker_idx = path.find(_RSSHUB_XIAOYUZHOU_ROUTE)
    if marker_idx < 0:
        return None
    podcast_id = path[marker_idx + len(_RSSHUB_XIAOYUZHOU_ROUTE) :].split("/", 1)[0]
    if not _PODCAST_ID_RE.fullmatch(podcast_id):
        return None
    base_path = path[:marker_idx]
    base = urlunparse((parsed.scheme, parsed.netloc, base_path, "", "", "")).rstrip("/")
    return base, podcast_id


async def probe_feed_title(url: str) -> str:
    try:
        import feedparser

        feed = await asyncio.to_thread(feedparser.parse, url)
    except Exception as e:
        logger.warning("subscription feed title probe failed for {}: {}", url, type(e).__name__)
        return ""

    feed_obj = getattr(feed, "feed", {})
    title = feed_obj.get("title", "") if hasattr(feed_obj, "get") else ""
    return str(title or "").strip()


async def _xiaoyuzhou_result(
    podcast_id: str,
    rsshub_base: str,
    *,
    rss_url: str | None = None,
    fallback_name: str,
) -> dict[str, Any]:
    final_url = rss_url or f"{rsshub_base.rstrip('/')}{_RSSHUB_XIAOYUZHOU_ROUTE}{podcast_id}"
    title = await probe_feed_title(final_url)
    return {
        "ok": True,
        "kind": "xiaoyuzhou",
        "name": title or fallback_name,
        "rss_url": final_url,
        "rsshub_base": rsshub_base,
        "podcast_id": podcast_id,
        "message": "已识别小宇宙播客，并转换为 RSSHub 订阅地址",
    }


async def _fetch_xiaoyuzhou_html(url: str) -> str:
    import httpx

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def _extract_xiaoyuzhou_series(html: str) -> tuple[str, str]:
    series_name = ""
    for match in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(match.group("body"))
        except json.JSONDecodeError:
            continue
        for node in _walk_json(data):
            part = node.get("partOfSeries")
            if isinstance(part, dict):
                series_name = str(part.get("name") or series_name)
                podcast_id = _podcast_id_from_url(str(part.get("url") or part.get("@id") or ""))
                if podcast_id:
                    return podcast_id, series_name
            podcast_id = _podcast_id_from_url(str(node.get("url") or node.get("@id") or ""))
            if podcast_id:
                return podcast_id, series_name

    match = _PODCAST_PATH_RE.search(html)
    if match:
        return match.group("id"), series_name
    return "", series_name


def _walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


def _podcast_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    return _podcast_id_from_path(parsed.path)


def _podcast_id_from_path(path: str) -> str:
    match = _PODCAST_PATH_RE.search(path)
    if not match:
        return ""
    podcast_id = match.group("id")
    return podcast_id if _PODCAST_ID_RE.fullmatch(podcast_id) else ""


def _clean_base(base: str) -> str:
    candidate = str(base or "").strip().strip("<>\"'").rstrip("/")
    if not candidate:
        return ""
    if not urlparse(candidate).scheme and "." in candidate.split("/", 1)[0]:
        candidate = "https://" + candidate
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def _fallback_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    path_name = Path(parsed.path).name
    return path_name or parsed.hostname or "播客"


def _missing_rsshub_base() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "请先填写 RSSHub 网址。小宇宙播客需要通过你的 RSSHub 转成 RSS。",
    }
