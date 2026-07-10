from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.summarizer import prompts
from src.summarizer.poe_client import MAX_COMPLETION_TOKENS, SYSTEM_PROMPT, PoeSummarizer


class TestPoeSummarizer:
    def test_init_defaults(self):
        s = PoeSummarizer(api_key="pk-test")
        assert s._model == "gpt-5.4-mini"
        assert s._reasoning_effort == "medium"
        assert s._cooldown == 60.0

    def test_uses_shared_prompt(self):
        assert SYSTEM_PROMPT is prompts.SYSTEM_PROMPT

    def test_init_custom(self):
        s = PoeSummarizer(
            api_key="pk-test", model="GPT-5.2", reasoning_effort="high", cooldown=90.0
        )
        assert s._model == "GPT-5.2"
        assert s._reasoning_effort == "high"
        assert s._cooldown == 90.0

    def test_parse_response_valid_json(self):
        s = PoeSummarizer(api_key="pk-test")
        content = (
            '{"analysis": "分析", "summary": "摘要",'
            ' "chapters": [{"title": "章1", "summary": "内容"}],'
            ' "keywords": ["关键词"]}'
        )
        result = s._parse_response(content)
        assert result.analysis == "分析"
        assert result.summary == "摘要"
        assert len(result.chapters) == 1
        assert result.chapters[0]["title"] == "章1"
        assert result.keywords == ["关键词"]

    def test_parse_response_normalizes_real_world_analysis_array(self):
        """Gemini returned this field shape in a real v1.8.6 note."""
        s = PoeSummarizer(api_key="pk-test")
        content = (
            '{"analysis": ["第一段观点", "第二段论证"], "summary": "摘要",'
            ' "chapters": [], "keywords": []}'
        )

        result = s._parse_response(content)

        assert result.analysis == "第一段观点\n\n第二段论证"

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
                            ' "analysis": "这是分析",'
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
        assert result.analysis == "这是分析"
        assert len(result.chapters) == 1
        assert result.keywords == ["测试"]
        payload = instance.post.await_args.kwargs["json"]
        assert payload["model"] == "gpt-5.4-mini"
        assert payload["max_tokens"] == MAX_COMPLETION_TOKENS

    @pytest.mark.asyncio
    async def test_summarize_respects_cooldown(self):
        """验证两次调用之间会等待 cooldown 间隔。"""
        s = PoeSummarizer(api_key="pk-test", cooldown=0.5)

        api_response = {
            "choices": [{"message": {"content": '{"analysis": "精简版博客", "summary": "摘要"}'}}]
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

            # 第一次调用
            await s.summarize("文本1", "标题1")
            t1 = time.monotonic()

            # 第二次调用应等待 cooldown
            await s.summarize("文本2", "标题2")
            t2 = time.monotonic()

            # 两次调用间隔应 >= cooldown（0.5s）
            assert t2 - t1 >= 0.4  # 留少许误差

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
