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

    def test_env_override_vault_path(self, tmp_config, monkeypatch):
        monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/env/vault")
        config = load_config(tmp_config)
        assert config.vault_path == "/env/vault"

    def test_env_override_log_level(self, tmp_config, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        config = load_config(tmp_config)
        assert config.log_level == "WARNING"

    def test_env_override_api_keys(self, tmp_config, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test-ds-key")
        monkeypatch.setenv("TINGWU_APP_ID", "test-app-id")
        config = load_config(tmp_config)
        assert config.dashscope_api_key == "test-ds-key"
        assert config.tingwu_app_id == "test-app-id"

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
        with pytest.raises(ConfigError, match="Invalid subscriptions file"):
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
