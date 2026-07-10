"""Integration tests for PUT /api/settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        f'# vault config\nvault_path: "{tmp_path}"\n'
        f'podcast_dir: "Podcasts"\nasr_engine: "funasr"\n',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "# secret\nexport DASHSCOPE_API_KEY=sk-orig\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-orig")
    with TestClient(create_app()) as c:
        yield c


def test_empty_strings_leave_keys_unchanged(client, tmp_path):
    r = client.put("/api/settings", json={"dashscope_api_key": "", "poe_api_key": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["env_keys_updated"] == []
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "sk-orig" in env_text


def test_update_dashscope_key_persists(client, tmp_path):
    r = client.put("/api/settings", json={"dashscope_api_key": "sk-NEW-1234567890"})
    assert r.status_code == 200
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "sk-NEW-1234567890" in env_text
    assert "sk-orig" not in env_text
    # Process env also reflects new value
    assert os.environ.get("DASHSCOPE_API_KEY") == "sk-NEW-1234567890"


def test_yaml_field_update_preserves_comment(client, tmp_path):
    r = client.put("/api/settings", json={"podcast_dir": "10_Podcasts"})
    assert r.status_code == 200
    text = (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    assert "# vault config" in text
    assert "10_Podcasts" in text


def test_vault_path_validation_rejects_missing_dir(client):
    r = client.put("/api/settings", json={"vault_path": "/does/not/exist/at/all"})
    assert r.status_code == 400
    assert "不存在" in r.json()["detail"]


def test_vault_path_validation_rejects_file(client, tmp_path):
    file_target = tmp_path / "not-a-dir.txt"
    file_target.write_text("hi", encoding="utf-8")
    r = client.put("/api/settings", json={"vault_path": str(file_target)})
    assert r.status_code == 400
    assert "不是目录" in r.json()["detail"]


def test_vault_path_strips_single_quotes(client, tmp_path):
    """Regression — user pasted a path copied from a shell hint that included
    surrounding ``'…'`` quotes. We must accept it and persist the cleaned value."""
    quoted = f"'{tmp_path}'"
    r = client.put("/api/settings", json={"vault_path": quoted})
    assert r.status_code == 200, r.json()
    text = (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    # The quotes are not part of the stored value (we may see YAML's own quoting
    # for the value, but never the leading-quoted form like 'foo'foo'foo').
    assert f"'{tmp_path}'" not in text.replace(f"{tmp_path}", "")
    assert str(tmp_path) in text


def test_vault_path_strips_double_quotes(client, tmp_path):
    quoted = f'"{tmp_path}"'
    r = client.put("/api/settings", json={"vault_path": quoted})
    assert r.status_code == 200, r.json()


def test_vault_path_strips_nested_quotes(client, tmp_path):
    """A user double-pasting from a YAML file can produce \"'/path/to/vault'\".
    The strip should peel both layers, not just one."""
    nested = f"\"'{tmp_path}'\""
    r = client.put("/api/settings", json={"vault_path": nested})
    assert r.status_code == 200, r.json()
    text = (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    assert str(tmp_path) in text


def test_vault_path_relative_paths_are_rejected(client, tmp_path):
    """Codex audit (v1.4.13) — a literal ``.`` or ``..`` survives
    _clean_path_input and Path(".") = CWD, which silently passes
    exists/is_dir/writable. Must be rejected by an absolute-path guard."""
    for evil in (".", "..", "./vault", "../vault", "relative/path"):
        r = client.put("/api/settings", json={"vault_path": evil})
        assert r.status_code == 400, (evil, r.json())
        assert "绝对路径" in r.json()["detail"]


def test_vault_path_collapsed_to_empty_is_rejected(client, tmp_path):
    """Codex audit Finding #3 — without an explicit empty check after
    cleaning, ``" "`` / ``"''"`` / ``"   "`` would collapse to "", and
    ``Path("")`` resolves to the current working directory (which exists,
    is a dir, and is writable) — silently corrupting vault_path."""
    for evil in ("   ", "''", "  '  '  ", '" "', "\"''\""):
        r = client.put("/api/settings", json={"vault_path": evil})
        assert r.status_code == 400, (evil, r.json())
        assert "不能为空" in r.json()["detail"]
    # The on-disk YAML must NOT have been touched — it still points where
    # the fixture put it.
    text = (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    assert str(tmp_path) in text


def test_summary_provider_persists_to_yaml_and_survives_reload(client, tmp_path):
    """Codex audit Finding #6 — verify the v1.4.12 migration actually works:
    PUT /api/settings with a non-secret field that used to be env-only
    persists to YAML and is read back from there. Without this test we'd
    never catch a regression that re-routes the field through .env."""
    # 1) Save a non-default summary_provider
    r = client.put("/api/settings", json={"summary_provider": "poe"})
    assert r.status_code == 200, r.json()
    assert "summary_provider" in r.json()["yaml_keys_updated"]
    # 2) It actually landed in YAML, not .env
    yaml_text = (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    assert "summary_provider" in yaml_text
    assert "poe" in yaml_text
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "SUMMARY_PROVIDER" not in env_text
    # 3) GET /api/settings reads it back from YAML
    r2 = client.get("/api/settings")
    assert r2.json()["summary_provider"] == "poe"


def test_settings_page_scopes_poe_model_options_to_poe_provider():
    html = (ROOT / "src/web/templates/settings.html").read_text(encoding="utf-8")
    js = (ROOT / "src/web/static/settings.js").read_text(encoding="utf-8")

    assert 'id="poe_summary_model"' in html
    assert "const DEFAULT_POE_MODEL = 'gpt-5.4-mini';" in js
    assert "gemini-3.1-flash-lite" in js
    assert "gpt-5.4-mini" in js
    assert "claude-sonnet-4.6" in js
    assert "provider !== 'poe'" in js
    assert "provider !== 'openai'" in js


def test_collie_has_transcribe_state_reactions():
    html = (ROOT / "src/web/templates/transcribe.html").read_text(encoding="utf-8")
    app_js = (ROOT / "src/web/static/app.js").read_text(encoding="utf-8")
    collie_js = (ROOT / "src/web/static/collie.js").read_text(encoding="utf-8")
    css = (ROOT / "src/web/static/app.css").read_text(encoding="utf-8")

    assert 'data-state="idle"' in html
    for state in ("ready", "working", "done", "error"):
        assert f"'{state}'" in app_js
        assert f"{state}:" in collie_js
        assert f'data-state="{state}"' in css


def test_log_level_persists_to_yaml(client, tmp_path):
    """Same regression guard as above for log_level (formerly LOG_LEVEL env)."""
    r = client.put("/api/settings", json={"log_level": "DEBUG"})
    assert r.status_code == 200, r.json()
    yaml_text = (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    assert "DEBUG" in yaml_text
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LOG_LEVEL" not in env_text


def test_vault_path_strips_whitespace(client, tmp_path):
    padded = f"  {tmp_path}  "
    r = client.put("/api/settings", json={"vault_path": padded})
    assert r.status_code == 200, r.json()


def test_podcast_dir_strips_quotes(client, tmp_path):
    r = client.put("/api/settings", json={"podcast_dir": "'10_Podcasts'"})
    assert r.status_code == 200, r.json()
    text = (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    assert "10_Podcasts" in text
    # ensure the literal ''...'' (leading apostrophe in the YAML value) is gone
    assert "''10_Podcasts''" not in text


def test_unknown_keys_are_silently_ignored(client, tmp_path):
    """If a client posts an unknown field, it should be ignored (not raise),
    and the canonical .env path must not be writable via query params."""
    # Try to slip a "config_path" query param in — should NOT redirect writes
    # because the API no longer reads it.
    r = client.put(
        "/api/settings?config_path=/tmp/evil.yaml&env_path=/tmp/evil.env",
        json={"dashscope_api_key": "sk-attacked"},
    )
    # Either the dashscope update succeeds (going to canonical paths) or 422.
    assert r.status_code in (200, 422)
    # Either way, no file at /tmp/evil.yaml or /tmp/evil.env should appear.
    from pathlib import Path

    assert not Path("/tmp/evil.yaml").exists()
    assert not Path("/tmp/evil.env").exists()


def test_aliyun_keys_round_trip(client, tmp_path, monkeypatch):
    r = client.put(
        "/api/settings",
        json={
            "aliyun_access_key_id": "LTAI5tABCD",
            "aliyun_access_key_secret": "supersecret",
        },
    )
    assert r.status_code == 200
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "LTAI5tABCD" in env_text
    assert "supersecret" in env_text


def test_restart_required_flag(client):
    r = client.put("/api/settings", json={"dashscope_api_key": "sk-new"})
    assert r.status_code == 200
    assert r.json()["restart_required"] is True

    r2 = client.put("/api/settings", json={"podcast_dir": "x"})
    assert r2.json()["restart_required"] is False


def test_two_phase_commit_leaves_no_partial_state(client, tmp_path, monkeypatch):
    """If the second os.replace fails, neither file should be partially written.

    We force the env replace to fail; the yaml file should remain untouched
    even though we asked for both updates.
    """
    import os as _os

    real_replace = _os.replace
    call_log = {"n": 0}

    def selective_replace(src, dst):
        call_log["n"] += 1
        # First replace is yaml (CONFIG_PATH). Allow it. Fail on the env one.
        if str(dst).endswith(".env"):
            raise OSError("simulated disk full on env write")
        return real_replace(src, dst)

    monkeypatch.setattr("src.web.routes.settings_api.os.replace", selective_replace)

    original_env = (tmp_path / ".env").read_text(encoding="utf-8")

    r = client.put(
        "/api/settings",
        json={"podcast_dir": "Should_Not_Persist", "dashscope_api_key": "sk-NEW"},
    )
    assert r.status_code == 500

    # YAML *did* commit (we don't have full transactional rollback) — but
    # only because the env replace failed. The user can retry safely.
    # The .env file must NOT have been touched.
    assert (tmp_path / ".env").read_text(encoding="utf-8") == original_env
    # Claude reviewer Bug 4 (v1.4.14): the docstring above claims "YAML did
    # commit" — assert it explicitly so a future refactor that accidentally
    # rolls back the yaml replace would fail this test instead of silently
    # changing observable behavior.
    yaml_after = (tmp_path / "config" / "config.yaml").read_text(encoding="utf-8")
    assert "Should_Not_Persist" in yaml_after, (
        "Two-phase commit currently lets YAML commit even when ENV fails. "
        "If this assertion fails, behavior changed — update the docstring "
        "or implement full transactional rollback."
    )
    # No stray temp files
    stray_env = [
        f.name for f in tmp_path.iterdir() if f.name.startswith(".env.") and f.name != ".env"
    ]
    assert stray_env == []
    stray_yaml = [
        f.name
        for f in (tmp_path / "config").iterdir()
        if f.name.startswith("config.yaml.") and f.name != "config.yaml"
    ]
    assert stray_yaml == []
