import pytest

from src.config import AppConfig, ConfigError, load_config, load_subscriptions


class TestLoadConfig:
    def test_load_valid_config(self, tmp_config, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        config = load_config(tmp_config)
        assert isinstance(config, AppConfig)
        assert config.vault_path == "/tmp/test-vault"
        assert config.podcast_dir == "Podcasts"
        assert config.poll_interval_hours == 3
        assert config.asr_engine == "tingwu"
        assert config.max_retries == 3

    def test_missing_file_raises_error(self, tmp_path):
        with pytest.raises(ConfigError, match="Config file not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_empty_file_raises_error(self, tmp_path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ConfigError, match="Config file is empty"):
            load_config(empty)

    def test_missing_vault_path_raises_error(self, tmp_path):
        no_vault = tmp_path / "no_vault.yaml"
        no_vault.write_text("asr_engine: tingwu\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="vault_path"):
            load_config(no_vault)

    def test_env_does_not_override_vault_path(self, tmp_config, monkeypatch):
        """Regression — pre-v1.4.12, OBSIDIAN_VAULT_PATH silently shadowed
        config.yaml, breaking Web UI saves. The env var is now ignored so the
        single editable surface (config.yaml) wins."""
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/env/vault")
        config = load_config(tmp_config)
        # The YAML value (set by the tmp_config fixture) must win
        assert config.vault_path == "/tmp/test-vault"
        assert config.vault_path != "/env/vault"

    def test_env_does_not_override_log_level(self, tmp_config, monkeypatch):
        """v1.4.12 — log_level moved to yaml-only along with vault_path."""
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        config = load_config(tmp_config)
        # tmp_config fixture sets log_level: "DEBUG" in YAML; env must not win
        assert config.log_level == "DEBUG"
        assert config.log_level != "WARNING"

    def test_env_does_not_override_summary_fields(self, tmp_config, monkeypatch):
        """v1.4.12 one-cut cleanup — SUMMARY_* env vars are no longer honored."""
        monkeypatch.setenv("SUMMARY_PROVIDER", "openai")
        monkeypatch.setenv("SUMMARY_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("SUMMARY_COOLDOWN", "999")
        monkeypatch.setenv("SUMMARY_BASE_URL", "https://example.com/v1")
        config = load_config(tmp_config)
        # All fall back to AppConfig defaults / yaml-omitted values
        assert config.summary_provider == "auto"
        assert config.summary_model == ""
        assert config.summary_cooldown == 60
        assert config.summary_base_url == ""

    def test_env_still_loads_api_keys(self, tmp_config, monkeypatch):
        """Sensitive credentials still come from env (and ONLY from env)."""
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test-ds-key")
        monkeypatch.setenv("TINGWU_APP_ID", "test-app-id")
        monkeypatch.setenv("POE_API_KEY", "test-poe-key")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        config = load_config(tmp_config)
        assert config.dashscope_api_key == "test-ds-key"
        assert config.tingwu_app_id == "test-app-id"
        assert config.poe_api_key == "test-poe-key"
        assert config.openai_api_key == "test-openai-key"

    def test_stale_env_warning_fires_only_once(self, tmp_config, monkeypatch):
        """Codex audit Finding #7 — load_config runs per HTTP request, so the
        stale-env warning must dedupe at module level or it floods the log.

        v1.4.14 hardening (Claude reviewer Bug 1): we count the *actual*
        warning emission, not just the dedup flag — a previous version of
        this test only checked the flag, which flips True on any call
        regardless of whether legacy env vars were set, so the assertion was
        trivially true and the dedup logic was untested.
        """
        import src.config as cfg_mod

        # The autouse _reset_legacy_env_warning fixture has already reset the
        # flag, but be explicit since this test depends on it.
        cfg_mod._legacy_env_warning_emitted = False
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/old/vault")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        # Count actual logger.warning calls (loguru doesn't propagate to
        # pytest caplog without extra plumbing — easier to wrap the sink).
        from loguru import logger as _logger

        warnings: list[str] = []
        sink_id = _logger.add(lambda msg: warnings.append(str(msg)), level="WARNING")
        try:
            load_config(tmp_config)
            # Three follow-up calls mimic per-request reloads in the web layer
            load_config(tmp_config)
            load_config(tmp_config)
            load_config(tmp_config)
        finally:
            _logger.remove(sink_id)

        # Exactly one warning emitted, and it mentions the legacy var by name
        legacy_warnings = [w for w in warnings if "v1.4.12" in w]
        assert len(legacy_warnings) == 1, (
            f"Expected 1 stale-env warning across 4 load_config calls, "
            f"got {len(legacy_warnings)}: {legacy_warnings}"
        )
        assert "OBSIDIAN_VAULT_PATH" in legacy_warnings[0]
        assert "LOG_LEVEL" in legacy_warnings[0]

    def test_stale_env_warning_not_emitted_when_no_legacy_env(self, tmp_config, monkeypatch):
        """Negative case — the warning must NOT fire if no legacy env var
        is set, even though the dedup flag still flips True after the call.
        Without this test, Bug 1's original assertion (`assert flag is True`)
        would have been an always-pass."""
        import src.config as cfg_mod

        cfg_mod._legacy_env_warning_emitted = False
        # Ensure none of the legacy vars are set
        for name in cfg_mod._LEGACY_YAML_ENV_VARS:
            monkeypatch.delenv(name, raising=False)

        from loguru import logger as _logger

        warnings: list[str] = []
        sink_id = _logger.add(lambda msg: warnings.append(str(msg)), level="WARNING")
        try:
            load_config(tmp_config)
        finally:
            _logger.remove(sink_id)

        legacy_warnings = [w for w in warnings if "v1.4.12" in w]
        assert legacy_warnings == [], f"Expected no stale-env warning, got: {legacy_warnings}"

    def test_default_values(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        minimal = tmp_path / "minimal.yaml"
        minimal.write_text('vault_path: "/tmp/vault"\n', encoding="utf-8")
        config = load_config(minimal)
        assert config.podcast_dir == "Podcasts"
        assert config.poll_interval_hours == 3
        assert config.asr_engine == "funasr"
        assert config.max_retries == 3
        assert config.log_level == "INFO"

    def test_hint_example_file(self, tmp_path):
        """When config.yaml is missing but config.example.yaml exists, show hint."""
        example = tmp_path / "config.example.yaml"
        example.write_text("vault_path: /tmp\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="Hint: copy the example file"):
            load_config(tmp_path / "config.yaml")


class TestLoadSubscriptions:
    def test_load_valid_subscriptions(self, tmp_subscriptions):
        subs = load_subscriptions(tmp_subscriptions)
        assert len(subs) == 2
        assert subs[0].name == "测试播客A"
        assert subs[0].rss_url == "http://localhost:1200/xiaoyuzhou/podcast/AAA"
        assert subs[0].tags == ["tech", "ai"]
        assert subs[1].name == "测试播客B"

    def test_missing_file_raises_error(self, tmp_path):
        with pytest.raises(ConfigError, match="Subscriptions file not found"):
            load_subscriptions(tmp_path / "nonexistent.yaml")

    def test_empty_file_raises_error(self, tmp_path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ConfigError, match="No podcasts configured"):
            load_subscriptions(empty)

    def test_missing_podcasts_key_raises_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("something_else: true\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="podcasts"):
            load_subscriptions(bad)

    def test_missing_required_fields_raises_error(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            """
podcasts:
  - name: "只有名字没有URL"
""",
            encoding="utf-8",
        )
        with pytest.raises(ConfigError, match="rss_url"):
            load_subscriptions(bad)

    def test_default_empty_tags(self, tmp_path):
        no_tags = tmp_path / "no_tags.yaml"
        no_tags.write_text(
            """
podcasts:
  - name: "无标签播客"
    rss_url: "http://example.com/rss"
""",
            encoding="utf-8",
        )
        subs = load_subscriptions(no_tags)
        assert subs[0].tags == []

    def test_hint_example_file_for_subscriptions(self, tmp_path):
        """When subscriptions.yaml is missing but example exists, show hint."""
        example = tmp_path / "subscriptions.example.yaml"
        example.write_text("podcasts: []\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="Hint: copy the example file"):
            load_subscriptions(tmp_path / "subscriptions.yaml")
