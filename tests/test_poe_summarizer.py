from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.summarizer.poe_client import PoeSummarizer


class TestPoeSummarizer:
    def test_init_defaults(self):
        s = PoeSummarizer(api_key="pk-test")
        assert s._model == "GPT-5.4"
        assert s._reasoning_effort == "medium"

    def test_init_custom(self):
        s = PoeSummarizer(api_key="pk-test", model="GPT-5.2", reasoning_effort="high")
        assert s._model == "GPT-5.2"
        assert s._reasoning_effort == "high"

    def test_parse_response_valid_json(self):
        s = PoeSummarizer(api_key="pk-test")
        content = (
            '{"summary": "摘要", "chapters": [{"title": "章1", "summary": "内容"}],'
            ' "keywords": ["关键词"]}'
        )
        result = s._parse_response(content)
        assert result.summary == "摘要"
        assert len(result.chapters) == 1
        assert result.chapters[0]["title"] == "章1"
        assert result.keywords == ["关键词"]

    def test_parse_response_json_in_markdown(self):
        s = PoeSummarizer(api_key="pk-test")
        content = '```json\n{"summary": "内容摘要", "chapters": [], "keywords": []}\n```'
        result = s._parse_response(content)
        assert result.summary == "内容摘要"

    def test_parse_response_invalid_fallback(self):
        s = PoeSummarizer(api_key="pk-test")
        content = "这不是 JSON，只是普通文本"
        result = s._parse_response(content)
        assert result.summary == content
        assert result.chapters is None
        assert result.keywords is None

    def test_parse_response_partial_json(self):
        s = PoeSummarizer(api_key="pk-test")
        content = '前面有文字 {"summary": "部分摘要"} 后面也有'
        result = s._parse_response(content)
        assert result.summary == "部分摘要"
        assert result.chapters is None

    def test_to_summary_result_invalid_chapters(self):
        s = PoeSummarizer(api_key="pk-test")
        data = {"summary": "摘要", "chapters": "不是列表", "keywords": None}
        result = s._to_summary_result(data)
        assert result.summary == "摘要"
        assert result.chapters is None
        assert result.keywords is None

    @pytest.mark.asyncio
    async def test_summarize_success(self):
        s = PoeSummarizer(api_key="pk-test")

        api_response = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"summary": "这是摘要", "chapters":'
                            ' [{"title": "开头", "summary": "介绍"}],'
                            ' "keywords": ["测试"]}'
                        )
                    }
                }
            ]
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = api_response
        mock_resp.raise_for_status = MagicMock()

        with patch("src.summarizer.poe_client.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = mock_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            result = await s.summarize("转写文本内容", "播客标题")

        assert result.summary == "这是摘要"
        assert len(result.chapters) == 1
        assert result.keywords == ["测试"]

    @pytest.mark.asyncio
    async def test_summarize_empty_response(self):
        s = PoeSummarizer(api_key="pk-test")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("src.summarizer.poe_client.httpx.AsyncClient") as mock_client:
            instance = AsyncMock()
            instance.post.return_value = mock_resp
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = instance

            with pytest.raises(ValueError, match="空内容"):
                await s.summarize("文本", "标题")
