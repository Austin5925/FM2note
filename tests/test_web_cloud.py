"""Tests for the v1.6 cloud-browse + selective-download API.

We don't hit the real macroclaw sidecar — `SharedCacheClient.from_env` is
monkeypatched per-test to return either ``None`` (unconfigured) or a fake
client that produces canned ``list_items`` / ``fetch`` results.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client_unconfigured(monkeypatch, tmp_path):
    """Cache env vars absent → SharedCacheClient.from_env returns None.

    Should not crash; both endpoints should return clear "cache_unconfigured"
    signal instead of a 500.
    """
    monkeypatch.delenv("SHARED_CACHE_URL", raising=False)
    monkeypatch.delenv("SHARED_CACHE_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "subscriptions.yaml").write_text("podcasts: []\n", encoding="utf-8")
    (tmp_path / "config" / "config.yaml").write_text(
        f'vault_path: "{tmp_path}"\npodcast_dir: "Podcasts"\n', encoding="utf-8"
    )
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def client_with_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("SHARED_CACHE_URL", "https://fake-cache.example/api")
    monkeypatch.setenv("SHARED_CACHE_TOKEN", "fake-token")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "subscriptions.yaml").write_text("podcasts: []\n", encoding="utf-8")
    (tmp_path / "config" / "config.yaml").write_text(
        f'vault_path: "{tmp_path}"\npodcast_dir: "Podcasts"\n', encoding="utf-8"
    )
    with TestClient(create_app()) as c:
        yield c


def test_list_returns_unconfigured_when_env_missing(client_unconfigured):
    r = client_unconfigured.get("/api/cloud/list")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["reason"] == "cache_unconfigured"
    assert body["items"] == []
    # detail should mention the two env vars by name so the user knows what to set
    assert "SHARED_CACHE_URL" in body["detail"]
    assert "SHARED_CACHE_TOKEN" in body["detail"]


def test_download_503_when_env_missing(client_unconfigured):
    r = client_unconfigured.post("/api/cloud/download", json={"guids": ["any-guid"]})
    assert r.status_code == 503


def test_download_rejects_empty_guids(client_with_cache):
    r = client_with_cache.post("/api/cloud/download", json={"guids": []})
    assert r.status_code == 400


def test_download_rejects_overcap(client_with_cache):
    r = client_with_cache.post(
        "/api/cloud/download", json={"guids": [f"g-{i}" for i in range(101)]}
    )
    assert r.status_code == 400
    assert "100" in r.json()["detail"]


def test_list_calls_client_with_prefix(client_with_cache, monkeypatch):
    fake = AsyncMock()
    fake.list_items = AsyncMock(
        return_value=[
            {"guid": "g1", "podcast_name": "P", "title": "T1", "size": 100, "updated_at": 1},
        ]
    )
    monkeypatch.setattr("src.web.routes.cloud._client", lambda: fake)

    r = client_with_cache.get("/api/cloud/list?prefix=P&limit=10")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 1
    assert body["items"][0]["title"] == "T1"
    fake.list_items.assert_awaited_once_with(prefix="P", limit=10)


def test_download_writes_files_grouped_by_podcast(client_with_cache, monkeypatch, tmp_path):
    """End-to-end: list-then-fetch path puts the markdown at
    ``<vault>/<podcast_dir>/<podcast_name>/<title>.md``."""
    fake = AsyncMock()
    fake.list_items = AsyncMock(
        return_value=[
            {
                "guid": "guid-1",
                "podcast_name": "MyShow",
                "title": "Episode One",
                "size": 100,
                "updated_at": 1,
            }
        ]
    )
    fake.fetch = AsyncMock(return_value="# Episode One\n\nbody.")
    monkeypatch.setattr("src.web.routes.cloud._client", lambda: fake)

    r = client_with_cache.post("/api/cloud/download", json={"guids": ["guid-1"]})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["downloaded"] == 1
    expected = tmp_path / "Podcasts" / "MyShow" / "Episode One.md"
    assert expected.exists()
    assert "Episode One" in expected.read_text(encoding="utf-8")


def test_download_respects_existing_unless_overwrite(client_with_cache, monkeypatch, tmp_path):
    """Pre-existing note must NOT be clobbered without explicit overwrite=true."""
    existing = tmp_path / "Podcasts" / "P" / "T.md"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("LOCAL_EDIT_DO_NOT_LOSE", encoding="utf-8")

    fake = AsyncMock()
    fake.list_items = AsyncMock(
        return_value=[{"guid": "g", "podcast_name": "P", "title": "T", "size": 50, "updated_at": 1}]
    )
    fake.fetch = AsyncMock(return_value="REMOTE")
    monkeypatch.setattr("src.web.routes.cloud._client", lambda: fake)

    r = client_with_cache.post("/api/cloud/download", json={"guids": ["g"]})
    assert r.status_code == 200
    body = r.json()
    assert body["downloaded"] == 0
    assert body["items"][0]["reason"] == "already_exists"
    assert existing.read_text(encoding="utf-8") == "LOCAL_EDIT_DO_NOT_LOSE"

    # Now with overwrite=true → file IS replaced.
    r2 = client_with_cache.post("/api/cloud/download", json={"guids": ["g"], "overwrite": True})
    assert r2.status_code == 200
    assert r2.json()["downloaded"] == 1
    assert existing.read_text(encoding="utf-8") == "REMOTE"


def test_download_safe_filename_strips_illegal_chars(client_with_cache, monkeypatch, tmp_path):
    """Filenames with / : | etc. (legal in title, illegal on disk) must be
    sanitized to underscores — the same rule ObsidianWriter applies."""
    fake = AsyncMock()
    fake.list_items = AsyncMock(
        return_value=[
            {
                "guid": "g",
                "podcast_name": "Pod/cast:Name",
                "title": "Ep: 1 | A?B*C",
                "size": 10,
                "updated_at": 1,
            }
        ]
    )
    fake.fetch = AsyncMock(return_value="x")
    monkeypatch.setattr("src.web.routes.cloud._client", lambda: fake)

    r = client_with_cache.post("/api/cloud/download", json={"guids": ["g"]})
    assert r.status_code == 200, r.json()
    written = Path(r.json()["items"][0]["path"])
    # both / and : / | / ? / * gone
    for bad in '/\\:|*?"<>':
        assert bad not in written.name
        assert bad not in written.parent.name


def test_download_cache_miss_reported_per_item(client_with_cache, monkeypatch, tmp_path):
    """fetch returning None → per-item reason='cache_miss', not a 500."""
    fake = AsyncMock()
    fake.list_items = AsyncMock(return_value=[])
    fake.fetch = AsyncMock(return_value=None)
    monkeypatch.setattr("src.web.routes.cloud._client", lambda: fake)

    r = client_with_cache.post("/api/cloud/download", json={"guids": ["gone-1"]})
    assert r.status_code == 200
    body = r.json()
    assert body["downloaded"] == 0
    assert body["items"][0]["reason"] == "cache_miss"
