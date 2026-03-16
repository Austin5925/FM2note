"""Tests for generic RSS/Atom feed parsing compatibility."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import Subscription
from src.monitor.rss_checker import RSSChecker


def _make_entry(**kwargs):
    """Create a mock feedparser entry with given fields."""
    entry = MagicMock()
    # Set defaults that simulate a minimal RSS entry
    entry.title = kwargs.get("title", "Test Episode")
    entry.published = kwargs.get("published", "2025-01-15T10:00:00Z")
    entry.updated = kwargs.get("updated", "")
    entry.id = kwargs.get("id", "test-guid")
    entry.link = kwargs.get("link", "https://example.com/ep1")
    entry.summary = kwargs.get("summary", "")
    entry.content = kwargs.get("content", [])
    entry.itunes_duration = kwargs.get("itunes_duration", "")
    entry.podcast_transcript = kwargs.get("podcast_transcript")
    entry.transcript_url = kwargs.get("transcript_url")
    entry.subtitle_url = kwargs.get("subtitle_url")

    # Enclosures
    if "enclosures" in kwargs:
        entry.enclosures = kwargs["enclosures"]
    elif "audio_url" in kwargs:
        entry.enclosures = [{"href": kwargs["audio_url"]}]
    else:
        entry.enclosures = [{"href": "https://example.com/audio.mp3"}]

    # For fields not provided, make getattr return the default
    # This simulates feedparser where missing fields don't exist as attributes
    for attr in ("podcast_transcript", "transcript_url", "subtitle_url"):
        if attr not in kwargs:
            setattr(entry, attr, None)

    return entry


@pytest.fixture
def checker():
    state = AsyncMock()
    state.is_processed = AsyncMock(return_value=False)
    subs = [Subscription(name="Test", rss_url="http://example.com/rss", tags=[])]
    return RSSChecker(subs, state)


class TestStandardRSSParsing:
    """Test RSS 2.0 standard feed parsing."""

    def test_standard_rss_entry(self, checker):
        """Standard RSS entry with all fields."""
        entry = _make_entry(
            title="My Episode",
            audio_url="https://cdn.example.com/ep1.mp3",
            published="Mon, 15 Jan 2025 10:00:00 GMT",
            id="https://example.com/ep1",
            link="https://example.com/ep1",
            summary="<p>Episode description</p>",
            itunes_duration="3600",
        )
        ep = checker._parse_episode(entry, "My Podcast", ["tech"])
        assert ep.title == "My Episode"
        assert ep.audio_url == "https://cdn.example.com/ep1.mp3"
        assert ep.guid == "https://example.com/ep1"
        assert ep.duration == "3600"
        assert ep.show_notes == "<p>Episode description</p>"

    def test_minimal_rss_entry(self, checker):
        """RSS entry with only required fields (title + enclosure)."""
        entry = _make_entry(
            title="Bare Minimum",
            audio_url="https://cdn.example.com/ep.mp3",
            published="",
            id="",
            link="",
            summary="",
            itunes_duration="",
        )
        entry.updated = ""
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.title == "Bare Minimum"
        assert ep.audio_url == "https://cdn.example.com/ep.mp3"
        assert ep.guid.startswith("no-guid-")  # fallback guid
        assert isinstance(ep.pub_date, datetime)  # fallback to now
        assert ep.duration == ""
        assert ep.link == ""

    def test_no_enclosure(self, checker):
        """Entry without enclosure (text-only podcast, should have empty audio_url)."""
        entry = _make_entry(enclosures=[])
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.audio_url == ""

    def test_no_enclosures_attr(self, checker):
        """Entry where enclosures attribute doesn't exist."""
        entry = _make_entry()
        del entry.enclosures
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.audio_url == ""


class TestAtomFeedParsing:
    """Test Atom feed compatibility (feedparser normalizes most fields)."""

    def test_atom_entry_with_updated(self, checker):
        """Atom uses 'updated' instead of 'published'."""
        entry = _make_entry(
            published="",
            updated="2025-03-01T12:00:00Z",
        )
        ep = checker._parse_episode(entry, "Atom Podcast", [])
        assert ep.pub_date.year == 2025
        assert ep.pub_date.month == 3

    def test_atom_content_field(self, checker):
        """Atom uses content instead of summary."""
        entry = _make_entry(summary="", content=[{"value": "<p>Atom content</p>"}])
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.show_notes == "<p>Atom content</p>"


class TestITunesPodcastFields:
    """Test iTunes podcast extension fields."""

    def test_itunes_duration_hhmmss(self, checker):
        """iTunes duration in HH:MM:SS format."""
        entry = _make_entry(itunes_duration="01:23:45")
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.duration == "01:23:45"

    def test_itunes_duration_seconds(self, checker):
        """iTunes duration as raw seconds."""
        entry = _make_entry(itunes_duration="5025")
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.duration == "5025"

    def test_no_itunes_duration(self, checker):
        """No iTunes duration field."""
        entry = _make_entry(itunes_duration="")
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.duration == ""


class TestGuidFallback:
    """Test GUID resolution with various fallback strategies."""

    def test_guid_from_id(self, checker):
        entry = _make_entry(id="urn:uuid:12345", link="https://example.com/ep")
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.guid == "urn:uuid:12345"

    def test_guid_fallback_to_link(self, checker):
        entry = _make_entry(id="", link="https://example.com/ep")
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.guid == "https://example.com/ep"

    def test_guid_fallback_to_title(self, checker):
        entry = _make_entry(id="", link="", title="Some Episode")
        ep = checker._parse_episode(entry, "Podcast", [])
        assert ep.guid == "no-guid-Some Episode"


class TestCheckFeedSkipsNoAudio:
    """Test that _check_feed skips entries without audio."""

    @pytest.mark.asyncio
    async def test_skip_entries_without_audio(self):
        state = AsyncMock()
        state.is_processed = AsyncMock(return_value=False)
        sub = Subscription(name="Test", rss_url="http://example.com/rss", tags=[])
        checker = RSSChecker([sub], state)

        from unittest.mock import patch

        feed = MagicMock()
        feed.entries = [
            _make_entry(title="Has Audio", audio_url="https://cdn.example.com/ep.mp3"),
            _make_entry(title="No Audio", enclosures=[]),
        ]

        with patch.object(checker, "_fetch_feed", AsyncMock(return_value=feed)):
            episodes = await checker._check_feed(sub)

        assert len(episodes) == 1
        assert episodes[0].title == "Has Audio"
