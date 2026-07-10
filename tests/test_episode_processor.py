"""Unit tests for the v1.5.0 EpisodeProcessor — the core shared by
Pipeline (subscription daemon) and transcribe_single_url (single-URL web)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import AppConfig
from src.episode_processor import (
    EpisodeProcessor,
    ProcessingOptions,
    ProcessOutcome,
)
from src.models import Episode, SummaryResult, TranscriptResult


def _episode(**overrides) -> Episode:
    defaults = dict(
        guid="ep-guid",
        title="测试节目",
        podcast_name="测试播客",
        pub_date=datetime(2026, 5, 25),
        audio_url="https://example.com/x.mp3",
        duration="60:00",
        show_notes="",
        link="https://example.com/x",
    )
    defaults.update(overrides)
    return Episode(**defaults)


def _transcript(text: str = "全文", summary: str = "") -> TranscriptResult:
    return TranscriptResult(text=text, paragraphs=text.split("\n"), summary=summary)


@pytest.fixture
def processor(tmp_path):
    """Default processor with everything mocked. Tests tweak attrs they care
    about; defaults are 'happy path' (no shared cache, no MCP dup, success)."""
    state = AsyncMock()
    transcriber = AsyncMock()
    transcriber.transcribe = AsyncMock(return_value=_transcript())
    md_generator = MagicMock()
    md_generator.render = MagicMock(return_value="# Note")
    writer = MagicMock()
    writer.search_existing_mcp = AsyncMock(return_value=False)
    writer.note_exists = MagicMock(return_value=False)
    note_path = tmp_path / "note.md"
    note_path.write_text("# Note", encoding="utf-8")
    writer.write_note = MagicMock(return_value=note_path)
    config = AppConfig(vault_path=str(tmp_path), asr_engine="funasr")
    p = EpisodeProcessor(
        config=config,
        state=state,
        transcriber=transcriber,
        md_generator=md_generator,
        writer=writer,
        summarizer=None,
    )
    return p


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_basic_process_returns_outcome(self, processor):
        outcome = await processor.process(_episode())
        assert isinstance(outcome, ProcessOutcome)
        assert outcome.char_count == len(_transcript().text)
        assert outcome.cache_hit is False
        # Render received asr_engine from config
        processor.md_generator.render.assert_called_once()
        assert processor.md_generator.render.call_args.kwargs["asr_engine"] == "funasr"

    @pytest.mark.asyncio
    async def test_condensed_blog_is_added_to_transcript_before_render(self, processor):
        summarizer = AsyncMock()
        summarizer.summarize = AsyncMock(
            return_value=SummaryResult(summary="摘要", analysis="精简版博客")
        )
        processor.summarizer = summarizer

        await processor.process(_episode())

        rendered_transcript = processor.md_generator.render.call_args.args[1]
        assert rendered_transcript.analysis == "精简版博客"
        assert rendered_transcript.summary == "摘要"


class TestCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_transcriber(self, processor):
        cache = MagicMock()
        cache.fetch = AsyncMock(return_value="# cached")
        cache.upload = AsyncMock()
        processor.shared_cache = cache
        outcome = await processor.process(_episode())
        # Critical: ASR never ran
        processor.transcriber.transcribe.assert_not_called()
        processor.md_generator.render.assert_not_called()
        # And we don't re-upload what we just fetched
        cache.upload.assert_not_called()
        assert outcome.cache_hit is True

    @pytest.mark.asyncio
    async def test_cache_hit_when_note_exists_is_idempotent(self, processor, tmp_path):
        """If a cache hit comes back AND the note already exists locally,
        don't call write_note (FileExistsError); just mark_status done."""
        cache = MagicMock()
        cache.fetch = AsyncMock(return_value="# cached")
        processor.shared_cache = cache
        processor.writer.note_exists = MagicMock(return_value=True)
        processor.writer._build_path = MagicMock(return_value=tmp_path / "existing.md")
        processor.writer.write_note = MagicMock(side_effect=AssertionError("must not be called"))
        outcome = await processor.process(_episode())
        processor.writer.write_note.assert_not_called()
        assert outcome.cache_hit is True

    @pytest.mark.asyncio
    async def test_cache_fetch_raise_falls_through_to_pipeline(self, processor):
        cache = MagicMock()
        cache.fetch = AsyncMock(side_effect=RuntimeError("DNS"))
        cache.upload = AsyncMock(return_value=True)
        processor.shared_cache = cache
        outcome = await processor.process(_episode())
        # Cache miss → normal pipeline runs and uploads
        processor.transcriber.transcribe.assert_called_once()
        cache.upload.assert_called_once()
        assert outcome.cache_hit is False


class TestProcessingOptions:
    @pytest.mark.asyncio
    async def test_use_shared_cache_fetch_false_skips_cache(self, processor):
        cache = MagicMock()
        cache.fetch = AsyncMock(return_value="# would have been cached")
        cache.upload = AsyncMock()
        processor.shared_cache = cache
        opts = ProcessingOptions(use_shared_cache_fetch=False)
        await processor.process(_episode(), options=opts)
        # fetch was never called — single-URL flow explicitly wants fresh work
        cache.fetch.assert_not_called()
        processor.transcriber.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_use_shared_cache_upload_false_skips_upload(self, processor):
        cache = MagicMock()
        cache.fetch = AsyncMock(return_value=None)
        cache.upload = AsyncMock()
        processor.shared_cache = cache
        opts = ProcessingOptions(use_shared_cache_upload=False)
        await processor.process(_episode(), options=opts)
        cache.upload.assert_not_called()

    @pytest.mark.asyncio
    async def test_do_mcp_dedup_false_skips_mcp(self, processor):
        opts = ProcessingOptions(do_mcp_dedup=False)
        await processor.process(_episode(), options=opts)
        processor.writer.search_existing_mcp.assert_not_called()

    @pytest.mark.asyncio
    async def test_mcp_hit_raises_file_exists(self, processor):
        processor.writer.search_existing_mcp = AsyncMock(return_value=True)
        with pytest.raises(FileExistsError):
            await processor.process(_episode(), options=ProcessingOptions(do_mcp_dedup=True))


class TestProgressCallback:
    @pytest.mark.asyncio
    async def test_normal_path_emits_all_stages(self, processor):
        events: list = []
        await processor.process(
            _episode(),
            progress_callback=lambda s, st, msg: events.append((s, st)),
        )
        stages = {s for s, _ in events}
        # All non-resolve stages should show up (resolve is single-URL-only).
        assert "subtitle_check" in stages
        assert "asr" in stages
        assert "summary" in stages
        assert "write" in stages
        # Final write event is done
        assert ("write", "done") in events

    @pytest.mark.asyncio
    async def test_cache_hit_emits_skipped_asr(self, processor):
        cache = MagicMock()
        cache.fetch = AsyncMock(return_value="# cached")
        cache.upload = AsyncMock()
        processor.shared_cache = cache
        events: list = []
        await processor.process(
            _episode(),
            progress_callback=lambda s, st, msg: events.append((s, st)),
        )
        # The cache hit path emits asr=skipped instead of asr=start/done
        assert ("asr", "skipped") in events

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_break_pipeline(self, processor):
        """A broken subscriber must not take down the daemon."""

        def _explosive(s, st, msg):
            raise RuntimeError("subscriber went wild")

        # Should NOT raise
        outcome = await processor.process(_episode(), progress_callback=_explosive)
        assert outcome.char_count > 0


class TestMarkStatusPodcastNameTitle:
    """Code Review A2 v1.5.0 fix: mark_status('done') must populate
    podcast_name + title so the history row is never blank."""

    @pytest.mark.asyncio
    async def test_done_call_includes_podcast_and_title(self, processor):
        ep = _episode(podcast_name="My Podcast", title="EP 42")
        await processor.process(ep)
        # Find the 'done' mark_status call
        done_calls = [c for c in processor.state.mark_status.call_args_list if c.args[1] == "done"]
        assert done_calls, "expected a mark_status('done') call"
        last_done = done_calls[-1]
        assert last_done.kwargs.get("podcast_name") == "My Podcast"
        assert last_done.kwargs.get("title") == "EP 42"
        assert last_done.kwargs.get("note_path")
