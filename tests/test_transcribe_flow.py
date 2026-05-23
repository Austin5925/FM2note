"""Tests for the shared transcribe_single_url flow.

External dependencies (transcriber / summarizer / writer / URL resolver) are
mocked so the test exercises stage ordering and callback invocation only.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import AppConfig
from src.models import TranscriptResult
from src.transcribe_flow import transcribe_single_url


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        vault_path=str(tmp_path),
        podcast_dir="Podcasts",
        asr_engine="funasr",
        summary_provider="none",
        summary_model="",
        summary_cooldown=0,
        poe_api_key="",
        openai_api_key="",
    )


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
        patch("src.writer.obsidian.ObsidianWriter", return_value=fake_writer),
        patch(
            "src.transcribe_flow._create_md_generator",
            return_value=MagicMock(render=MagicMock(return_value="# Note")),
        ),
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
        patch("src.writer.obsidian.ObsidianWriter", return_value=fake_writer),
        patch("src.summarizer.pending.save_pending"),
        patch(
            "src.transcribe_flow._create_md_generator",
            return_value=MagicMock(render=MagicMock(return_value="# Note")),
        ),
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
        await transcribe_single_url(
            "http://audio.example/x.mp3", config, progress_callback=cb
        )

    assert ("asr", "error") in events
    assert ("write", "done") not in events


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
        patch("src.writer.obsidian.ObsidianWriter", return_value=fake_writer),
        patch(
            "src.transcribe_flow._create_md_generator",
            return_value=MagicMock(render=MagicMock(return_value="# Note")),
        ),
    ):
        outcome = await transcribe_single_url(
            "http://audio.example/x.mp3", config, progress_callback=cb
        )

    assert outcome.title == "T"
