"""Integration tests for the FastAPI web app (pages + API)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app
from src.web.progress import reset_bus


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Provide a minimal valid config the routes can load
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f'vault_path: "{tmp_path}"\npodcast_dir: "Podcasts"\nasr_engine: "funasr"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(
        f'vault_path: "{tmp_path}"\npodcast_dir: "Podcasts"\nasr_engine: "funasr"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-1234567890abcdef")
    reset_bus()
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestPages:
    def test_transcribe_page_renders(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "FM2note" in r.text
        assert "开始转录" in r.text
        assert 'id="collie"' in r.text
        assert 'data-state="idle"' in r.text
        # 5-stage progress list rendered
        for stage in ["resolve", "subtitle_check", "asr", "summary", "write"]:
            assert f'data-stage="{stage}"' in r.text
        assert "生成精简版博客、摘要与章节" in r.text

    def test_history_page_renders(self, client):
        r = client.get("/history")
        assert r.status_code == 200
        assert "最近转录过的剧集" in r.text
        assert "/static/history.js" in r.text

    def test_subscriptions_page_renders(self, client):
        r = client.get("/subscriptions")
        assert r.status_code == 200
        assert "粘贴小宇宙播客链接" in r.text
        assert "sub-paste" in r.text
        assert "/static/subscriptions.js" in r.text

    def test_settings_page_renders(self, client):
        r = client.get("/settings")
        assert r.status_code == 200
        assert "API 密钥" in r.text or "设置" in r.text

    def test_active_tab_highlighted(self, client):
        r = client.get("/history")
        # The active tab uses bg-stone-900 styling
        assert "bg-stone-900" in r.text

    def test_header_allows_mobile_wrapping(self, client):
        """v1.6.4: narrow app/browser windows must wrap header controls instead
        of squeezing the daemon chip into vertical text or overflowing."""
        r = client.get("/cloud")
        assert r.status_code == 200
        assert "flex flex-wrap items-center justify-between gap-3" in r.text
        assert "hidden whitespace-nowrap shrink-0 text-xs" in r.text
        assert "flex flex-wrap items-center justify-end gap-1 text-sm" in r.text


class TestHealthz:
    def test_healthz(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "version" in body


class TestSettingsAPI:
    def test_get_settings_returns_redacted_keys(self, client):
        r = client.get("/api/settings")
        assert r.status_code == 200
        body = r.json()
        # DashScope key is set via monkeypatched env var
        assert body["keys"]["dashscope"]["configured"] is True
        preview = body["keys"]["dashscope"]["preview"]
        # Preview must not contain the middle of the actual key
        assert "1234567890abcdef" not in preview
        assert preview.startswith("sk-t")
        # Unset keys are empty strings
        assert body["keys"]["poe"]["configured"] is False
        assert body["keys"]["poe"]["preview"] == ""

    def test_get_settings_exposes_vault_path_default(self, client):
        """The personal-default vault path is surfaced as a separate field so
        the frontend can show it as a placeholder / "use default" button."""
        from src.config import DEFAULT_VAULT_PATH

        r = client.get("/api/settings")
        assert r.status_code == 200
        body = r.json()
        assert body["vault_path_default"] == DEFAULT_VAULT_PATH
        # v1.5.1: default is "~/Documents/Obsidian" (was a hardcoded personal
        # absolute path). UI prepends Path.expanduser if it cares. Verify the
        # placeholder is non-empty and either "~"-prefixed or absolute.
        assert body["vault_path_default"]
        assert body["vault_path_default"].startswith(("~", "/"))


class TestStaticFiles:
    def test_app_js_served(self, client):
        r = client.get("/static/app.js")
        assert r.status_code == 200
        assert "EventSource" in r.text

    def test_app_css_served(self, client):
        r = client.get("/static/app.css")
        assert r.status_code == 200
        assert "step-icon" in r.text

    def test_daemon_chip_uses_desktop_app_copy(self, client):
        r = client.get("/static/daemon-chip.js")
        assert r.status_code == 200
        assert "桌面 App 运行中" in r.text
        assert "后台未启" in r.text

    def test_settings_js_uses_background_check_copy(self, client):
        r = client.get("/static/settings.js")
        assert r.status_code == 200
        assert "后台自动检查" in r.text
        assert "开启后台" in r.text
        assert "关闭后台" in r.text
        assert "启动后台" in r.text

    def test_settings_js_background_buttons_do_not_submit_or_open_new_windows(self, client):
        r = client.get("/static/settings.js")
        assert r.status_code == 200
        assert 'id="svc-install-btn"\n                    type="button"' in r.text
        assert 'id="svc-start-btn"\n                      type="button"' in r.text
        assert 'id="svc-uninstall-btn"\n                    type="button"' in r.text
        assert "toggleService('install', btn, event)" in r.text
        assert "toggleService('start', startBtn, event)" in r.text
        assert "toggleService('uninstall', offBtn, event)" in r.text
        assert "if (event) event.preventDefault();" in r.text
        assert "pollBtn.addEventListener('click', async (event)" in r.text
        assert "event.preventDefault();" in r.text

    def test_cloud_js_maps_source_dedup_reason(self, client):
        r = client.get("/static/cloud.js")
        assert r.status_code == 200
        assert "already_exists_by_source" in r.text
        assert "已存在同一来源" in r.text
