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

    def test_poe_engine_uses_poe_key_and_unlimited_balance(self, client, tmp_path, monkeypatch):
        (tmp_path / "config" / "config.yaml").write_text(
            f'vault_path: "{tmp_path}"\nasr_engine: "poe"\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("POE_API_KEY", "pk-test")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

        r = client.get("/api/health-check")

        labels = {it["label"]: it for it in r.json()["items"]}
        assert labels["Poe 语音 Key"]["ok"] is True
        assert labels["Poe 转写余额"]["hint"] == "无限（使用套餐积分）"
        assert "DashScope 语音 Key" not in labels


class TestServiceStatus:
    def test_status_no_plist(self, client, monkeypatch):
        # macOS path but no plist file
        monkeypatch.setattr("platform.system", lambda: "Darwin")
        from src import macos_service as mac_svc

        # Point plist to a non-existent location
        nonexistent = "/tmp/__fm2note-no-such-plist__.plist"
        monkeypatch.setattr(
            mac_svc, "launchd_plist_path", lambda: __import__("pathlib").Path(nonexistent)
        )
        r = client.get("/api/service/status")
        assert r.status_code == 200
        body = r.json()
        assert body["platform"] == "darwin"
        assert body["installed"] is False
        assert body["running"] is False
        assert body["auto_start_disabled"] is False

    def test_status_installed_but_not_running(self, client, monkeypatch, tmp_path):
        plist = tmp_path / "fake.plist"
        plist.write_text("<?xml?>", encoding="utf-8")
        from src import macos_service as mac_svc

        monkeypatch.setattr("platform.system", lambda: "Darwin")
        monkeypatch.setattr(mac_svc, "launchd_plist_path", lambda: plist)
        # launchctl list returns nonzero → not running
        from subprocess import CompletedProcess

        monkeypatch.setattr(
            mac_svc.subprocess,
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
        from src import macos_service as mac_svc

        monkeypatch.setattr("platform.system", lambda: "Darwin")
        monkeypatch.setattr(mac_svc, "launchd_plist_path", lambda: plist)
        stdout = '{\n\t"PID" = 12345;\n\t"Label" = "com.fm2note.serve";\n}'
        from subprocess import CompletedProcess

        monkeypatch.setattr(
            mac_svc.subprocess,
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
        assert body["desktop_app"] is False

    def test_status_marks_desktop_app_mode(self, client, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Linux")
        monkeypatch.setenv("FM2NOTE_DESKTOP_APP", "1")
        r = client.get("/api/service/status")
        body = r.json()
        assert body["desktop_app"] is True

    def test_status_reports_user_disabled_background(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr("platform.system", lambda: "Darwin")
        from src import macos_service as mac_svc

        monkeypatch.setattr(mac_svc, "launchd_plist_path", lambda: tmp_path / "missing.plist")
        (tmp_path / mac_svc.BACKGROUND_DISABLED_MARKER).write_text("disabled\n")

        r = client.get("/api/service/status")
        body = r.json()
        assert body["installed"] is False
        assert body["auto_start_disabled"] is True


class TestServiceInstallToggle:
    """v1.5.1: GUI 'open at login' toggle calls install/uninstall endpoints
    so users no longer need to open a terminal."""

    def test_install_macos_success(self, client, monkeypatch):
        from unittest.mock import patch

        monkeypatch.setattr("platform.system", lambda: "Darwin")
        with patch(
            "src.web.routes.service._run_install_service",
            return_value={"ok": True, "output": "installed"},
        ):
            r = client.post("/api/service/install")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_install_macos_failure_returns_500(self, client, monkeypatch):
        from unittest.mock import patch

        monkeypatch.setattr("platform.system", lambda: "Darwin")
        with patch(
            "src.web.routes.service._run_install_service",
            return_value={"ok": False, "error": "launchctl 拒绝"},
        ):
            r = client.post("/api/service/install")
        assert r.status_code == 500
        assert "launchctl" in r.json()["detail"]

    def test_install_non_darwin_returns_400(self, client, monkeypatch):
        monkeypatch.setattr("platform.system", lambda: "Linux")
        r = client.post("/api/service/install")
        assert r.status_code == 400

    def test_uninstall_macos_success(self, client, monkeypatch):
        from unittest.mock import patch

        monkeypatch.setattr("platform.system", lambda: "Darwin")
        with patch(
            "src.web.routes.service._run_uninstall_service",
            return_value={"ok": True, "output": "removed"},
        ):
            r = client.post("/api/service/uninstall")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_start_macos_success(self, client, monkeypatch):
        from unittest.mock import patch

        monkeypatch.setattr("platform.system", lambda: "Darwin")
        with patch(
            "src.web.routes.service._run_start_service",
            return_value={"ok": True, "output": "started"},
        ):
            r = client.post("/api/service/start")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_frozen_desktop_cli_command_uses_current_executable(self, monkeypatch):
        from src.web.routes import service as svc_mod

        monkeypatch.setattr(svc_mod.sys, "frozen", True, raising=False)
        monkeypatch.setattr(svc_mod.sys, "executable", "/App/FM2note.app/Contents/MacOS/FM2note")
        monkeypatch.setattr(svc_mod.shutil, "which", lambda name: "/usr/local/bin/fm2note")

        assert svc_mod._fm2note_cli_cmd("run-once") == [
            "/App/FM2note.app/Contents/MacOS/FM2note",
            "run-once",
        ]

        assert svc_mod._fm2note_cli_cmd("start-service") == [
            "/App/FM2note.app/Contents/MacOS/FM2note",
            "start-service",
        ]

    def test_source_checkout_cli_command_prefers_console_script(self, monkeypatch):
        from src.web.routes import service as svc_mod

        monkeypatch.delattr(svc_mod.sys, "frozen", raising=False)
        monkeypatch.setattr(svc_mod.shutil, "which", lambda name: "/usr/local/bin/fm2note")

        assert svc_mod._fm2note_cli_cmd("run-once") == ["/usr/local/bin/fm2note", "run-once"]


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
