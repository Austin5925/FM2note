"""Integration tests for POST /api/transcribe + SSE stream."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.transcribe_flow import TranscribeOutcome
from src.web.app import create_app
from src.web.progress import reset_bus


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        f'vault_path: "{tmp_path}"\npodcast_dir: "Podcasts"\n', encoding="utf-8"
    )
    reset_bus()
    with TestClient(create_app()) as c:
        yield c


class TestPreview:
    def test_preview_requires_url(self, client):
        r = client.get("/api/episode/preview", params={"url": ""})
        assert r.status_code == 400

    def test_preview_direct_url_returns_passthrough(self, client):
        with patch(
            "src.transcribe_flow._resolve_episode_url",
            AsyncMock(return_value=("http://x/y.mp3", None, None, "", None)),
        ):
            r = client.get("/api/episode/preview", params={"url": "http://x/y.mp3"})
            assert r.status_code == 200
            body = r.json()
            assert body["audio_url"] == "http://x/y.mp3"
            assert body["source"] == "direct"

    def test_preview_swallows_errors(self, client):
        with patch(
            "src.transcribe_flow._resolve_episode_url",
            AsyncMock(side_effect=ValueError("parse failed")),
        ):
            r = client.get("/api/episode/preview", params={"url": "http://x/y.mp3"})
            assert r.status_code == 200
            body = r.json()
            assert "error" in body


class TestTranscribeSubmit:
    def test_missing_url_returns_400(self, client):
        r = client.post("/api/transcribe", json={})
        assert r.status_code == 400

    def test_submit_returns_task_id(self, client, tmp_path):
        async def fake_flow(url, config, **kwargs):
            cb = kwargs.get("progress_callback")
            if cb:
                cb("resolve", "start", "")
                cb("resolve", "done", "T")
                cb("subtitle_check", "skipped", "")
                cb("asr", "start", "")
                cb("asr", "done", "10 字")
                cb("summary", "skipped", "")
                cb("write", "start", "")
                cb("write", "done", "/tmp/x.md")
            return TranscribeOutcome(
                note_path=Path("/tmp/x.md"),
                title="T",
                podcast_name="P",
                char_count=10,
                paragraph_count=1,
                elapsed_ms=123,
                summary_failed=False,
            )

        with patch("src.web.routes.transcribe.transcribe_single_url", side_effect=fake_flow):
            r = client.post("/api/transcribe", json={"url": "http://x/y.mp3"})
            assert r.status_code == 200
            body = r.json()
            assert "task_id" in body
            assert len(body["task_id"]) == 32  # uuid4 hex


class TestSseStream:
    def test_unknown_task_id_404(self, client):
        r = client.get("/api/transcribe/nonexistent/stream")
        assert r.status_code == 404

    def test_full_stream_emits_progress_and_end(self, client):
        async def fake_flow(url, config, **kwargs):
            cb = kwargs["progress_callback"]
            # Simulate stage events without I/O delay
            cb("resolve", "start", "")
            cb("resolve", "done", "Title")
            cb("subtitle_check", "skipped", "")
            cb("asr", "start", "")
            cb("asr", "done", "5 字 · 1 段")
            cb("summary", "skipped", "")
            cb("write", "start", "")
            cb("write", "done", "/tmp/x.md")
            await asyncio.sleep(0)
            return TranscribeOutcome(
                note_path=Path("/tmp/x.md"),
                title="Title",
                podcast_name="P",
                char_count=5,
                paragraph_count=1,
                elapsed_ms=10,
                summary_failed=False,
            )

        with patch("src.web.routes.transcribe.transcribe_single_url", side_effect=fake_flow):
            r = client.post("/api/transcribe", json={"url": "http://x/y.mp3"})
            task_id = r.json()["task_id"]

            with client.stream("GET", f"/api/transcribe/{task_id}/stream") as stream:
                body = "".join(stream.iter_text())

        # All five stages and an end event must be present
        assert "event: progress" in body
        assert "event: end" in body
        for stage in ["resolve", "subtitle_check", "asr", "summary", "write"]:
            assert f'"stage": "{stage}"' in body
        # complete payload includes note_path
        assert "/tmp/x.md" in body

    def test_stream_emits_error_on_pipeline_failure(self, client):
        async def fake_flow(url, config, **kwargs):
            cb = kwargs["progress_callback"]
            cb("asr", "error", "boom")
            raise RuntimeError("boom")

        with patch("src.web.routes.transcribe.transcribe_single_url", side_effect=fake_flow):
            r = client.post("/api/transcribe", json={"url": "http://x/y.mp3"})
            task_id = r.json()["task_id"]

            with client.stream("GET", f"/api/transcribe/{task_id}/stream") as stream:
                body = "".join(stream.iter_text())

        assert '"status": "error"' in body
        assert "boom" in body
        assert "event: end" in body
