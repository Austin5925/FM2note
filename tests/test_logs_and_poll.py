"""v1.5.3 tests: /api/logs ring buffer + /api/service/poll-now spawn."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from src.web.app import create_app
from src.web.services.log_buffer import (
    ensure_buffer_installed,
    get_logs,
    uninstall_buffer,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        f'vault_path: "{tmp_path}"\n'
        'podcast_dir: ""\n'
        'asr_engine: "funasr"\n'
        f'db_path: "{tmp_path / "state.db"}"\n',
        encoding="utf-8",
    )
    with TestClient(create_app()) as c:
        yield c


class TestLogBuffer:
    def setup_method(self):
        uninstall_buffer()

    def teardown_method(self):
        uninstall_buffer()

    def test_ensure_buffer_installed_is_idempotent(self):
        ensure_buffer_installed()
        ensure_buffer_installed()  # no-op second time
        # Should not crash — buffer is still functional
        logger.info("hello")
        records = get_logs()
        assert any("hello" in r["message"] for r in records)

    def test_after_seq_filters_correctly(self):
        ensure_buffer_installed()
        logger.info("first")
        before = get_logs()
        cutoff = before[-1]["seq"] if before else 0
        logger.info("second")
        logger.info("third")
        after = get_logs(after_seq=cutoff)
        msgs = [r["message"] for r in after]
        assert "first" not in msgs
        assert "second" in msgs
        assert "third" in msgs

    def test_buffer_is_bounded(self):
        ensure_buffer_installed()
        for i in range(50):
            logger.info(f"msg {i}")
        records = get_logs(limit=10)
        assert len(records) <= 10

    def test_uninstall_resets_seq(self):
        """v1.5.3 Code Review C1 fix: uninstall_buffer() must reset _seq so
        the after_seq filter in the next test starts from a clean baseline."""
        import src.web.services.log_buffer as lb

        ensure_buffer_installed()
        for i in range(5):
            logger.info(f"a{i}")
        assert lb._seq >= 5
        uninstall_buffer()
        assert lb._seq == 0
        # After reinstall, seqs start fresh
        ensure_buffer_installed()
        logger.info("fresh")
        records = get_logs()
        assert records[-1]["seq"] == 1

    def test_seq_strictly_monotonic_across_appends(self):
        """v1.5.3 Code Review I1 fix: seq assignment + deque.append are now
        in one lock so the deque is always seq-sorted (no out-of-order
        appends from concurrent writers can ever break after_seq filtering)."""
        ensure_buffer_installed()
        for i in range(20):
            logger.info(f"line {i}")
        records = get_logs()
        seqs = [r["seq"] for r in records]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)  # all unique


class TestLogsEndpoint:
    def test_logs_endpoint_returns_records(self, client):
        # The lifespan hook installs the buffer, so any log fired during
        # the request becomes visible.
        logger.info("test-marker-logs-endpoint")
        r = client.get("/api/logs")
        assert r.status_code == 200
        body = r.json()
        assert "records" in body
        assert "next_after_seq" in body
        assert any("test-marker" in rec["message"] for rec in body["records"])

    def test_logs_endpoint_after_seq_no_records(self, client):
        # Bump past all current records — should get an empty list, not 404
        r1 = client.get("/api/logs")
        last = r1.json()["next_after_seq"]
        r2 = client.get(f"/api/logs?after_seq={last + 1_000_000}")
        assert r2.status_code == 200
        assert r2.json()["records"] == []


class TestPollNowEndpoint:
    def test_poll_now_spawns_subprocess(self, client, monkeypatch):
        """Endpoint should fire-and-forget — return 200 without waiting
        for the spawned subprocess to finish."""
        monkeypatch.setattr("platform.system", lambda: "Darwin")
        calls = []

        class _FakePopen:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))

        with patch("src.web.routes.service.subprocess.Popen", _FakePopen):
            r = client.post("/api/service/poll-now")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert calls, "Popen should have been called"
        assert calls[0][0][0][-1] == "run-once"
        assert calls[0][1]["start_new_session"] is True

    def test_poll_now_in_frozen_app_uses_launcher_cli_mode(self, client, monkeypatch):
        """Desktop app must spawn run-once without opening a second app window."""
        monkeypatch.setattr("platform.system", lambda: "Darwin")

        from src.web.routes import service as svc_mod

        monkeypatch.setattr(svc_mod.sys, "frozen", True, raising=False)
        monkeypatch.setattr(svc_mod.sys, "executable", "/App/FM2note.app/Contents/MacOS/FM2note")
        calls = []

        class _FakePopen:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))

        with patch("src.web.routes.service.subprocess.Popen", _FakePopen):
            r = client.post("/api/service/poll-now")

        assert r.status_code == 200
        assert calls[0][0][0] == ["/App/FM2note.app/Contents/MacOS/FM2note", "run-once"]

    def test_poll_now_rejected_on_unsupported_platform(self, client, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Windows")
        r = client.post("/api/service/poll-now")
        assert r.status_code == 400


class TestServiceStatusActivity:
    """v1.5.3: /api/service/status now also returns last_run_at /
    next_run_estimate_at / poll_interval_hours so the header chip can
    render daemon health."""

    def test_status_includes_activity_fields(self, client, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Linux")
        r = client.get("/api/service/status")
        body = r.json()
        # These keys must always be present (may be None on fresh install)
        assert "last_run_at" in body
        assert "next_run_estimate_at" in body
        assert "poll_interval_hours" in body
        assert "desktop_app" in body
