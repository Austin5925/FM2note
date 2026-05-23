"""Integration tests for subscriptions API + RSS test endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    # Seed a subscriptions file with a comment to verify roundtrip preservation
    (tmp_path / "config" / "subscriptions.yaml").write_text(
        "# top-level comment\npodcasts:\n"
        "  - name: existing\n"
        "    rss_url: https://feed.example/rss\n"
        "    tags: [x]\n",
        encoding="utf-8",
    )
    with TestClient(create_app()) as c:
        yield c


def test_list_returns_existing(client):
    r = client.get("/api/subscriptions")
    assert r.status_code == 200
    subs = r.json()["subscriptions"]
    assert len(subs) == 1
    assert subs[0]["name"] == "existing"
    assert subs[0]["index"] == 0


def test_add_appends_and_preserves_comment(client, tmp_path):
    payload = {"name": "new", "rss_url": "https://feed.example/new", "tags": ["a", "b"]}
    r = client.post("/api/subscriptions", json=payload)
    assert r.status_code == 200
    text = (tmp_path / "config" / "subscriptions.yaml").read_text(encoding="utf-8")
    assert "# top-level comment" in text
    assert "new" in text
    assert "existing" in text


def test_add_rejects_missing_fields(client):
    r = client.post("/api/subscriptions", json={"name": "x"})
    assert r.status_code == 400


def test_update_modifies_in_place(client, tmp_path):
    payload = {"name": "renamed", "rss_url": "https://feed.example/r", "tags": []}
    r = client.put("/api/subscriptions/0", json=payload)
    assert r.status_code == 200
    text = (tmp_path / "config" / "subscriptions.yaml").read_text(encoding="utf-8")
    assert "renamed" in text
    assert "existing" not in text


def test_update_out_of_range_returns_404(client):
    r = client.put("/api/subscriptions/9", json={"name": "x", "rss_url": "x"})
    assert r.status_code == 404


def test_delete_removes_entry(client):
    r = client.delete("/api/subscriptions/0")
    assert r.status_code == 200
    assert r.json()["removed"]["name"] == "existing"

    r2 = client.get("/api/subscriptions")
    assert r2.json()["subscriptions"] == []


def test_test_endpoint_happy_path(client):
    fake_feed = type("F", (), {})()
    fake_feed.bozo = 0
    fake_feed.entries = [type("E", (), {"get": staticmethod(lambda k, d="": "latest ep")})()]
    fake_feed.feed = type("FF", (), {"get": staticmethod(lambda k, d="": "Feed Name")})()
    with patch("feedparser.parse", return_value=fake_feed):
        r = client.post("/api/subscriptions/test", json={"rss_url": "https://x/feed"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["feed_title"] == "Feed Name"
    assert body["latest_title"] == "latest ep"


def test_test_endpoint_invalid_feed(client):
    fake_feed = type("F", (), {})()
    fake_feed.bozo = 1
    fake_feed.bozo_exception = "Not XML"
    fake_feed.entries = []
    with patch("feedparser.parse", return_value=fake_feed):
        r = client.post("/api/subscriptions/test", json={"rss_url": "https://x/bad"})
    body = r.json()
    assert body["ok"] is False
    assert "无法解析" in body["error"]


def test_test_endpoint_requires_url(client):
    r = client.post("/api/subscriptions/test", json={})
    assert r.status_code == 400


def test_test_endpoint_rejects_file_scheme(client):
    r = client.post("/api/subscriptions/test", json={"rss_url": "file:///etc/passwd"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "不支持的协议" in body["error"]


def test_test_endpoint_rejects_javascript_scheme(client):
    r = client.post("/api/subscriptions/test", json={"rss_url": "javascript:alert(1)"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_test_endpoint_rejects_url_without_host(client):
    r = client.post("/api/subscriptions/test", json={"rss_url": "http:///"})
    assert r.status_code == 200
    assert r.json()["ok"] is False
