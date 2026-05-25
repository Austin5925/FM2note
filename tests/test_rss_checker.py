from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Subscription
from src.monitor.rss_checker import RSSChecker


def _make_entry(
    title="测试节目",
    audio_url="https://example.com/audio.mp3",
    published="2025-01-15T10:00:00Z",
    guid="test-guid",
    link="https://www.xiaoyuzhoufm.com/episode/test",
    summary="show notes",
    duration="01:00:00",
):
    entry = MagicMock()
    entry.title = title
    entry.enclosures = [{"href": audio_url}]
    entry.published = published
    entry.id = guid
    entry.link = link
    entry.summary = summary
    entry.itunes_duration = duration
    entry.content = []
    return entry


def _make_feed(*entries):
    feed = MagicMock()
    feed.entries = list(entries)
    return feed


@pytest.fixture
def mock_state():
    state = AsyncMock()
    state.is_processed = AsyncMock(return_value=False)
    return state


@pytest.fixture
def subscriptions():
    return [
        Subscription(name="测试播客", rss_url="http://localhost:1200/test", tags=["tech"]),
    ]


class TestRSSChecker:
    @pytest.mark.asyncio
    async def test_parse_episode(self, subscriptions, mock_state):
        checker = RSSChecker(subscriptions, mock_state)
        entry = _make_entry()
        ep = checker._parse_episode(entry, "测试播客", ["tech"])
        assert ep.guid == "test-guid"
        assert ep.title == "测试节目"
        assert ep.podcast_name == "测试播客"
        assert ep.audio_url == "https://example.com/audio.mp3"
        assert ep.tags == ["tech"]
        assert isinstance(ep.pub_date, datetime)

    @pytest.mark.asyncio
    async def test_parse_episode_no_enclosure(self, subscriptions, mock_state):
        checker = RSSChecker(subscriptions, mock_state)
        entry = _make_entry()
        entry.enclosures = []
        ep = checker._parse_episode(entry, "播客", [])
        assert ep.audio_url == ""

    @pytest.mark.asyncio
    async def test_check_all_filters_processed(self, subscriptions, mock_state):
        checker = RSSChecker(subscriptions, mock_state)

        feed = _make_feed(
            _make_entry(title="已处理", guid="old"),
            _make_entry(title="新节目", guid="new"),
        )

        # old 已处理，new 未处理
        async def is_processed(guid):
            return guid == "old"

        mock_state.is_processed = is_processed

        with patch.object(checker, "_fetch_feed", AsyncMock(return_value=feed)):
            episodes = await checker.check_all()

        assert len(episodes) == 1
        assert episodes[0].title == "新节目"

    @pytest.mark.asyncio
    async def test_check_all_sorts_by_date(self, subscriptions, mock_state):
        checker = RSSChecker(subscriptions, mock_state)

        feed = _make_feed(
            _make_entry(title="后发布", guid="g2", published="2025-01-20T10:00:00Z"),
            _make_entry(title="先发布", guid="g1", published="2025-01-10T10:00:00Z"),
        )

        with patch.object(checker, "_fetch_feed", AsyncMock(return_value=feed)):
            episodes = await checker.check_all()

        assert len(episodes) == 2
        assert episodes[0].title == "先发布"
        assert episodes[1].title == "后发布"

    @pytest.mark.asyncio
    async def test_check_all_handles_feed_error(self, mock_state):
        subs = [
            Subscription(name="正常", rss_url="http://ok", tags=[]),
            Subscription(name="异常", rss_url="http://fail", tags=[]),
        ]
        checker = RSSChecker(subs, mock_state)

        async def mock_fetch(url):
            if "fail" in url:
                raise Exception("网络错误")
            return _make_feed(_make_entry(guid="good"))

        with patch.object(checker, "_fetch_feed", side_effect=mock_fetch):
            episodes = await checker.check_all()

        # 只返回正常 feed 的剧集
        assert len(episodes) == 1

    @pytest.mark.asyncio
    async def test_subs_provider_hot_reload(self, mock_state):
        """v1.4.15 — when ``subs_provider`` is set, each ``check_all`` call
        re-reads the subscriptions list, so Web UI edits to subscriptions.yaml
        take effect on the next poll without restarting the daemon."""
        sub_a = Subscription(name="A", rss_url="http://a", tags=[])
        sub_b = Subscription(name="B", rss_url="http://b", tags=[])

        # Provider returns a list whose contents change between calls
        calls = {"n": 0}

        def provider():
            calls["n"] += 1
            return [sub_a] if calls["n"] == 1 else [sub_a, sub_b]

        checker = RSSChecker([sub_a], mock_state, subs_provider=provider)

        seen_urls: list[str] = []

        async def fake_fetch(url):
            seen_urls.append(url)
            return _make_feed()  # empty feed

        with patch.object(checker, "_fetch_feed", side_effect=fake_fetch):
            await checker.check_all()
            await checker.check_all()

        # First call sees just A; second call sees A + B (the new sub)
        assert seen_urls == ["http://a", "http://a", "http://b"]
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_subs_provider_failure_falls_back_to_previous(self, mock_state):
        """If the provider raises (e.g. yaml is being saved), the checker
        should reuse the last-known subscription list rather than crash."""
        sub_a = Subscription(name="A", rss_url="http://a", tags=[])

        def provider():
            raise RuntimeError("yaml locked")

        checker = RSSChecker([sub_a], mock_state, subs_provider=provider)

        with patch.object(checker, "_fetch_feed", AsyncMock(return_value=_make_feed())):
            # Must not raise — falls back to the constructor-time list
            episodes = await checker.check_all()
        assert episodes == []

    def test_detect_subtitle_none(self, subscriptions, mock_state):
        checker = RSSChecker(subscriptions, mock_state)
        entry = _make_entry()
        # 默认 MagicMock 的 podcast_transcript 为 MagicMock，需显式设为 None
        entry.podcast_transcript = None
        entry.transcript_url = None
        entry.subtitle_url = None
        assert checker._detect_subtitle(entry) is None

    def test_detect_subtitle_from_podcast_transcript(self, subscriptions, mock_state):
        checker = RSSChecker(subscriptions, mock_state)
        entry = _make_entry()
        entry.podcast_transcript = [{"url": "https://example.com/sub.srt", "type": "text/srt"}]
        entry.transcript_url = None
        entry.subtitle_url = None
        result = checker._detect_subtitle(entry)
        assert result == "https://example.com/sub.srt"

    def test_detect_subtitle_from_transcript_url(self, subscriptions, mock_state):
        checker = RSSChecker(subscriptions, mock_state)
        entry = _make_entry()
        entry.podcast_transcript = None
        entry.transcript_url = "https://example.com/transcript.vtt"
        entry.subtitle_url = None
        result = checker._detect_subtitle(entry)
        assert result == "https://example.com/transcript.vtt"

    def test_parse_episode_with_subtitle(self, subscriptions, mock_state):
        checker = RSSChecker(subscriptions, mock_state)
        entry = _make_entry()
        entry.podcast_transcript = [{"url": "https://example.com/sub.srt"}]
        entry.transcript_url = None
        entry.subtitle_url = None
        ep = checker._parse_episode(entry, "播客", [])
        assert ep.subtitle_url == "https://example.com/sub.srt"
