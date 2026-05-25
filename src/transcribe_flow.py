from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from dateutil import parser as dateutil_parser
from loguru import logger

from src.config import AppConfig
from src.models import Episode

ProgressCallback = Callable[[str, str, str], None]
"""(stage, status, message) — sync callback invoked at each pipeline stage.

stage:  one of resolve | subtitle_check | asr | summary | write
status: one of start | done | skipped | error
"""


@dataclass
class TranscribeOutcome:
    """Result of a single-URL transcribe run."""

    note_path: Path
    title: str
    podcast_name: str
    char_count: int
    paragraph_count: int
    elapsed_ms: int
    summary_failed: bool


def _emit(callback: ProgressCallback | None, stage: str, status: str, message: str = "") -> None:
    if callback is None:
        return
    try:
        callback(stage, status, message)
    except Exception as e:
        logger.warning("Progress callback raised: {}: {}", type(e).__name__, e)


_XIAOYUZHOU_HOSTS = frozenset({"www.xiaoyuzhoufm.com", "xiaoyuzhoufm.com"})


def _is_xiaoyuzhou_episode_url(url: str) -> bool:
    """Strict host + path check to prevent SSRF via substring spoofing.

    A URL like ``http://attacker/xiaoyuzhoufm.com/episode/x`` must be rejected.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except (TypeError, ValueError):
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.hostname not in _XIAOYUZHOU_HOSTS:
        return False
    return parsed.path.startswith("/episode/")


async def _resolve_episode_url(
    url: str,
) -> tuple[str, str | None, str | None, str, str | None]:
    """If URL is a Xiaoyuzhou episode page, extract audio URL and metadata.

    Returns:
        (audio_url, title, podcast_name, link, date_published)
    """
    import json
    import re

    import httpx

    if not _is_xiaoyuzhou_episode_url(url):
        return url, None, None, "", None

    logger.info("Detected Xiaoyuzhou episode URL, parsing metadata...")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    match = re.search(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.+?)</script>',
        resp.text,
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"Cannot parse metadata from Xiaoyuzhou page: {url}")

    data = json.loads(match.group(1))
    audio_url = data.get("associatedMedia", {}).get("contentUrl", "")
    ep_title = data.get("name")
    ep_podcast = data.get("partOfSeries", {}).get("name")
    date_published = data.get("datePublished")

    if not audio_url:
        raise ValueError(f"Cannot extract audio URL from Xiaoyuzhou page: {url}")

    logger.info("Parsed: {} — {}", ep_podcast, ep_title)
    return audio_url, ep_title, ep_podcast, url, date_published


async def preview_episode(url: str) -> dict:
    """Lightweight metadata fetch used by the GUI before user clicks 转录.

    Returns a dict with: title, podcast_name, link, date_published, audio_url, source.
    For non-Xiaoyuzhou URLs the dict will only have audio_url set.
    """
    audio_url, title, podcast, link, date_pub = await _resolve_episode_url(url)
    return {
        "audio_url": audio_url,
        "title": title,
        "podcast_name": podcast,
        "link": link,
        "date_published": date_pub,
        "source": "xiaoyuzhou" if "xiaoyuzhoufm.com" in url else "direct",
    }


async def transcribe_single_url(
    audio_url: str,
    config: AppConfig,
    *,
    title: str | None = None,
    podcast_name: str = "单独转录",
    progress_callback: ProgressCallback | None = None,
) -> TranscribeOutcome:
    """End-to-end transcribe of a single audio/episode URL.

    Shared by the CLI ``transcribe`` command and the Web ``POST /api/transcribe`` route.
    Emits 5 fixed stages via ``progress_callback`` (resolve / subtitle_check / asr / summary
    / write).

    v1.5.0: the actual ASR / summary / render / write work is delegated to
    :class:`EpisodeProcessor`. This function is now responsible only for the
    *single-URL-specific* concerns: URL resolution, title fallback, building
    the synthetic Episode, and packaging the outcome. The v1.4.16 audit
    duplication between this file and ``pipeline.py`` is finally gone.

    Raises:
        Any exception from the transcriber, summarizer (only summary failure
        is swallowed), or writer. The corresponding stage will emit an
        ``error`` event before propagating.
    """
    from src.episode_processor import EpisodeProcessor, ProcessingOptions
    from src.monitor.state import StateManager

    started_at = time.monotonic()

    # Stage 1: resolve URL & metadata (single-URL-specific — no equivalent
    # in the daemon path, where RSSChecker hands us a fully-built Episode).
    _emit(progress_callback, "resolve", "start", "解析剧集信息...")
    try:
        resolved_url, ep_title, ep_podcast, link, date_pub = await _resolve_episode_url(audio_url)
    except Exception as e:
        _emit(progress_callback, "resolve", "error", f"解析失败: {e}")
        raise
    if not title and ep_title:
        title = ep_title
    if podcast_name == "单独转录" and ep_podcast:
        podcast_name = ep_podcast
    _emit(progress_callback, "resolve", "done", title or "")

    # Title fallback when not provided and not auto-detected
    if not title:
        path = urlparse(resolved_url).path
        title = unquote(path.split("/")[-1]).rsplit(".", 1)[0] or "untitled"

    pub_date = datetime.now()
    if date_pub:
        with contextlib.suppress(ValueError, TypeError):
            pub_date = dateutil_parser.parse(date_pub)

    episode = Episode(
        guid=resolved_url,
        title=title,
        podcast_name=podcast_name,
        pub_date=pub_date,
        audio_url=resolved_url,
        duration="",
        show_notes="",
        link=link,
    )

    # Build a transient StateManager so mark_status calls inside the
    # processor land in the right db. Single-URL transcribes are rare events
    # (user-triggered), so opening + closing per call is fine.
    state = StateManager(config.db_path)
    try:
        await state.init()
    except Exception as e:
        # state.db unavailable shouldn't break the user's transcribe; build a
        # stub that no-ops mark_status calls.
        logger.warning("state.db unavailable, state writes disabled: {}", e)
        state = _NullState()

    try:
        processor = EpisodeProcessor.from_config(config, state)
        # Single-URL flow: user explicitly asked for fresh work, so don't
        # short-circuit on shared cache fetch (would silently serve a stale
        # peer-uploaded note). DO upload our result for peers to benefit.
        # Skip MCP dedup — user is explicitly transcribing one specific URL.
        options = ProcessingOptions(
            use_shared_cache_fetch=False,
            use_shared_cache_upload=True,
            do_mcp_dedup=False,
            save_pending_on_summary_fail=True,
        )
        outcome = await processor.process(
            episode, progress_callback=progress_callback, options=options
        )
    finally:
        if hasattr(state, "close"):
            with contextlib.suppress(Exception):
                await state.close()

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    return TranscribeOutcome(
        note_path=outcome.note_path,
        title=title,
        podcast_name=podcast_name,
        char_count=outcome.char_count,
        paragraph_count=outcome.paragraph_count,
        elapsed_ms=elapsed_ms,
        summary_failed=outcome.summary_failed,
    )


class _NullState:
    """Stub StateManager-shaped object used when state.db can't be opened —
    keeps EpisodeProcessor happy without polluting it with optional handling.
    Every method is an async no-op. Single-URL transcribes still complete,
    they just don't appear on the history page."""

    async def init(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def mark_status(self, *args, **kwargs) -> None:
        pass

    async def is_processed(self, *args, **kwargs) -> bool:
        return False

    async def get_all(self):
        return []

    async def get_failed(self, *args, **kwargs):
        return []

    async def mark_backfill_skipped(self, items) -> int:
        return 0
