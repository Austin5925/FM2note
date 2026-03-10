"""转写器模块测试

使用 mock 测试每个引擎的请求构建、轮询逻辑、结果解析、错误处理。
不实际调用外部 API。
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import AppConfig
from src.models import TranscriptResult
from src.transcriber.bailian import BailianTranscriber
from src.transcriber.base import TranscriptionError
from src.transcriber.factory import create_transcriber
from src.transcriber.tingwu import TingwuTranscriber
from src.transcriber.whisper_api import WhisperTranscriber


def _mock_dashscope_modules():
    """注入 dashscope mock 模块到 sys.modules，避免实际安装依赖"""
    mock_tingwu = MagicMock()
    modules = {
        "dashscope": MagicMock(),
        "dashscope.multimodal": MagicMock(),
        "dashscope.multimodal.tingwu": MagicMock(),
        "dashscope.multimodal.tingwu.tingwu": mock_tingwu,
    }
    return modules, mock_tingwu.TingWu

# ==================== Base Protocol ====================


class TestTranscriberProtocol:
    def test_tingwu_has_name(self):
        t = TingwuTranscriber("api_key", "app_id")
        assert t.name == "tingwu"

    def test_bailian_has_name(self):
        t = BailianTranscriber("api_key")
        assert t.name == "bailian"

    def test_whisper_has_name(self):
        t = WhisperTranscriber("api_key")
        assert t.name == "whisper_api"


# ==================== TingwuTranscriber ====================


class TestTingwuTranscriber:
    def setup_method(self):
        self.transcriber = TingwuTranscriber("test_api_key", "test_app_id")

    @pytest.mark.asyncio
    async def test_create_task_success(self):
        mock_response = {"output": {"dataId": "data-123"}}
        modules, mock_tingwu_cls = _mock_dashscope_modules()
        mock_tingwu_cls.call = MagicMock(return_value=mock_response)

        with patch.dict(sys.modules, modules):
            data_id = await self.transcriber._create_task("https://example.com/audio.mp3")

        assert data_id == "data-123"
        call_args = mock_tingwu_cls.call.call_args
        assert call_args.kwargs["model"] == "tingwu-meeting"
        assert call_args.kwargs["user_defined_input"]["appId"] == "test_app_id"
        assert call_args.kwargs["user_defined_input"]["fileUrl"] == "https://example.com/audio.mp3"

    @pytest.mark.asyncio
    async def test_create_task_failure(self):
        mock_response = {"output": {}}
        modules, mock_tingwu_cls = _mock_dashscope_modules()
        mock_tingwu_cls.call = MagicMock(return_value=mock_response)

        with patch.dict(sys.modules, modules):
            with pytest.raises(TranscriptionError, match="创建任务失败"):
                await self.transcriber._create_task("https://example.com/audio.mp3")

    @pytest.mark.asyncio
    async def test_fetch_oss_result_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"Transcription": {"Paragraphs": []}}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await self.transcriber._fetch_oss_result("https://oss.example.com/result.json")
            assert result == {"Transcription": {"Paragraphs": []}}

    @pytest.mark.asyncio
    async def test_parse_result_with_all_fields(self):
        raw_result = {
            "result": {
                "transcription": "https://oss.example.com/trans.json",
                "summarization": "https://oss.example.com/summary.json",
                "autoChapters": "https://oss.example.com/chapters.json",
            }
        }

        trans_json = {
            "Transcription": {
                "Paragraphs": [
                    {"Words": [{"Text": "第一段文本"}]},
                    {"Words": [{"Text": "第二段文本"}]},
                ]
            }
        }
        summary_json = {"Summarization": {"Paragraph": "这是摘要"}}
        chapters_json = {
            "AutoChapters": [
                {"Title": "第一章", "Summary": "章节摘要"}
            ]
        }

        async def mock_fetch(url):
            if "trans" in url:
                return trans_json
            elif "summary" in url:
                return summary_json
            elif "chapters" in url:
                return chapters_json
            return {}

        self.transcriber._fetch_oss_result = mock_fetch

        result = await self.transcriber._parse_result(raw_result)
        assert isinstance(result, TranscriptResult)
        assert len(result.paragraphs) == 2
        assert result.paragraphs[0] == "第一段文本"
        assert result.summary == "这是摘要"
        assert len(result.chapters) == 1
        assert result.chapters[0]["title"] == "第一章"

    @pytest.mark.asyncio
    async def test_parse_result_pascal_case(self):
        """兼容 PascalCase 字段名"""
        raw_result = {
            "Result": {
                "Transcription": "https://oss.example.com/trans.json",
            }
        }

        trans_json = {
            "Transcription": {
                "Paragraphs": [
                    {"Words": [{"Text": "段落内容"}]},
                ]
            }
        }

        self.transcriber._fetch_oss_result = AsyncMock(return_value=trans_json)
        result = await self.transcriber._parse_result(raw_result)
        assert result.paragraphs[0] == "段落内容"

    @pytest.mark.asyncio
    async def test_parse_result_empty(self):
        raw_result = {"result": {}}
        result = await self.transcriber._parse_result(raw_result)
        assert result.text == ""
        assert result.paragraphs == []
        assert result.summary is None
        assert result.chapters is None


# ==================== BailianTranscriber ====================


class TestBailianTranscriber:
    def setup_method(self):
        self.transcriber = BailianTranscriber("test_api_key")

    @pytest.mark.asyncio
    async def test_parse_result_success(self):
        trans_json = {
            "transcripts": [
                {
                    "text": "句子一句子二句子三句子四句子五句子六",
                    "sentences": [
                        {"text": "句子一"},
                        {"text": "句子二"},
                        {"text": "句子三"},
                        {"text": "句子四"},
                        {"text": "句子五"},
                        {"text": "句子六"},
                    ],
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.json.return_value = trans_json
        mock_response.raise_for_status = MagicMock()

        mock_result = MagicMock()
        mock_result.output = {
            "results": [{"transcription_url": "https://oss.example.com/result.json"}]
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await self.transcriber._parse_result(mock_result)

        assert isinstance(result, TranscriptResult)
        assert result.text == "句子一句子二句子三句子四句子五句子六"
        assert len(result.paragraphs) == 2  # 5 + 1 = 2 paragraphs
        assert result.summary is None

    @pytest.mark.asyncio
    async def test_parse_result_empty(self):
        mock_result = MagicMock()
        mock_result.output = {"results": []}

        with pytest.raises(TranscriptionError, match="结果为空"):
            await self.transcriber._parse_result(mock_result)


# ==================== WhisperTranscriber ====================


class TestWhisperTranscriber:
    def setup_method(self):
        self.transcriber = WhisperTranscriber("test_api_key", temp_dir="/tmp/fm2note_test")

    def test_max_file_size(self):
        assert self.transcriber.MAX_FILE_SIZE == 25 * 1024 * 1024


# ==================== Factory ====================


class TestTranscriberFactory:
    def _make_config(self, **overrides) -> AppConfig:
        defaults = {
            "vault_path": "/tmp/vault",
            "asr_engine": "tingwu",
            "dashscope_api_key": "test_ds_key",
            "tingwu_app_id": "test_app_id",
            "openai_api_key": "test_oai_key",
        }
        defaults.update(overrides)
        return AppConfig(**defaults)

    def test_create_tingwu(self):
        config = self._make_config(asr_engine="tingwu")
        t = create_transcriber(config)
        assert isinstance(t, TingwuTranscriber)
        assert t.name == "tingwu"

    def test_create_bailian(self):
        config = self._make_config(asr_engine="bailian")
        t = create_transcriber(config)
        assert isinstance(t, BailianTranscriber)
        assert t.name == "bailian"

    def test_create_whisper(self):
        config = self._make_config(asr_engine="whisper_api")
        t = create_transcriber(config)
        assert isinstance(t, WhisperTranscriber)
        assert t.name == "whisper_api"

    def test_unknown_engine_raises(self):
        config = self._make_config(asr_engine="unknown")
        with pytest.raises(TranscriptionError, match="不支持"):
            create_transcriber(config)

    def test_missing_dashscope_key_for_tingwu_raises(self):
        config = self._make_config(asr_engine="tingwu", dashscope_api_key="")
        with pytest.raises(TranscriptionError, match="DASHSCOPE_API_KEY"):
            create_transcriber(config)

    def test_missing_tingwu_app_id_raises(self):
        config = self._make_config(asr_engine="tingwu", tingwu_app_id="")
        with pytest.raises(TranscriptionError, match="TINGWU_APP_ID"):
            create_transcriber(config)

    def test_missing_bailian_key_raises(self):
        config = self._make_config(asr_engine="bailian", dashscope_api_key="")
        with pytest.raises(TranscriptionError, match="DASHSCOPE_API_KEY"):
            create_transcriber(config)

    def test_missing_whisper_key_raises(self):
        config = self._make_config(asr_engine="whisper_api", openai_api_key="")
        with pytest.raises(TranscriptionError, match="OPENAI_API_KEY"):
            create_transcriber(config)
