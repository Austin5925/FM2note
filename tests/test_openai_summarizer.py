"""Tests for OpenAI-compatible summarizer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.summarizer.openai_client import OpenAISummarizer


@pytest.fixture
def summarizer():
    return OpenAISummarizer(api_key="test-key", model="gpt-4o-mini", cooldown=0)


class TestOpenAISummarizer:
    def test_name(self, summarizer):
        assert summarizer.name == "openai/gpt-4o-mini"

    def test_custom_model_name(self):
        s = OpenAISummarizer(api_key="k", model="deepseek-chat")
        assert s.name == "openai/deepseek-chat"

    @pytest.mark.asyncio
    async def test_summarize_success(self, summarizer):
        response_data = {
            "summary": "Test summary",
            "chapters": [{"title": "Ch1", "summary": "Sum1"}],
            "keywords": ["AI", "podcast"],
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps(response_data)}}]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await summarizer.summarize("transcript text", "Episode Title")

        assert result.summary == "Test summary"
        assert result.chapters is not None
        assert len(result.chapters) == 1
        assert result.keywords == ["AI", "podcast"]

    @pytest.mark.asyncio
    async def test_summarize_empty_response(self, summarizer):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": ""}}]}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="empty content"):
                await summarizer.summarize("text", "title", max_retries=1)

    def test_parse_response_valid_json(self, summarizer):
        content = json.dumps(
            {
                "summary": "S",
                "chapters": [{"title": "T", "summary": "S"}],
                "keywords": ["k1"],
            }
        )
        result = summarizer._parse_response(content)
        assert result.summary == "S"
        assert result.keywords == ["k1"]

    def test_parse_response_json_with_wrapper(self, summarizer):
        content = 'Here is the result:\n{"summary": "wrapped", "chapters": [], "keywords": []}'
        result = summarizer._parse_response(content)
        assert result.summary == "wrapped"

    def test_parse_response_invalid_json(self, summarizer):
        result = summarizer._parse_response("not json at all")
        assert result.summary == "not json at all"

    def test_custom_base_url(self):
        s = OpenAISummarizer(
            api_key="k",
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
        )
        assert s._base_url == "https://api.deepseek.com/v1"

    def test_base_url_trailing_slash_stripped(self):
        s = OpenAISummarizer(api_key="k", base_url="https://api.example.com/v1/")
        assert s._base_url == "https://api.example.com/v1"
