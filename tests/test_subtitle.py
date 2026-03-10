from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.monitor.subtitle import fetch_subtitle_from_url, parse_subtitle_text


class TestParseSubtitleText:
    def test_parse_srt(self):
        srt = """1
00:00:00,000 --> 00:00:05,000
第一句话

2
00:00:05,000 --> 00:00:10,000
第二句话
"""
        result = parse_subtitle_text(srt)
        assert "第一句话" in result
        assert "第二句话" in result
        assert "-->" not in result
        assert "00:00" not in result

    def test_parse_vtt(self):
        vtt = """WEBVTT

00:00:00.000 --> 00:00:05.000
大家好欢迎收听

00:00:05.000 --> 00:00:10.000
今天我们聊一下AI
"""
        result = parse_subtitle_text(vtt)
        assert "大家好欢迎收听" in result
        assert "今天我们聊一下AI" in result
        assert "WEBVTT" not in result
        assert "-->" not in result

    def test_parse_removes_html_tags(self):
        srt = """1
00:00:00,000 --> 00:00:05,000
<b>加粗文本</b>和<i>斜体</i>
"""
        result = parse_subtitle_text(srt)
        assert "加粗文本" in result
        assert "<b>" not in result
        assert "<i>" not in result

    def test_parse_empty(self):
        assert parse_subtitle_text("") == ""
        assert parse_subtitle_text("   ") == ""

    def test_parse_plain_text(self):
        # 非字幕格式的纯文本
        result = parse_subtitle_text("这是一段普通文本\n没有时间戳")
        assert "这是一段普通文本" in result
        assert "没有时间戳" in result


class TestFetchSubtitleFromUrl:
    @pytest.mark.asyncio
    async def test_fetch_success(self):
        import httpx

        srt_content = """1
00:00:00,000 --> 00:00:05,000
测试字幕内容
"""
        mock_resp = MagicMock()
        mock_resp.text = srt_content
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx, "AsyncClient", lambda **kw: mock_client)
            result = await fetch_subtitle_from_url("https://example.com/sub.srt")

        assert result is not None
        assert "测试字幕内容" in result

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_none(self):
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("404"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(httpx, "AsyncClient", lambda **kw: mock_client)
            result = await fetch_subtitle_from_url("https://example.com/missing.srt")

        assert result is None
