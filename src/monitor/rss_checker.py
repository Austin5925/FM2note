from __future__ import annotations

import asyncio

import feedparser
import httpx
from dateutil import parser as dateutil_parser
from loguru import logger

from src.config import Subscription
from src.models import Episode
from src.monitor.state import StateManager


class RSSChecker:
    """RSS 轮询检查器，检测新播客剧集"""

    def __init__(self, subscriptions: list[Subscription], state: StateManager):
        self._subscriptions = subscriptions
        self._state = state

    async def check_all(self) -> list[Episode]:
        """检查所有订阅的 RSS feed，返回未处理的新剧集列表。

        Returns:
            按 pub_date 排序的新剧集列表
        """
        new_episodes: list[Episode] = []

        for sub in self._subscriptions:
            try:
                episodes = await self._check_feed(sub)
                new_episodes.extend(episodes)
            except Exception as e:
                logger.error("检查 RSS feed 失败: {} — {}", sub.name, e)

        new_episodes.sort(key=lambda ep: ep.pub_date)
        logger.info("发现 {} 个新剧集", len(new_episodes))
        return new_episodes

    async def _check_feed(self, sub: Subscription) -> list[Episode]:
        """Check a single RSS feed, return unprocessed episodes."""
        feed = await self._fetch_feed(sub.rss_url)
        episodes = []

        for entry in feed.entries:
            episode = self._parse_episode(entry, sub.name, sub.tags)
            if not episode.audio_url:
                logger.debug(
                    "Skipping entry without audio: {} — {}",
                    sub.name,
                    getattr(entry, "title", "?"),
                )
                continue
            if not await self._state.is_processed(episode.guid):
                episodes.append(episode)

        return episodes

    async def _fetch_feed(self, url: str) -> feedparser.FeedParserDict:
        """获取并解析 RSS feed，带重试"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return feedparser.parse(resp.text)
            except (httpx.HTTPError, Exception) as e:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** (attempt + 1)
                logger.warning(
                    "RSS 获取失败 (重试 {}/{}): {} — {}",
                    attempt + 1,
                    max_retries,
                    url,
                    e,
                )
                await asyncio.sleep(wait)
        raise RuntimeError("unreachable")

    def _parse_episode(self, entry, podcast_name: str, tags: list[str]) -> Episode | None:
        """Parse a feedparser entry into an Episode.

        Compatible with RSS 2.0, Atom, and iTunes podcast feeds.
        Returns None if the entry has no audio (no enclosure).
        """
        # Audio URL — required for processing
        audio_url = ""
        if hasattr(entry, "enclosures") and entry.enclosures:
            audio_url = entry.enclosures[0].get("href", "")

        # Published date — try multiple fields for Atom/RSS compat
        pub_date_str = getattr(entry, "published", "") or getattr(entry, "updated", "")
        try:
            pub_date = dateutil_parser.parse(pub_date_str)
        except (ValueError, TypeError):
            from datetime import datetime

            pub_date = datetime.now()

        # Show notes — try summary first, then content (Atom)
        show_notes = ""
        if hasattr(entry, "summary") and entry.summary:
            show_notes = entry.summary
        elif hasattr(entry, "content") and entry.content:
            show_notes = entry.content[0].get("value", "")

        # Duration — iTunes extension, may not exist
        duration = getattr(entry, "itunes_duration", "") or ""

        # GUID — fall back to link, then title hash
        guid = getattr(entry, "id", "") or getattr(entry, "link", "")
        if not guid:
            # Last resort: use title as guid
            guid = f"no-guid-{getattr(entry, 'title', 'unknown')}"

        # Link
        link = getattr(entry, "link", "") or ""

        # Title
        title = getattr(entry, "title", "") or "Untitled"

        # Subtitle detection
        subtitle_url = self._detect_subtitle(entry)

        return Episode(
            guid=guid,
            title=title,
            podcast_name=podcast_name,
            pub_date=pub_date,
            audio_url=audio_url,
            duration=duration,
            show_notes=show_notes,
            link=link,
            tags=tags,
            subtitle_url=subtitle_url,
        )

    def _detect_subtitle(self, entry) -> str | None:
        """检测 RSS entry 中的字幕链接。

        检查 podcast:transcript 标签和其他已知的字幕扩展字段。
        """
        # podcast:transcript 标签（Podcasting 2.0 标准）
        transcripts = getattr(entry, "podcast_transcript", None)
        if transcripts:
            if isinstance(transcripts, list):
                for t in transcripts:
                    url = t.get("url", "") if isinstance(t, dict) else ""
                    if url:
                        logger.info("发现内置字幕: {}", url)
                        return url
            elif isinstance(transcripts, dict) and transcripts.get("url"):
                logger.info("发现内置字幕: {}", transcripts["url"])
                return transcripts["url"]

        # 其他常见字幕字段
        for attr in ("transcript_url", "subtitle_url"):
            val = getattr(entry, attr, None)
            if val:
                logger.info("发现内置字幕 ({}): {}", attr, val)
                return val

        return None
