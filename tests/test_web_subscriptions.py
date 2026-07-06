"""Integration tests for subscriptions API + RSS test endpoint."""

from __future__ import annotations

from types import SimpleNamespace
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


@pytest.fixture
def client_with_state(tmp_path, monkeypatch):
    """Like ``client`` but also seeds a config.yaml so backfill flows that
    open the state DB / load_config can run end-to-end."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "subscriptions.yaml").write_text(
        "podcasts:\n  - name: existing\n    rss_url: https://feed.example/rss\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "config.yaml").write_text(
        f'vault_path: "{tmp_path}"\n'
        f'podcast_dir: "Podcasts"\n'
        f'db_path: "{tmp_path / "data" / "state.db"}"\n'
        'asr_engine: "funasr"\n',
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


def test_add_appends_and_preserves_comment(client_with_state, tmp_path):
    # v1.5.4: strategy="all" now seeds 'pending' rows in state.db to defeat
    # daemon auto-protect (FAIL d). Requires state DB + a valid feed mock.
    feed = _fake_feed_with_entries(
        ("g-new-1", "Ep 1", "Mon, 01 May 2026 10:00:00 +0000", 3600),
    )
    # Re-seed subscriptions.yaml with the comment we want to verify roundtrip on.
    (tmp_path / "config" / "subscriptions.yaml").write_text(
        "# top-level comment\npodcasts:\n"
        "  - name: existing\n"
        "    rss_url: https://feed.example/rss\n"
        "    tags: [x]\n",
        encoding="utf-8",
    )
    payload = {
        "name": "new",
        "rss_url": "https://feed.example/new",
        "tags": ["a", "b"],
        "backfill_strategy": "all",
    }
    with patch("feedparser.parse", return_value=feed):
        r = client_with_state.post("/api/subscriptions", json=payload)
    assert r.status_code == 200, r.json()
    text = (tmp_path / "config" / "subscriptions.yaml").read_text(encoding="utf-8")
    assert "# top-level comment" in text
    assert "new" in text
    assert "existing" in text


def test_add_rejects_missing_fields(client):
    r = client.post("/api/subscriptions", json={"name": "x"})
    assert r.status_code == 400


def test_add_requires_backfill_strategy(client):
    """v1.4.15 — explicit backfill strategy is mandatory to prevent silent
    quota burn on a new subscription's historical episodes."""
    r = client.post(
        "/api/subscriptions",
        json={"name": "x", "rss_url": "https://feed.example/x"},
    )
    assert r.status_code == 400
    assert "backfill_strategy" in r.json()["detail"]


def test_add_rejects_invalid_backfill_strategy(client):
    r = client.post(
        "/api/subscriptions",
        json={
            "name": "x",
            "rss_url": "https://feed.example/x",
            "backfill_strategy": "yolo",
        },
    )
    assert r.status_code == 400


def test_add_recent_n_requires_int(client):
    r = client.post(
        "/api/subscriptions",
        json={
            "name": "x",
            "rss_url": "https://feed.example/x",
            "backfill_strategy": "recent_n",
        },
    )
    assert r.status_code == 400
    assert "recent_n" in r.json()["detail"]


def test_add_recent_n_rejects_negative_and_zero(client):
    """Code Review I4 (v1.4.15): without a >=1 guard, -5 silently clamped to
    0 (skip everything) while the response still said strategy=recent_n."""
    for bad in (-5, 0):
        r = client.post(
            "/api/subscriptions",
            json={
                "name": "x",
                "rss_url": "https://feed.example/x",
                "backfill_strategy": "recent_n",
                "recent_n": bad,
            },
        )
        assert r.status_code == 400, (bad, r.json())
        assert "正整数" in r.json()["detail"]


def test_add_rejects_non_http_scheme(client):
    """Codex audit BUG 10 (v1.4.15): rss_url goes to feedparser which does
    its own fetch — must reject file:// / gopher:// / javascript: before that."""
    for evil in (
        "file:///etc/passwd",
        "gopher://example.com/x",
        "javascript:alert(1)",
        "ftp://example.com/feed.xml",
    ):
        r = client.post(
            "/api/subscriptions",
            json={
                "name": "x",
                "rss_url": evil,
                "backfill_strategy": "all",
            },
        )
        assert r.status_code == 400, (evil, r.json())
        assert "协议" in r.json()["detail"] or "主机名" in r.json()["detail"]


def test_add_since_date_requires_iso(client):
    r = client.post(
        "/api/subscriptions",
        json={
            "name": "x",
            "rss_url": "https://feed.example/x",
            "backfill_strategy": "since_date",
        },
    )
    assert r.status_code == 400
    assert "since_date" in r.json()["detail"]


def _fake_feed_with_entries(*entries):
    """Build a feedparser-shaped object from (guid, title, pub_date, duration_sec) tuples."""

    def _mk(g, t, p, d):
        return SimpleNamespace(
            id=g,
            link=g,
            title=t,
            published=p,
            enclosures=[{"href": f"https://audio.example/{g}.mp3"}],
            itunes_duration=str(d) if d else "",
        )

    return SimpleNamespace(
        bozo=0,
        bozo_exception=None,
        entries=[_mk(*e) for e in entries],
        feed=SimpleNamespace(get=lambda k, default="": "Fake Feed"),
    )


def test_preview_returns_count_and_cost(client_with_state):
    feed = _fake_feed_with_entries(
        ("g1", "Ep 1", "Mon, 01 May 2026 10:00:00 +0000", 3600),
        ("g2", "Ep 2", "Mon, 08 May 2026 10:00:00 +0000", 1800),
    )
    with patch("feedparser.parse", return_value=feed):
        r = client_with_state.post(
            "/api/subscriptions/preview",
            json={"rss_url": "https://feed.example/x"},
        )
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["ok"] is True
    assert body["episode_count"] == 2
    assert body["unprocessed_count"] == 2
    assert body["total_duration_sec"] == 5400
    assert body["estimated_cost_cny"] > 0
    assert body["asr_engine"] == "funasr"
    assert len(body["episodes"]) == 2


def test_preview_counts_only_unprocessed_episodes(client_with_state, tmp_path):
    """v1.6.4: preview must await state checks in a normal loop, not inside a
    generator expression. Otherwise Python builds an async_generator, the
    endpoint logs TypeError, and the UI falls back to episode_count."""
    import asyncio

    from src.monitor.state import StateManager

    async def _seed_done():
        state = StateManager(str(tmp_path / "data" / "state.db"))
        await state.init()
        try:
            await state.mark_status(
                "g1",
                "done",
                podcast_name="Fake Feed",
                title="Already Done",
                note_path=str(tmp_path / "note.md"),
            )
        finally:
            await state.close()

    asyncio.run(_seed_done())

    feed = _fake_feed_with_entries(
        ("g1", "Already Done", "Mon, 01 May 2026 10:00:00 +0000", 3600),
        ("g2", "Needs Work", "Mon, 08 May 2026 10:00:00 +0000", 1800),
    )
    with patch("feedparser.parse", return_value=feed):
        r = client_with_state.post(
            "/api/subscriptions/preview",
            json={"rss_url": "https://feed.example/x"},
        )
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["episode_count"] == 2
    assert body["unprocessed_count"] == 1


def test_preview_rejects_non_http(client_with_state):
    r = client_with_state.post(
        "/api/subscriptions/preview",
        json={"rss_url": "file:///etc/passwd"},
    )
    assert r.status_code == 200  # endpoint returns 200 ok=false on bad scheme
    assert r.json()["ok"] is False


def test_add_new_only_marks_all_episodes_skipped(client_with_state, tmp_path):
    """End-to-end: strategy=new_only must populate state.db with
    ``backfill_skipped`` so the next poll treats existing episodes as already
    processed and skips ASR entirely."""
    feed = _fake_feed_with_entries(
        ("g1", "Ep 1", "Mon, 01 May 2026 10:00:00 +0000", 3600),
        ("g2", "Ep 2", "Mon, 08 May 2026 10:00:00 +0000", 1800),
        ("g3", "Ep 3", "Mon, 15 May 2026 10:00:00 +0000", 0),
    )
    with patch("feedparser.parse", return_value=feed):
        r = client_with_state.post(
            "/api/subscriptions",
            json={
                "name": "new",
                "rss_url": "https://feed.example/n",
                "backfill_strategy": "new_only",
            },
        )
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["backfill_strategy"] == "new_only"
    assert body["backfill_skipped_count"] == 3

    # Verify state.db rows actually exist and is_processed returns True
    import asyncio

    from src.monitor.state import StateManager

    async def _check():
        state = StateManager(str(tmp_path / "data" / "state.db"))
        await state.init()
        try:
            return [await state.is_processed(g) for g in ("g1", "g2", "g3")]
        finally:
            await state.close()

    assert asyncio.run(_check()) == [True, True, True]


def test_add_recent_n_keeps_n_newest(client_with_state, tmp_path):
    """strategy=recent_n keeps the N most-recent for processing, marks the rest
    as backfill_skipped."""
    feed = _fake_feed_with_entries(
        ("g_old", "Old", "Mon, 01 Jan 2026 10:00:00 +0000", 1800),
        ("g_mid", "Mid", "Mon, 01 Mar 2026 10:00:00 +0000", 1800),
        ("g_new", "New", "Mon, 01 May 2026 10:00:00 +0000", 1800),
    )
    with patch("feedparser.parse", return_value=feed):
        r = client_with_state.post(
            "/api/subscriptions",
            json={
                "name": "n",
                "rss_url": "https://feed.example/n",
                "backfill_strategy": "recent_n",
                "recent_n": 1,
            },
        )
    assert r.status_code == 200, r.json()
    assert r.json()["backfill_skipped_count"] == 2  # old + mid skipped

    import asyncio

    from src.monitor.state import StateManager

    async def _check():
        state = StateManager(str(tmp_path / "data" / "state.db"))
        await state.init()
        try:
            return {g: await state.is_processed(g) for g in ("g_old", "g_mid", "g_new")}
        finally:
            await state.close()

    seen = asyncio.run(_check())
    assert seen["g_old"] is True
    assert seen["g_mid"] is True
    assert seen["g_new"] is False  # newest is left for the daemon to transcribe


def test_add_duplicate_url_returns_409(client_with_state, tmp_path):
    """Code Review I1 (v1.4.15): concurrent or repeat POSTs of the same
    rss_url must NOT produce duplicate subscription rows. The fixture seeds
    one subscription at https://feed.example/rss; a re-add must 409."""
    r = client_with_state.post(
        "/api/subscriptions",
        json={
            "name": "duplicate",
            "rss_url": "https://feed.example/rss",
            "backfill_strategy": "all",
        },
    )
    assert r.status_code == 409, r.json()
    text = (tmp_path / "config" / "subscriptions.yaml").read_text(encoding="utf-8")
    # The yaml still has just the one existing entry (no duplicate appended)
    assert text.count("https://feed.example/rss") == 1


def test_add_aborts_when_feed_fails_for_non_all_strategy(client_with_state, tmp_path):
    """Codex audit BUG 11 (v1.4.15): if feedparser returns a bozo-empty feed
    while strategy is anything other than 'all', the add MUST abort. Otherwise
    the subscription would sit in yaml with zero skip-marks and the next
    poll would re-transcribe every historical episode — exactly the burn
    this version was built to prevent."""
    from types import SimpleNamespace

    bad_feed = SimpleNamespace(
        bozo=1,
        bozo_exception=Exception("network unreachable"),
        entries=[],
        feed=SimpleNamespace(get=lambda k, default="": ""),
    )
    with patch("feedparser.parse", return_value=bad_feed):
        r = client_with_state.post(
            "/api/subscriptions",
            json={
                "name": "fragile",
                "rss_url": "https://feed.example/fragile",
                "backfill_strategy": "new_only",
            },
        )
    assert r.status_code == 502, r.json()
    assert "未保存" in r.json()["detail"]
    # yaml must NOT have been touched — still just the fixture's seed entry
    text = (tmp_path / "config" / "subscriptions.yaml").read_text(encoding="utf-8")
    assert "fragile" not in text


def test_add_all_strategy_502_when_feed_fails(client_with_state, tmp_path):
    """v1.5.4: strategy='all' now seeds 'pending' rows in state.db to defeat
    the daemon auto-protect (which would otherwise silently mark every episode
    as ``backfill_skipped`` on next poll → flipping "all" into "skip all").
    That seeding requires a valid feed; a flaky feed now raises 502 so the
    user can retry instead of getting a silent reversal. Symmetric with the
    non-``all`` strategies, contrary to the v1.4.15 design but required by
    v1.5.4 daemon auto-protect (Codex audit FAIL d)."""
    from types import SimpleNamespace

    bad_feed = SimpleNamespace(
        bozo=1,
        bozo_exception=Exception("dead"),
        entries=[],
        feed=SimpleNamespace(get=lambda k, default="": ""),
    )
    with patch("feedparser.parse", return_value=bad_feed):
        r = client_with_state.post(
            "/api/subscriptions",
            json={
                "name": "later",
                "rss_url": "https://feed.example/later",
                "backfill_strategy": "all",
            },
        )
    assert r.status_code == 502, r.json()
    # yaml must NOT have been touched
    text = (tmp_path / "config" / "subscriptions.yaml").read_text(encoding="utf-8")
    assert "later" not in text


def test_add_all_strategy_seeds_pending_to_defeat_auto_protect(client_with_state, tmp_path):
    """v1.5.4: strategy='all' writes a ``pending`` row per current feed
    episode so the daemon auto-protect (which fires when state.db has zero
    rows for a sub) doesn't subsequently turn "all" into "skip all".

    backfill_skipped_count is still 0 (nothing got skipped — that's the
    point of strategy=all). But state.db should have N pending rows after.
    """
    feed = _fake_feed_with_entries(
        ("g1", "Ep 1", "Mon, 01 May 2026 10:00:00 +0000", 3600),
        ("g2", "Ep 2", "Tue, 02 May 2026 10:00:00 +0000", 1800),
    )
    with patch("feedparser.parse", return_value=feed):
        r = client_with_state.post(
            "/api/subscriptions",
            json={
                "name": "a",
                "rss_url": "https://feed.example/a",
                "backfill_strategy": "all",
            },
        )
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["backfill_skipped_count"] == 0

    # Now hit the same StateManager singleton the route used. The seeded rows
    # must exist with status=pending so:
    #  (a) has_any_recorded_in returns True for daemon auto-protect
    #  (b) is_processed returns False so daemon STILL transcribes them
    import asyncio

    from src.web.services.state_singleton import get_state_manager

    async def _check():
        state = await get_state_manager(str(tmp_path / "data" / "state.db"))
        assert await state.has_any_recorded_in(["g1"]) is True
        assert await state.is_processed("g1") is False
        assert await state.is_processed("g2") is False

    asyncio.run(_check())


def test_update_modifies_in_place(client, tmp_path):
    payload = {"name": "renamed", "rss_url": "https://feed.example/r", "tags": []}
    r = client.put("/api/subscriptions/0", json=payload)
    assert r.status_code == 200
    text = (tmp_path / "config" / "subscriptions.yaml").read_text(encoding="utf-8")
    assert "renamed" in text
    assert "existing" not in text


def test_update_out_of_range_returns_404(client):
    # Use a valid-looking URL so the scheme guard (added in v1.4.15) doesn't
    # 400 us before we reach the index check.
    r = client.put(
        "/api/subscriptions/9",
        json={"name": "x", "rss_url": "https://x.example/feed"},
    )
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


def test_defaults_are_empty_for_public_build(client):
    r = client.get("/api/subscriptions/defaults")
    assert r.status_code == 200
    assert r.json()["rsshub_base"] == ""


def test_defaults_use_env_rsshub_base(client, monkeypatch):
    monkeypatch.setenv("FM2NOTE_RSSHUB_BASE", "https://macroclaw.app/rsshub/")
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
            json={
                "input": "https://www.xiaoyuzhoufm.com/podcast/6978a31df828d4e9f2787d3d",
                "rsshub_base": "https://macroclaw.app/rsshub",
            },
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
                "input": "我在小宇宙发现了一个播客 https://www.xiaoyuzhoufm.com/podcast/681b47122ad01a51a21cd515?utm_source=copy_link",
                "rsshub_base": "https://macroclaw.app/rsshub",
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
            json={
                "input": "https://www.xiaoyuzhoufm.com/episode/episode123",
                "rsshub_base": "https://macroclaw.app/rsshub",
            },
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
