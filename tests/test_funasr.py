from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.transcriber.base import TranscriptionError
from src.transcriber.funasr import FunASRTranscriber, ParaformerTranscriber


class TestFunASRTranscriber:
    def test_name(self):
        t = FunASRTranscriber(api_key="sk-test")
        assert t.name == "funasr"

    def test_default_model(self):
        t = FunASRTranscriber(api_key="sk-test")
        assert t.MODEL == "fun-asr"

    def test_custom_model(self):
        t = FunASRTranscriber(api_key="sk-test", model="fun-asr-mtl")
        assert t.MODEL == "fun-asr-mtl"

    def test_sentences_to_paragraphs_empty(self):
        t = FunASRTranscriber(api_key="sk-test")
        assert t._sentences_to_paragraphs([]) == []

    def test_sentences_to_paragraphs_basic(self):
        t = FunASRTranscriber(api_key="sk-test")
        sentences = [
            {"text": "第一句。", "begin_time": 0, "end_time": 1000},
            {"text": "第二句。", "begin_time": 1100, "end_time": 2000},
            {"text": "第三句。", "begin_time": 2100, "end_time": 3000},
        ]
        result = t._sentences_to_paragraphs(sentences, max_sentences=5)
        assert len(result) == 1
        assert "第一句" in result[0]
        assert "第三句" in result[0]

    def test_sentences_to_paragraphs_split_by_count(self):
        t = FunASRTranscriber(api_key="sk-test")
        sentences = [
            {"text": f"句子{i}。", "begin_time": i * 1000, "end_time": i * 1000 + 900}
            for i in range(10)
        ]
        result = t._sentences_to_paragraphs(sentences, max_sentences=3)
        assert len(result) == 4  # 3+3+3+1

    def test_sentences_to_paragraphs_split_by_gap(self):
        t = FunASRTranscriber(api_key="sk-test")
        sentences = [
            {"text": "段落一。", "begin_time": 0, "end_time": 1000},
            {"text": "段落二。", "begin_time": 5000, "end_time": 6000},  # 4s gap
        ]
        result = t._sentences_to_paragraphs(sentences, gap_threshold_ms=2000)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_parse_results_empty(self):
        t = FunASRTranscriber(api_key="sk-test")
        with pytest.raises(TranscriptionError, match="空结果"):
            await t._parse_results({"results": []})

    @pytest.mark.asyncio
    async def test_parse_results_failed_subtask(self):
        t = FunASRTranscriber(api_key="sk-test")
        output = {"results": [{"subtask_status": "FAILED"}]}
        with pytest.raises(TranscriptionError, match="子任务失败"):
            await t._parse_results(output)

    @pytest.mark.asyncio
    async def test_fetch_and_parse_success(self):
        t = FunASRTranscriber(api_key="sk-test")
        mock_json = {
            "transcripts": [
                {
                    "channel_id": 0,
                    "text": "你好世界。这是测试。",
                    "sentences": [
                        {"text": "你好世界。", "begin_time": 0, "end_time": 1000},
                        {"text": "这是测试。", "begin_time": 1100, "end_time": 2000},
                    ],
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_json
        mock_resp.raise_for_status = MagicMock()

        with patch("src.transcriber.funasr.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.get.return_value = mock_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await t._fetch_and_parse("https://example.com/result.json")

        assert result.text == "你好世界。这是测试。"
        assert len(result.paragraphs) == 1
        assert result.summary is None
        assert result.chapters is None


class TestParaformerTranscriber:
    def test_name(self):
        t = ParaformerTranscriber(api_key="sk-test")
        assert t.name == "paraformer"

    def test_model(self):
        t = ParaformerTranscriber(api_key="sk-test")
        assert t.MODEL == "paraformer-v2"
