"""Integration tests for subscriptions API + RSS test endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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


def _fake_feed(title: str):
    fake_feed = type("F", (), {})()
    fake_feed.bozo = 0
    fake_feed.entries = []
    fake_feed.feed = {"title": title}
    return fake_feed


def test_defaults_use_personal_rsshub_fallback(client):
    r = client.get("/api/subscriptions/defaults")
    assert r.status_code == 200
    assert r.json()["rsshub_base"] == "https://macroclaw.app/rsshub"


def test_defaults_extract_existing_rsshub_base(client, tmp_path):
    (tmp_path / "config" / "subscriptions.yaml").write_text(
        "podcasts:\n"
        "  - name: x\n"
        "    rss_url: https://example.com/rsshub/xiaoyuzhou/podcast/abc123\n",
        encoding="utf-8",
    )
    r = client.get("/api/subscriptions/defaults")
    assert r.status_code == 200
    assert r.json()["rsshub_base"] == "https://example.com/rsshub"


def test_resolve_xiaoyuzhou_podcast_url_uses_default_rsshub(client):
    with patch("feedparser.parse", return_value=_fake_feed("非共识的20分钟")):
        r = client.post(
            "/api/subscriptions/resolve",
            json={"input": "https://www.xiaoyuzhoufm.com/podcast/6978a31df828d4e9f2787d3d"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["kind"] == "xiaoyuzhou"
    assert body["name"] == "非共识的20分钟"
    assert (
        body["rss_url"]
        == "https://macroclaw.app/rsshub/xiaoyuzhou/podcast/6978a31df828d4e9f2787d3d"
    )


def test_resolve_xiaoyuzhou_share_text_extracts_podcast_url(client):
    with patch("feedparser.parse", return_value=_fake_feed("支无不言")):
        r = client.post(
            "/api/subscriptions/resolve",
            json={
                "input": "我在小宇宙发现了一个播客 https://www.xiaoyuzhoufm.com/podcast/681b47122ad01a51a21cd515?utm_source=copy_link"
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["podcast_id"] == "681b47122ad01a51a21cd515"
    assert body["name"] == "支无不言"


def test_resolve_xiaoyuzhou_episode_url_extracts_series(client):
    html = """
    <script type="application/ld+json">
      {"partOfSeries":{"name":"从剧集页来的播客","url":"https://www.xiaoyuzhoufm.com/podcast/podcast123"}}
    </script>
    """
    with (
        patch(
            "src.web.services.subscription_resolver._fetch_xiaoyuzhou_html",
            new=AsyncMock(return_value=html),
        ),
        patch("feedparser.parse", return_value=_fake_feed("从剧集页来的播客")),
    ):
        r = client.post(
            "/api/subscriptions/resolve",
            json={"input": "https://www.xiaoyuzhoufm.com/episode/episode123"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["podcast_id"] == "podcast123"
    assert body["rss_url"] == "https://macroclaw.app/rsshub/xiaoyuzhou/podcast/podcast123"


def test_resolve_existing_rsshub_url_preserves_url(client):
    url = "https://macroclaw.app/rsshub/xiaoyuzhou/podcast/existing123"
    with patch("feedparser.parse", return_value=_fake_feed("已有 RSSHub")):
        r = client.post("/api/subscriptions/resolve", json={"input": url})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["rss_url"] == url
    assert body["rsshub_base"] == "https://macroclaw.app/rsshub"


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
