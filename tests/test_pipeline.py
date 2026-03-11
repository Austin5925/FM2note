from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

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
    writer.search_existing_mcp = AsyncMock(return_value=False)
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

    @pytest.mark.asyncio
    async def test_process_episode_with_subtitle(self, mock_pipeline):
        """有内置字幕时跳过 ASR"""
        ep = _make_episode(subtitle_url="https://example.com/sub.srt")

        with patch(
            "src.pipeline.fetch_subtitle_from_url",
            AsyncMock(return_value="字幕文本第一行\n字幕文本第二行"),
        ):
            path = await mock_pipeline.process_episode(ep)

        assert path.exists()
        # 不应调用 transcriber
        mock_pipeline._transcriber.transcribe.assert_not_called()
        # render 应收到 asr_engine="subtitle"
        render_call = mock_pipeline._md_generator.render.call_args
        assert render_call.kwargs.get("asr_engine") == "subtitle"

    @pytest.mark.asyncio
    async def test_process_episode_subtitle_fallback(self, mock_pipeline):
        """字幕下载失败时回退到 ASR"""
        ep = _make_episode(subtitle_url="https://example.com/sub.srt")

        with patch(
            "src.pipeline.fetch_subtitle_from_url",
            AsyncMock(return_value=None),
        ):
            path = await mock_pipeline.process_episode(ep)

        assert path.exists()
        # 应回退调用 transcriber
        mock_pipeline._transcriber.transcribe.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_episode_mcp_dedup(self, mock_pipeline):
        """MCP 发现同名笔记时跳过"""
        mock_pipeline._writer.search_existing_mcp = AsyncMock(return_value=True)
        ep = _make_episode()

        with pytest.raises(FileExistsError, match="MCP"):
            await mock_pipeline.process_episode(ep)

        # 不应调用 transcriber
        mock_pipeline._transcriber.transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_episode_saves_pending_on_summary_failure(
        self, mock_config, tmp_path
    ):
        """摘要失败时应缓存转录结果到 pending"""
        # 构建带 summarizer 的 pipeline
        transcript_no_summary = TranscriptResult(
            text="转写文本内容",
            paragraphs=["段落1"],
        )
        transcriber = AsyncMock()
        transcriber.transcribe = AsyncMock(return_value=transcript_no_summary)

        md_generator = MagicMock()
        md_generator.render = MagicMock(return_value="# Note")

        note_path = tmp_path / "note.md"
        note_path.write_text("# Note")
        writer = MagicMock()
        writer.search_existing_mcp = AsyncMock(return_value=False)
        writer.write_note = MagicMock(return_value=note_path)

        state = AsyncMock()
        state.get_failed = AsyncMock(return_value=[])

        summarizer = AsyncMock()
        summarizer.summarize = AsyncMock(side_effect=Exception("Poe API 连接失败"))

        pipeline = Pipeline(
            config=mock_config,
            rss_checker=AsyncMock(),
            downloader=AsyncMock(),
            transcriber=transcriber,
            md_generator=md_generator,
            writer=writer,
            state=state,
            summarizer=summarizer,
        )

        pending_dir = tmp_path / "pending"
        with patch("src.summarizer.pending.PENDING_DIR", pending_dir):
            ep = _make_episode()
            path = await pipeline.process_episode(ep)

        # 笔记仍应写入成功
        assert path.exists()
        # pending 目录应有缓存文件
        assert pending_dir.exists()
        pending_files = list(pending_dir.glob("*.json"))
        assert len(pending_files) == 1
