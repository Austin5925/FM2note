"""Integration tests for the history API."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.models import SummaryResult
from src.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        f'vault_path: "{tmp_path}"\npodcast_dir: "Podcasts"\n'
        f'db_path: "{tmp_path}/state.db"\n',
        encoding="utf-8",
    )
    with TestClient(create_app()) as c:
        yield c


class TestHistoryList:
    def test_empty_db_returns_empty_lists(self, client):
        r = client.get("/api/history")
        assert r.status_code == 200
        body = r.json()
        assert body["episodes"] == []
        assert body["pending_summaries"] == []

    def test_episodes_sorted_descending(self, client, tmp_path):
        # Insert two entries directly via sqlite
        import sqlite3

        con = sqlite3.connect(tmp_path / "state.db")
        con.execute(
            """CREATE TABLE IF NOT EXISTS processed_episodes (
                guid TEXT PRIMARY KEY,
                podcast_name TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                error_msg TEXT,
                retry_count INTEGER DEFAULT 0,
                note_path TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )"""
        )
        old_time = "2024-01-01T00:00:00"
        new_time = "2026-05-23T12:00:00"
        sql = (
            "INSERT INTO processed_episodes "
            "(guid,podcast_name,title,status,note_path,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?)"
        )
        con.executemany(
            sql,
            [
                ("g-old", "Podcast", "Old Title", "done", "/tmp/old.md", old_time, old_time),
                ("g-new", "Podcast", "New Title", "done", "/tmp/new.md", new_time, new_time),
            ],
        )
        con.commit()
        con.close()

        r = client.get("/api/history")
        assert r.status_code == 200
        eps = r.json()["episodes"]
        assert len(eps) == 2
        assert eps[0]["title"] == "New Title"
        assert eps[1]["title"] == "Old Title"

    def test_pending_summary_reported(self, client, tmp_path):
        pending_dir = tmp_path / "data" / "pending_summaries"
        pending_dir.mkdir(parents=True)
        item = {
            "guid": "abc",
            "title": "Awaiting summary",
            "podcast_name": "P",
            "text": "transcript text",
            "note_path": str(tmp_path / "note.md"),
        }
        (pending_dir / "abc12345.json").write_text(json.dumps(item), encoding="utf-8")
        # PENDING_DIR is a module-level relative path, hence chdir was set
        r = client.get("/api/history")
        body = r.json()
        assert len(body["pending_summaries"]) == 1
        assert body["pending_summaries"][0]["title"] == "Awaiting summary"
        assert body["pending_summaries"][0]["id"] == "abc12345"


class TestRetrySummary:
    def test_missing_id_returns_400(self, client):
        r = client.post("/api/history/retry-summary", json={})
        assert r.status_code == 400

    def test_no_summarizer_configured_returns_409(self, client):
        r = client.post("/api/history/retry-summary", json={"id": "anything"})
        assert r.status_code == 409
        assert "未配置" in r.json()["detail"]

    def test_not_found(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("POE_API_KEY", "pk-test")
        # Build pending dir so the retry endpoint can search it
        (tmp_path / "data" / "pending_summaries").mkdir(parents=True)
        # "deadbeef" is valid hex but no such file exists → 404
        r = client.post("/api/history/retry-summary", json={"id": "deadbeef"})
        assert r.status_code == 404

    def test_invalid_id_rejected(self, client, monkeypatch, tmp_path):
        """Path-traversal payloads must be rejected before any filesystem access."""
        monkeypatch.setenv("POE_API_KEY", "pk-test")
        (tmp_path / "data" / "pending_summaries").mkdir(parents=True)
        for bad in ["../etc", "abc/def", "../../passwd", "not-hex"]:
            r = client.post("/api/history/retry-summary", json={"id": bad})
            assert r.status_code == 400, f"expected 400 for {bad!r}, got {r.status_code}"

    def test_happy_path_marks_retried(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("POE_API_KEY", "pk-test")
        pending_dir = tmp_path / "data" / "pending_summaries"
        pending_dir.mkdir(parents=True)
        note_path = tmp_path / "note.md"
        note_path.write_text("# Note\n\n## 全文转写\nbody\n", encoding="utf-8")
        (pending_dir / "abcd.json").write_text(
            json.dumps(
                {
                    "guid": "g",
                    "title": "T",
                    "podcast_name": "P",
                    "text": "text",
                    "note_path": str(note_path),
                }
            ),
            encoding="utf-8",
        )

        fake_summarizer = type("X", (), {})()
        fake_summarizer.summarize = AsyncMock(
            return_value=SummaryResult(summary="The summary.", chapters=None, keywords=None)
        )
        with patch(
            "src.web.routes.history.create_summarizer", return_value=fake_summarizer
        ):
            r = client.post("/api/history/retry-summary", json={"id": "abcd"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        # Pending file removed
        assert not (pending_dir / "abcd.json").exists()
