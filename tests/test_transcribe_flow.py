"""Tests for the shared transcribe_single_url flow.

External dependencies (transcriber / summarizer / writer / URL resolver) are
mocked so the test exercises stage ordering and callback invocation only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.config import AppConfig
from src.models import TranscriptResult
from src.transcribe_flow import (
    UnsupportedXiaoyuzhouUrlError,
    _is_xiaoyuzhou_episode_url,
    preview_episode,
    transcribe_single_url,
)


def test_xiaoyuzhou_host_check_rejects_substring_spoofing():
    """Must not accept URLs where ``xiaoyuzhoufm.com/episode/`` is just a substring."""
    # Genuine
    assert _is_xiaoyuzhou_episode_url("https://www.xiaoyuzhoufm.com/episode/abc123")
    assert _is_xiaoyuzhou_episode_url("https://xiaoyuzhoufm.com/episode/abc123")
    # Spoofing attempts that the old substring check would accept
    assert not _is_xiaoyuzhou_episode_url("http://attacker.com/xiaoyuzhoufm.com/episode/x")
    assert not _is_xiaoyuzhou_episode_url("http://xiaoyuzhoufm.com.attacker.com/episode/x")
    assert not _is_xiaoyuzhou_episode_url("file:///xiaoyuzhoufm.com/episode/x")
    # Non-episode paths on the real domain
    assert not _is_xiaoyuzhou_episode_url("https://www.xiaoyuzhoufm.com/podcast/x")
    # Garbage
    assert not _is_xiaoyuzhou_episode_url("")
    assert not _is_xiaoyuzhou_episode_url("not a url")


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        vault_path=str(tmp_path),
        podcast_dir="Podcasts",
        asr_engine="funasr",
        summary_provider="none",
        summary_model="",
        summary_cooldown=0,
        deepseek_api_key="",
        openai_api_key="",
        db_path=str(tmp_path / "state.db"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://www.xiaoyuzhoufm.com/podcast/61358d971c5d56efe5bcb5d2",
        "https://xiaoyuzhoufm.com/podcast/61358d971c5d56efe5bcb5d2?share=1",
        "https://www.xiaoyuzhoufm.com/",
        "https://www.xiaoyuzhoufm.com/user/example",
    ],
)
async def test_non_episode_xiaoyuzhou_page_never_reaches_asr(tmp_path, url):
    with (
        patch("httpx.AsyncClient") as http_client,
        patch("src.episode_processor.EpisodeProcessor.from_config") as processor,
        pytest.raises(UnsupportedXiaoyuzhouUrlError, match="单集链接"),
    ):
        await transcribe_single_url(url, _make_config(tmp_path))

    http_client.assert_not_called()
    processor.assert_not_called()
    assert not (tmp_path / "state.db").exists()


@pytest.mark.asyncio
async def test_episode_preview_resolves_real_audio_url():
    url = "https://www.xiaoyuzhoufm.com/episode/5f20d34e9504bbdb77b7681f"
    audio_url = "https://media.xyzcdn.net/podcast/episode.mp3"
    response = httpx.Response(
        200,
        request=httpx.Request("GET", url),
        text=(
            '<script type="application/ld+json">'
            '{"name":"单集标题","partOfSeries":{"name":"播客"},'
            f'"associatedMedia":{{"contentUrl":"{audio_url}"}}}}'
            "</script>"
        ),
    )
    with patch("httpx.AsyncClient") as http_client:
        http_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=response)
        result = await preview_episode(url)

    assert result["audio_url"] == audio_url
    assert result["title"] == "单集标题"
    assert result["source"] == "xiaoyuzhou"


@pytest.mark.asyncio
async def test_preview_source_uses_parsed_host_instead_of_substring():
    url = "https://example.com/audio/xiaoyuzhoufm.com.mp3"
    result = await preview_episode(url)
    assert result["audio_url"] == url
    assert result["source"] == "direct"


@pytest.mark.asyncio
async def test_emits_all_five_stages_no_summary(tmp_path):
    """When summarizer is None, stages must still emit in fixed order: skipped for summary."""
    config = _make_config(tmp_path)
    events: list[tuple[str, str]] = []

    def cb(stage, status, message):
        events.append((stage, status))

    fake_transcript = TranscriptResult(text="hello world", paragraphs=["hello world"])
    fake_transcriber = MagicMock()
    fake_transcriber.transcribe = AsyncMock(return_value=fake_transcript)

    fake_writer = MagicMock()
    fake_writer.write_note = MagicMock(return_value=tmp_path / "note.md")

    with (
        patch(
            "src.transcribe_flow._resolve_episode_url",
            AsyncMock(return_value=("http://audio.example/x.mp3", "Title", "Podcast", "", None)),
        ),
        patch("src.transcriber.factory.create_transcriber", return_value=fake_transcriber),
        patch("src.summarizer.factory.create_summarizer", return_value=None),
        patch("src.episode_processor.ObsidianWriter", return_value=fake_writer),
    ):
        outcome = await transcribe_single_url(
            "http://audio.example/x.mp3", config, progress_callback=cb
        )

    # Stage ordering — every stage appears at least once
    stages_seen = [s for s, _ in events]
    assert stages_seen[0] == "resolve"
    assert "subtitle_check" in stages_seen
    assert "asr" in stages_seen
    assert "summary" in stages_seen
    assert stages_seen[-1] == "write"

    # Summary skipped (no summarizer)
    assert ("summary", "skipped") in events

    # Outcome fields populated
    assert outcome.title == "Title"
    assert outcome.podcast_name == "Podcast"
    assert outcome.char_count == len("hello world")
    assert outcome.paragraph_count == 1
    assert outcome.summary_failed is False
    assert outcome.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_summary_error_does_not_abort(tmp_path):
    """If summary fails, the pipeline still writes the note and flags summary_failed."""
    config = _make_config(tmp_path)
    events: list[tuple[str, str]] = []

    def cb(stage, status, message):
        events.append((stage, status))

    fake_transcript = TranscriptResult(text="content", paragraphs=["content"])
    fake_transcriber = MagicMock()
    fake_transcriber.transcribe = AsyncMock(return_value=fake_transcript)

    fake_summarizer = MagicMock()
    fake_summarizer.summarize = AsyncMock(side_effect=RuntimeError("api down"))

    fake_writer = MagicMock()
    fake_writer.write_note = MagicMock(return_value=tmp_path / "note.md")

    with (
        patch(
            "src.transcribe_flow._resolve_episode_url",
            AsyncMock(return_value=("http://audio.example/x.mp3", "Title", "Podcast", "", None)),
        ),
        patch("src.transcriber.factory.create_transcriber", return_value=fake_transcriber),
        patch("src.summarizer.factory.create_summarizer", return_value=fake_summarizer),
        patch("src.episode_processor.ObsidianWriter", return_value=fake_writer),
        patch("src.summarizer.pending.save_pending"),
    ):
        outcome = await transcribe_single_url(
            "http://audio.example/x.mp3", config, progress_callback=cb
        )

    assert outcome.summary_failed is True
    assert ("summary", "error") in events
    assert ("write", "done") in events


@pytest.mark.asyncio
async def test_asr_failure_propagates_with_error_event(tmp_path):
    config = _make_config(tmp_path)
    events: list[tuple[str, str]] = []

    def cb(stage, status, message):
        events.append((stage, status))

    fake_transcriber = MagicMock()
    fake_transcriber.transcribe = AsyncMock(side_effect=RuntimeError("network"))

    with (
        patch(
            "src.transcribe_flow._resolve_episode_url",
            AsyncMock(return_value=("http://audio.example/x.mp3", None, None, "", None)),
        ),
        patch("src.transcriber.factory.create_transcriber", return_value=fake_transcriber),
        pytest.raises(RuntimeError, match="network"),
    ):
        await transcribe_single_url("http://audio.example/x.mp3", config, progress_callback=cb)

    assert ("asr", "error") in events
    assert ("write", "done") not in events
    with sqlite3.connect(config.db_path) as db:
        row = db.execute(
            "SELECT status,error_msg,retry_count FROM processed_episodes WHERE guid=?",
            ("http://audio.example/x.mp3",),
        ).fetchone()
    assert row == ("failed", "network", 1)


@pytest.mark.asyncio
async def test_failed_status_write_does_not_replace_transcription_error(tmp_path):
    from src.monitor.state import StateManager

    config = _make_config(tmp_path)
    mark_status = StateManager.mark_status

    async def fail_on_failed(self, guid, status, **kwargs):
        if status == "failed":
            raise OSError("database unavailable")
        return await mark_status(self, guid, status, **kwargs)

    fake_transcriber = MagicMock()
    fake_transcriber.transcribe = AsyncMock(side_effect=RuntimeError("original ASR failure"))
    with (
        patch.object(StateManager, "mark_status", fail_on_failed),
        patch("src.transcriber.factory.create_transcriber", return_value=fake_transcriber),
        patch("src.summarizer.factory.create_summarizer", return_value=None),
        pytest.raises(RuntimeError, match="original ASR failure"),
    ):
        await transcribe_single_url("https://example.com/audio.mp3", config)


@pytest.mark.asyncio
async def test_progress_callback_exception_is_swallowed(tmp_path):
    """A buggy callback should never crash the pipeline."""
    config = _make_config(tmp_path)

    def cb(stage, status, message):
        raise ValueError("buggy callback")

    fake_transcript = TranscriptResult(text="ok", paragraphs=["ok"])
    fake_transcriber = MagicMock()
    fake_transcriber.transcribe = AsyncMock(return_value=fake_transcript)
    fake_writer = MagicMock()
    fake_writer.write_note = MagicMock(return_value=tmp_path / "note.md")

    with (
        patch(
            "src.transcribe_flow._resolve_episode_url",
            AsyncMock(return_value=("http://audio.example/x.mp3", "T", "P", "", None)),
        ),
        patch("src.transcriber.factory.create_transcriber", return_value=fake_transcriber),
        patch("src.summarizer.factory.create_summarizer", return_value=None),
        patch("src.episode_processor.ObsidianWriter", return_value=fake_writer),
    ):
        outcome = await transcribe_single_url(
            "http://audio.example/x.mp3", config, progress_callback=cb
        )

    assert outcome.title == "T"
