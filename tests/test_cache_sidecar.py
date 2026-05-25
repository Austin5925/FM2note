"""Integration tests for server/cache_sidecar.py (v1.4.16)."""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Build a TestClient backed by a temp SQLite DB. The sidecar reads its
    DB path + token from env at module import time, so we monkeypatch and
    reimport the module to get a fresh app instance."""
    db = tmp_path / "cache.db"
    monkeypatch.setenv("CACHE_DB_PATH", str(db))
    monkeypatch.setenv("SHARED_CACHE_TOKEN", "test-token-42")
    # Force reimport so module-level constants pick up our env
    import server.cache_sidecar as mod

    importlib.reload(mod)
    with TestClient(mod.app) as c:
        yield c


def _auth(token="test-token-42"):
    return {"Authorization": f"Bearer {token}"}


class TestHealthz:
    def test_no_auth_required(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True


class TestAuth:
    def test_missing_bearer_token_returns_401(self, client):
        r = client.get("/cache/some-guid")
        assert r.status_code == 401

    def test_wrong_token_returns_401(self, client):
        r = client.get("/cache/some-guid", headers=_auth("wrong-token"))
        assert r.status_code == 401

    def test_no_bearer_prefix_returns_401(self, client):
        r = client.get("/cache/some-guid", headers={"Authorization": "test-token-42"})
        assert r.status_code == 401


class TestRoundTrip:
    def test_get_miss_returns_404(self, client):
        r = client.get("/cache/nonexistent", headers=_auth())
        assert r.status_code == 404
        assert r.json()["ok"] is False

    def test_post_then_get_round_trip(self, client):
        post = client.post(
            "/cache/abc123",
            headers=_auth(),
            json={"content": "# Hello\nworld", "uploader_fp": "fp1"},
        )
        assert post.status_code == 200
        assert post.json()["ok"] is True

        get = client.get("/cache/abc123", headers=_auth())
        assert get.status_code == 200
        body = get.json()
        assert body["content"] == "# Hello\nworld"
        assert body["uploader_fp"] == "fp1"

    def test_post_upsert_overwrites_last_write_wins(self, client):
        client.post(
            "/cache/abc",
            headers=_auth(),
            json={"content": "v1", "uploader_fp": "user-a"},
        )
        client.post(
            "/cache/abc",
            headers=_auth(),
            json={"content": "v2", "uploader_fp": "user-b"},
        )
        get = client.get("/cache/abc", headers=_auth())
        body = get.json()
        assert body["content"] == "v2"
        assert body["uploader_fp"] == "user-b"


class TestValidation:
    def test_post_empty_content_returns_400(self, client):
        r = client.post("/cache/g1", headers=_auth(), json={"content": ""})
        assert r.status_code == 400

    def test_post_whitespace_content_returns_400(self, client):
        r = client.post("/cache/g1", headers=_auth(), json={"content": "   \n  "})
        assert r.status_code == 400

    def test_post_oversize_content_returns_413(self, client, monkeypatch):
        """5 MB ceiling on uploads — way above real notes (~5-50 KB) but
        rules out abuse. v1.4.16 Codex audit #6 added a body-size middleware
        that rejects via Content-Length BEFORE FastAPI buffers the body, so
        this 6 MB request is rejected at the network boundary, not after
        loading the whole JSON into memory."""
        # The default MAX_CONTENT_BYTES is 5 MB; build a 6 MB string
        big = "x" * (6 * 1024 * 1024)
        r = client.post("/cache/big", headers=_auth(), json={"content": big})
        assert r.status_code == 413
        # The middleware fires before auth, so the detail string is the
        # middleware one (not the per-route one)
        assert "exceeds" in r.json()["detail"]

    def test_oversize_body_rejected_without_loading(self, client):
        """The middleware uses Content-Length so it doesn't even need to be
        valid JSON — a raw 6 MB blob with Content-Length set is rejected."""

        # Use httpx via TestClient's underlying transport with a raw body.
        # The simplest probe: post a giant raw string body.
        big = b"x" * (6 * 1024 * 1024)
        r = client.post(
            "/cache/raw",
            headers={**_auth(), "Content-Type": "application/octet-stream"},
            content=big,
        )
        # 413 from middleware
        assert r.status_code == 413

    def test_guid_too_long_returns_400(self, client):
        long_guid = "a" * 300
        r = client.post("/cache/" + long_guid, headers=_auth(), json={"content": "x"})
        assert r.status_code == 400

    def test_guid_with_slashes_path_works(self, client):
        """GUIDs are often link-shaped — server route is /cache/{guid:path}
        so embedded slashes (after URL decoding) still match."""
        # Round-trip a guid that has a slash. We encode it client-side in
        # SharedCacheClient._url_for; the TestClient handles encoding too.
        guid = "https://x.example/ep/42"
        client.post(f"/cache/{guid}", headers=_auth(), json={"content": "# ep"})
        get = client.get(f"/cache/{guid}", headers=_auth())
        assert get.status_code == 200
        assert get.json()["content"] == "# ep"


def test_missing_token_at_startup_blocks_app():
    """If SHARED_CACHE_TOKEN isn't set, the lifespan must refuse to start —
    otherwise the service would silently accept anonymous writes from the
    Internet. (The actual import succeeds; the failure is at app startup.)"""
    os.environ.pop("SHARED_CACHE_TOKEN", None)
    import server.cache_sidecar as mod

    importlib.reload(mod)
    # The error fires when uvicorn enters the lifespan, which TestClient
    # triggers via its __enter__. Catch the RuntimeError from there.
    with pytest.raises((RuntimeError, Exception)), TestClient(mod.app):
        pass
