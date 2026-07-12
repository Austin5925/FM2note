"""Shared helpers for previewing an RSS feed before subscribing.

Used by ``POST /api/subscriptions/preview`` to show the user how many
episodes a feed contains and how much it would cost to transcribe them all,
*before* committing to a backfill strategy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dateutil import parser as dateutil_parser

# Rough cost estimate per minute of audio, by ASR engine. Values are CNY
# unless otherwise noted; sources are the engines' own pricing pages.
# Kept conservative — when in doubt, round up to avoid lowballing the user.
_COST_CNY_PER_MIN = {
    "poe": 0.0,  # Existing subscription points: no incremental cash charge
    "funasr": 0.0132,  # ~¥0.79/hour
    "paraformer": 0.0048,  # ~¥0.29/hour
    "bailian": 0.0132,
    "tingwu": 0.05,  # ~¥3/hour
    "whisper_api": 0.045,  # ~$0.006/min × ~7.5 RMB/USD
}


@dataclass
class EpisodePreview:
    """A single feed entry projected for the preview UI."""

    guid: str
    title: str
    pub_date: str  # ISO date YYYY-MM-DD ("" if unparseable)
    duration_sec: int  # 0 if the feed didn't include itunes:duration

    def to_dict(self) -> dict:
        return {
            "guid": self.guid,
            "title": self.title,
            "pub_date": self.pub_date,
            "duration_sec": self.duration_sec,
        }


def _parse_itunes_duration(raw: str) -> int:
    """Parse an itunes:duration value into seconds.

    Accepts the three common forms: ``HH:MM:SS``, ``MM:SS``, or a bare integer
    (seconds). Returns 0 on parse failure — the UI should treat 0 as "unknown".
    """
    if not raw:
        return 0
    raw = str(raw).strip()
    if not raw:
        return 0
    # Bare integer (seconds)
    if raw.isdigit():
        return int(raw)
    # H:M:S or M:S
    if re.fullmatch(r"\d{1,3}(:\d{1,2}){1,2}", raw):
        parts = [int(p) for p in raw.split(":")]
        if len(parts) == 2:
            m, s = parts
            return m * 60 + s
        if len(parts) == 3:
            h, m, s = parts
            return h * 3600 + m * 60 + s
    return 0


def _parse_pub_date(raw: str) -> str:
    """Return an ISO date string (YYYY-MM-DD) or "" on failure."""
    if not raw:
        return ""
    try:
        return dateutil_parser.parse(raw).date().isoformat()
    except (ValueError, TypeError):
        return ""


def _entry_guid(entry: Any) -> str:
    guid = getattr(entry, "id", "") or getattr(entry, "link", "")
    if guid:
        return str(guid)
    return f"no-guid-{getattr(entry, 'title', 'unknown')}"


def project_feed(feed: Any) -> list[EpisodePreview]:
    """Convert a feedparser result into a list of ``EpisodePreview``.

    Skips entries without an enclosure (no audio = nothing to transcribe).
    """
    out: list[EpisodePreview] = []
    for entry in getattr(feed, "entries", []) or []:
        enclosures = getattr(entry, "enclosures", None) or []
        if not enclosures or not enclosures[0].get("href"):
            continue
        out.append(
            EpisodePreview(
                guid=_entry_guid(entry),
                title=str(getattr(entry, "title", "") or "Untitled"),
                pub_date=_parse_pub_date(
                    getattr(entry, "published", "") or getattr(entry, "updated", "")
                ),
                duration_sec=_parse_itunes_duration(getattr(entry, "itunes_duration", "") or ""),
            )
        )
    return out


def estimate_cost_cny(total_sec: int, asr_engine: str) -> float:
    """Cheap multiplier — returns CNY. Conservative for unknown engines.

    Total seconds × per-minute rate. Returns 0.0 if total_sec is 0 (we don't
    fabricate a cost from nothing — the UI can fall back to a per-episode
    placeholder if it wants).
    """
    if total_sec <= 0:
        return 0.0
    rate = _COST_CNY_PER_MIN.get(asr_engine, _COST_CNY_PER_MIN["funasr"])
    return round(total_sec / 60 * rate, 2)


def filter_for_backfill(
    episodes: list[EpisodePreview],
    strategy: str,
    *,
    recent_n: int | None = None,
    since_date: str | None = None,
) -> tuple[list[EpisodePreview], list[EpisodePreview]]:
    """Split episodes into (to_process, to_skip) according to backfill strategy.

    Strategies:
      * ``all`` — process everything (skip nothing).
      * ``new_only`` — skip everything currently in the feed; only future
        episodes will be picked up by the next poll.
      * ``recent_n`` — keep the N newest, skip the rest. ``recent_n`` required.
      * ``since_date`` — keep episodes published on or after the date, skip
        the rest. ``since_date`` required as YYYY-MM-DD.

    Unknown strategies fall back to ``new_only`` — the safest default
    (worst case: user manually transcribes via the single-URL flow).
    """
    if strategy == "all":
        return list(episodes), []
    if strategy == "new_only":
        return [], list(episodes)
    if strategy == "recent_n":
        n = max(0, int(recent_n or 0))
        # Sort newest first by pub_date; entries with "" pub_date go last
        sorted_eps = sorted(
            episodes,
            key=lambda e: e.pub_date or "0000-00-00",
            reverse=True,
        )
        return sorted_eps[:n], sorted_eps[n:]
    if strategy == "since_date":
        if not since_date:
            return [], list(episodes)
        try:
            cutoff = datetime.fromisoformat(since_date).date().isoformat()
        except (ValueError, TypeError):
            return [], list(episodes)
        to_process = [e for e in episodes if e.pub_date and e.pub_date >= cutoff]
        to_skip = [e for e in episodes if not (e.pub_date and e.pub_date >= cutoff)]
        return to_process, to_skip
    # Unknown — be conservative
    return [], list(episodes)
