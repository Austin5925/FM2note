from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config import AppConfig
from src.models import Episode, TranscriptResult
from src.pipeline import Pipeline


def _make_episode(**overrides):
    defaults = {
        "guid": "test-guid",
        "title": "测试节目",
        "podcast_name": "测试播客",
        "pub_date": datetime(2025, 1, 15),
        "audio_url": "https://example.com/audio.mp3",
        "duration": "01:00:00",
        "show_notes": "show notes",
        "link": "https://example.com",
    }
    defaults.update(overrides)
    return Episode(**defaults)


def _make_transcript():
    return TranscriptResult(
        text="全文",
        paragraphs=["段落1", "段落2"],
        summary="摘要",
    )


@pytest.fixture
def mock_config():
    return AppConfig(vault_path="/tmp/vault", max_retries=3)


@pytest.fixture
def mock_pipeline(mock_config, tmp_path):
    rss_checker = AsyncMock()
    downloader = AsyncMock()
    transcriber = AsyncMock()
    transcriber.transcribe = AsyncMock(return_value=_make_transcript())
    md_generator = MagicMock()
    md_generator.render = MagicMock(return_value="# Note content")
    writer = MagicMock()
    note_path = tmp_path / "note.md"
    note_path.write_text("# Note content")
    writer.write_note = MagicMock(return_value=note_path)
    state = AsyncMock()
    state.get_failed = AsyncMock(return_value=[])

    pipeline = Pipeline(
        config=mock_config,
        rss_checker=rss_checker,
        downloader=downloader,
        transcriber=transcriber,
        md_generator=md_generator,
        writer=writer,
        state=state,
    )
    return pipeline


class TestPipeline:
    @pytest.mark.asyncio
    async def test_process_episode_success(self, mock_pipeline):
        ep = _make_episode()
        path = await mock_pipeline.process_episode(ep)

        assert path.exists()
        # 验证状态流转
        calls = mock_pipeline._state.mark_status.call_args_list
        statuses = [c.args[1] for c in calls]
        assert "transcribing" in statuses
        assert "writing" in statuses
        assert "done" in statuses

    @pytest.mark.asyncio
    async def test_process_episode_marks_failed_on_error(self, mock_pipeline):
        mock_pipeline._transcriber.transcribe = AsyncMock(side_effect=Exception("转写超时"))
        ep = _make_episode()

        with pytest.raises(Exception, match="转写超时"):
            await mock_pipeline.process_episode(ep)

        calls = mock_pipeline._state.mark_status.call_args_list
        last_call = calls[-1]
        assert last_call.args[1] == "failed"

    @pytest.mark.asyncio
    async def test_run_once_no_new_episodes(self, mock_pipeline):
        mock_pipeline._rss_checker.check_all = AsyncMock(return_value=[])
        results = await mock_pipeline.run_once()
        assert results == []

    @pytest.mark.asyncio
    async def test_run_once_processes_episodes(self, mock_pipeline):
        episodes = [_make_episode(guid="g1"), _make_episode(guid="g2")]
        mock_pipeline._rss_checker.check_all = AsyncMock(return_value=episodes)

        results = await mock_pipeline.run_once()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_run_once_continues_on_failure(self, mock_pipeline):
        episodes = [_make_episode(guid="g1"), _make_episode(guid="g2")]
        mock_pipeline._rss_checker.check_all = AsyncMock(return_value=episodes)

        call_count = 0

        async def mock_transcribe(url, language="cn"):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("第一个失败")
            return _make_transcript()

        mock_pipeline._transcriber.transcribe = mock_transcribe

        results = await mock_pipeline.run_once()
        # 第一个失败，第二个成功
        assert len(results) == 1
