"""Unit tests for src.shared_cache (v1.4.16)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.shared_cache import SharedCacheClient


class TestFromEnv:
    def test_unconfigured_returns_none(self, monkeypatch):
        monkeypatch.delenv("SHARED_CACHE_URL", raising=False)
        monkeypatch.delenv("SHARED_CACHE_TOKEN", raising=False)
        assert SharedCacheClient.from_env() is None

    def test_only_url_set_returns_none(self, monkeypatch):
        """Both env vars must be present; partial config is treated as
        unconfigured so an in-progress setup never silently sends requests
        without auth."""
        monkeypatch.setenv("SHARED_CACHE_URL", "https://x/cache")
        monkeypatch.delenv("SHARED_CACHE_TOKEN", raising=False)
        assert SharedCacheClient.from_env() is None

    def test_only_token_set_returns_none(self, monkeypatch):
        monkeypatch.delenv("SHARED_CACHE_URL", raising=False)
        monkeypatch.setenv("SHARED_CACHE_TOKEN", "abc")
        assert SharedCacheClient.from_env() is None

    def test_both_set_returns_client(self, monkeypatch):
        monkeypatch.setenv("SHARED_CACHE_URL", "https://x/cache")
        monkeypatch.setenv("SHARED_CACHE_TOKEN", "abc")
        c = SharedCacheClient.from_env()
        assert c is not None

    def test_trailing_slash_trimmed(self, monkeypatch):
        monkeypatch.setenv("SHARED_CACHE_URL", "https://x/cache/")
        monkeypatch.setenv("SHARED_CACHE_TOKEN", "abc")
        c = SharedCacheClient.from_env()
        assert c._url_for("g1") == "https://x/cache/cache/g1"


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_hit_returns_content(self):
        client = SharedCacheClient("https://x", "tok")
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"ok": True, "guid": "g1", "content": "# hello\n"})
        with patch(
            "httpx.AsyncClient.__aenter__",
            return_value=MagicMock(get=AsyncMock(return_value=resp)),
        ):
            content = await client.fetch("g1")
        assert content == "# hello\n"

    @pytest.mark.asyncio
    async def test_fetch_404_returns_none(self):
        client = SharedCacheClient("https://x", "tok")
        resp = MagicMock(status_code=404)
        with patch(
            "httpx.AsyncClient.__aenter__",
            return_value=MagicMock(get=AsyncMock(return_value=resp)),
        ):
            assert await client.fetch("g1") is None

    @pytest.mark.asyncio
    async def test_fetch_5xx_returns_none(self):
        """Server errors must be treated as miss — never as fatal. The local
        pipeline always has a fallback (do the work locally)."""
        client = SharedCacheClient("https://x", "tok")
        resp = MagicMock(status_code=502)
        with patch(
            "httpx.AsyncClient.__aenter__",
            return_value=MagicMock(get=AsyncMock(return_value=resp)),
        ):
            assert await client.fetch("g1") is None

    @pytest.mark.asyncio
    async def test_fetch_network_error_returns_none(self):
        """A DNS / connection failure must NOT raise into the pipeline."""
        client = SharedCacheClient("https://x", "tok")
        with patch(
            "httpx.AsyncClient.__aenter__",
            return_value=MagicMock(get=AsyncMock(side_effect=httpx.ConnectError("nope"))),
        ):
            assert await client.fetch("g1") is None

    @pytest.mark.asyncio
    async def test_fetch_auth_header_sent(self):
        client = SharedCacheClient("https://x", "TESTTOKEN")
        resp = MagicMock(status_code=404)
        get_mock = AsyncMock(return_value=resp)
        with patch(
            "httpx.AsyncClient.__aenter__",
            return_value=MagicMock(get=get_mock),
        ):
            await client.fetch("g1")
        _, kwargs = get_mock.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer TESTTOKEN"


class TestUpload:
    @pytest.mark.asyncio
    async def test_upload_success_returns_true(self):
        client = SharedCacheClient("https://x", "tok")
        resp = MagicMock(status_code=200)
        post_mock = AsyncMock(return_value=resp)
        with patch(
            "httpx.AsyncClient.__aenter__",
            return_value=MagicMock(post=post_mock),
        ):
            ok = await client.upload("g1", "# note")
        assert ok is True
        _, kwargs = post_mock.call_args
        assert kwargs["json"]["content"] == "# note"
        assert "uploader_fp" in kwargs["json"]

    @pytest.mark.asyncio
    async def test_upload_empty_content_no_request(self):
        """Avoid wasting a round-trip on empty content (which the server
        rejects anyway). Returns False without touching the network."""
        client = SharedCacheClient("https://x", "tok")
        with patch("httpx.AsyncClient.__aenter__") as mock_ctx:
            ok = await client.upload("g1", "")
        assert ok is False
        mock_ctx.assert_not_called()

    @pytest.mark.asyncio
    async def test_upload_4xx_returns_false_no_raise(self):
        client = SharedCacheClient("https://x", "tok")
        resp = MagicMock(status_code=401, text="bad token")
        with patch(
            "httpx.AsyncClient.__aenter__",
            return_value=MagicMock(post=AsyncMock(return_value=resp)),
        ):
            assert await client.upload("g1", "# note") is False

    @pytest.mark.asyncio
    async def test_upload_network_error_returns_false(self):
        client = SharedCacheClient("https://x", "tok")
        with patch(
            "httpx.AsyncClient.__aenter__",
            return_value=MagicMock(post=AsyncMock(side_effect=httpx.TimeoutException("slow"))),
        ):
            assert await client.upload("g1", "# note") is False


class TestUrlEncoding:
    def test_guid_with_slashes_encoded(self):
        """RSS GUIDs are often link-shaped (https://...). URL-encode them
        fully so the server's /cache/{guid:path} route matches a single
        path segment."""
        client = SharedCacheClient("https://x", "tok")
        url = client._url_for("https://example.com/ep/42")
        assert url == "https://x/cache/https%3A%2F%2Fexample.com%2Fep%2F42"

    def test_guid_with_unicode_encoded(self):
        client = SharedCacheClient("https://x", "tok")
        url = client._url_for("非共识/ep/42")
        # All non-ASCII percent-encoded, ASCII slashes encoded too (safe="")
        assert "%" in url and "非" not in url
