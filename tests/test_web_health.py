"""Tests for the health check + service status endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        f'vault_path: "{tmp_path}"\npodcast_dir: "Podcasts"\nasr_engine: "funasr"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("POE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ALIYUN_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIYUN_ACCESS_KEY_SECRET", raising=False)
    with TestClient(create_app()) as c:
        yield c


class TestHealthCheck:
    def test_minimal_config_no_keys(self, client):
        r = client.get("/api/health-check")
        assert r.status_code == 200
        body = r.json()
        labels = {it["label"]: it["ok"] for it in body["items"]}
        assert labels["配置文件可读"] is True
        assert labels["Obsidian Vault 路径"] is True
        # Without DashScope key, DashScope check fails and overall is not ok
        assert labels["DashScope 语音 Key"] is False
        assert body["overall_ok"] is False

    def test_with_dashscope_and_poe_keys(self, client, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
        monkeypatch.setenv("POE_API_KEY", "pk-test")
        r = client.get("/api/health-check")
        body = r.json()
        labels = {it["label"]: it["ok"] for it in body["items"]}
        assert labels["DashScope 语音 Key"] is True
        assert labels["AI 摘要"] is True

    def test_invalid_vault_path(self, client, tmp_path):
        # Overwrite config with a non-existent vault
        (tmp_path / "config" / "config.yaml").write_text(
            'vault_path: "/does/not/exist"\npodcast_dir: "Podcasts"\n',
            encoding="utf-8",
        )
        r = client.get("/api/health-check")
        body = r.json()
        labels = {it["label"]: it["ok"] for it in body["items"]}
        assert labels["Obsidian Vault 路径"] is False
        assert body["overall_ok"] is False

    def test_tingwu_engine_requires_app_id(self, client, tmp_path, monkeypatch):
        (tmp_path / "config" / "config.yaml").write_text(
            f'vault_path: "{tmp_path}"\nasr_engine: "tingwu"\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
        monkeypatch.delenv("TINGWU_APP_ID", raising=False)
        r = client.get("/api/health-check")
        body = r.json()
        labels = {it["label"]: it["ok"] for it in body["items"]}
        assert "TingWu App ID" in labels
        assert labels["TingWu App ID"] is False


class TestServiceStatus:
    def test_status_no_plist(self, client, monkeypatch):
        # macOS path but no plist file
        monkeypatch.setattr("platform.system", lambda: "Darwin")
        from src.web.routes import service as svc_mod

        # Point plist to a non-existent location
        nonexistent = "/tmp/__fm2note-no-such-plist__.plist"
        monkeypatch.setattr(
            svc_mod, "_macos_plist_path", lambda: __import__("pathlib").Path(nonexistent)
        )
        r = client.get("/api/service/status")
        assert r.status_code == 200
        body = r.json()
        assert body["platform"] == "darwin"
        assert body["installed"] is False
        assert body["running"] is False

    def test_status_installed_but_not_running(self, client, monkeypatch, tmp_path):
        plist = tmp_path / "fake.plist"
        plist.write_text("<?xml?>", encoding="utf-8")
        from src.web.routes import service as svc_mod

        monkeypatch.setattr("platform.system", lambda: "Darwin")
        monkeypatch.setattr(svc_mod, "_macos_plist_path", lambda: plist)
        # launchctl list returns nonzero → not running
        from subprocess import CompletedProcess

        monkeypatch.setattr(
            svc_mod.subprocess,
            "run",
            lambda *a, **kw: CompletedProcess(args=a[0], returncode=1, stdout="", stderr=""),
        )
        r = client.get("/api/service/status")
        body = r.json()
        assert body["installed"] is True
        assert body["running"] is False

    def test_status_running_with_pid(self, client, monkeypatch, tmp_path):
        plist = tmp_path / "fake.plist"
        plist.write_text("<?xml?>", encoding="utf-8")
        from src.web.routes import service as svc_mod

        monkeypatch.setattr("platform.system", lambda: "Darwin")
        monkeypatch.setattr(svc_mod, "_macos_plist_path", lambda: plist)
        stdout = '{\n\t"PID" = 12345;\n\t"Label" = "com.fm2note.serve";\n}'
        from subprocess import CompletedProcess

        monkeypatch.setattr(
            svc_mod.subprocess,
            "run",
            lambda *a, **kw: CompletedProcess(args=a[0], returncode=0, stdout=stdout, stderr=""),
        )
        r = client.get("/api/service/status")
        body = r.json()
        assert body["installed"] is True
        assert body["running"] is True
        assert body["pid"] == 12345

    def test_non_darwin_returns_unsupported(self, client, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Linux")
        r = client.get("/api/service/status")
        body = r.json()
        assert body["platform"] == "linux"
        assert body["installed"] is False


class TestErrorMessages:
    """Verify friendly error mapping."""

    def test_rate_limit_mapping(self):
        from src.web.services.error_messages import friendly_transcribe_error

        msg = friendly_transcribe_error(Exception("HTTP 429 Too Many Requests"))
        assert "限速" in msg

    def test_balance_mapping(self):
        from src.web.services.error_messages import friendly_transcribe_error

        msg = friendly_transcribe_error(Exception("Insufficient balance"))
        assert "余额" in msg or "充值" in msg

    def test_unknown_falls_back_to_type_name(self):
        from src.web.services.error_messages import friendly_transcribe_error

        msg = friendly_transcribe_error(RuntimeError("some opaque internal error"))
        assert "RuntimeError" in msg
        assert "some opaque internal error" not in msg

    def test_xiaoyuzhou_parse_failure(self):
        from src.web.services.error_messages import friendly_transcribe_error

        msg = friendly_transcribe_error(
            ValueError("Cannot extract audio URL from Xiaoyuzhou page: foo")
        )
        assert "小宇宙" in msg

    def test_permission_error_mapping(self):
        """macOS users get a hint about Full Disk Access when writing fails."""
        from src.web.services.error_messages import friendly_transcribe_error

        msg = friendly_transcribe_error(PermissionError("[Errno 13] Permission denied: '/x'"))
        assert "完全磁盘访问" in msg
        assert "PermissionError" in msg

    def test_file_not_found_mapping(self):
        from src.web.services.error_messages import friendly_transcribe_error

        msg = friendly_transcribe_error(FileNotFoundError("[Errno 2] No such file or directory"))
        assert "Vault" in msg or "目录" in msg


class TestGlobalExceptionHandler:
    def test_unhandled_returns_sanitized_500(self, monkeypatch):
        """An unhandled exception in a route must not leak the traceback to the response."""

        from src.web.app import create_app as _create

        app = _create()

        @app.get("/__boom__")
        async def boom():
            raise KeyError("sensitive-internal-detail")

        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/__boom__")
        assert r.status_code == 500
        body = r.json()
        assert "sensitive-internal-detail" not in str(body)
        assert "KeyError" in body["detail"]
