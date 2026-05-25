"""Unit tests for src.web.services.feed_preview (v1.4.15)."""

from __future__ import annotations

from types import SimpleNamespace

from src.web.services.feed_preview import (
    EpisodePreview,
    estimate_cost_cny,
    filter_for_backfill,
    project_feed,
)


def _entry(guid, title, pub, duration, has_audio=True):
    return SimpleNamespace(
        id=guid,
        link=guid,
        title=title,
        published=pub,
        enclosures=[{"href": f"https://x/{guid}.mp3"}] if has_audio else [],
        itunes_duration=str(duration) if duration else "",
    )


def _feed(*entries):
    return SimpleNamespace(entries=list(entries))


class TestProjectFeed:
    def test_basic(self):
        feed = _feed(
            _entry("g1", "Ep 1", "Mon, 01 May 2026 10:00:00 +0000", 3600),
            _entry("g2", "Ep 2", "Mon, 08 May 2026 10:00:00 +0000", "01:30:00"),
        )
        out = project_feed(feed)
        assert len(out) == 2
        assert out[0].guid == "g1"
        assert out[0].duration_sec == 3600
        assert out[1].duration_sec == 5400  # 1:30:00

    def test_skips_entries_without_audio(self):
        feed = _feed(
            _entry("g1", "no audio", "Mon, 01 May 2026 10:00:00 +0000", 0, has_audio=False),
            _entry("g2", "ok", "Mon, 08 May 2026 10:00:00 +0000", 600),
        )
        out = project_feed(feed)
        assert [e.guid for e in out] == ["g2"]

    def test_handles_unparseable_pub_date(self):
        feed = _feed(_entry("g1", "weird", "garbage", 60))
        out = project_feed(feed)
        assert out[0].pub_date == ""

    def test_parses_mmss_duration(self):
        feed = _feed(_entry("g1", "mmss", "Mon, 01 May 2026 10:00:00 +0000", "45:30"))
        out = project_feed(feed)
        assert out[0].duration_sec == 45 * 60 + 30


class TestEstimateCost:
    def test_zero_duration_zero_cost(self):
        assert estimate_cost_cny(0, "funasr") == 0.0

    def test_funasr_rate(self):
        cost = estimate_cost_cny(3600, "funasr")  # 60 min
        assert cost == round(60 * 0.0132, 2)

    def test_unknown_engine_falls_back_to_funasr(self):
        assert estimate_cost_cny(3600, "imaginary_engine") == estimate_cost_cny(3600, "funasr")


def _ep(guid, pub):
    return EpisodePreview(guid=guid, title=guid, pub_date=pub, duration_sec=600)


class TestFilterForBackfill:
    eps = [
        _ep("old", "2026-01-01"),
        _ep("mid", "2026-03-01"),
        _ep("new", "2026-05-01"),
    ]

    def test_all_processes_everything(self):
        process, skip = filter_for_backfill(self.eps, "all")
        assert len(process) == 3
        assert skip == []

    def test_new_only_skips_everything(self):
        process, skip = filter_for_backfill(self.eps, "new_only")
        assert process == []
        assert len(skip) == 3

    def test_recent_n_keeps_n_newest(self):
        process, skip = filter_for_backfill(self.eps, "recent_n", recent_n=2)
        process_guids = {e.guid for e in process}
        skip_guids = {e.guid for e in skip}
        assert process_guids == {"new", "mid"}
        assert skip_guids == {"old"}

    def test_recent_n_zero_skips_everything(self):
        process, skip = filter_for_backfill(self.eps, "recent_n", recent_n=0)
        assert process == []
        assert len(skip) == 3

    def test_since_date_inclusive_cutoff(self):
        process, skip = filter_for_backfill(self.eps, "since_date", since_date="2026-03-01")
        assert {e.guid for e in process} == {"mid", "new"}
        assert {e.guid for e in skip} == {"old"}

    def test_since_date_invalid_format_skips_all(self):
        process, skip = filter_for_backfill(self.eps, "since_date", since_date="not-a-date")
        assert process == []
        assert len(skip) == 3

    def test_unknown_strategy_is_conservative(self):
        process, skip = filter_for_backfill(self.eps, "yolo")
        assert process == []
        assert len(skip) == 3
