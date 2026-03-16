"""Tests for summarizer factory selection logic."""

from __future__ import annotations

from src.config import AppConfig
from src.summarizer.factory import create_summarizer


def _make_config(**overrides) -> AppConfig:
    defaults = {
        "vault_path": "/tmp/vault",
        "summary_provider": "auto",
        "summary_model": "",
        "summary_cooldown": 0,
        "summary_base_url": "",
        "poe_api_key": "",
        "openai_api_key": "",
    }
    defaults.update(overrides)
    return AppConfig(**defaults)


class TestSummarizerFactory:
    def test_provider_none(self):
        config = _make_config(summary_provider="none")
        assert create_summarizer(config) is None

    def test_provider_poe_with_key(self):
        config = _make_config(summary_provider="poe", poe_api_key="pk-test")
        s = create_summarizer(config)
        assert s is not None
        assert "poe" in s.name

    def test_provider_poe_without_key(self):
        config = _make_config(summary_provider="poe", poe_api_key="")
        assert create_summarizer(config) is None

    def test_provider_openai_with_key(self):
        config = _make_config(summary_provider="openai", openai_api_key="sk-test")
        s = create_summarizer(config)
        assert s is not None
        assert "openai" in s.name

    def test_provider_openai_without_key(self):
        config = _make_config(summary_provider="openai", openai_api_key="")
        assert create_summarizer(config) is None

    def test_auto_prefers_poe(self):
        """When both keys available, auto prefers Poe."""
        config = _make_config(
            summary_provider="auto",
            poe_api_key="pk-test",
            openai_api_key="sk-test",
        )
        s = create_summarizer(config)
        assert s is not None
        assert "poe" in s.name

    def test_auto_falls_back_to_openai(self):
        """When only OpenAI key available, auto uses OpenAI."""
        config = _make_config(
            summary_provider="auto",
            poe_api_key="",
            openai_api_key="sk-test",
        )
        s = create_summarizer(config)
        assert s is not None
        assert "openai" in s.name

    def test_auto_no_keys(self):
        """When no keys available, auto returns None."""
        config = _make_config(summary_provider="auto")
        assert create_summarizer(config) is None

    def test_custom_model(self):
        config = _make_config(
            summary_provider="openai",
            openai_api_key="sk-test",
            summary_model="gpt-4o",
        )
        s = create_summarizer(config)
        assert "gpt-4o" in s.name

    def test_custom_base_url(self):
        config = _make_config(
            summary_provider="openai",
            openai_api_key="sk-test",
            summary_base_url="https://api.deepseek.com/v1",
        )
        s = create_summarizer(config)
        assert s is not None

    def test_default_model_poe(self):
        """Empty summary_model uses provider default."""
        config = _make_config(
            summary_provider="poe",
            poe_api_key="pk-test",
            summary_model="",
        )
        s = create_summarizer(config)
        assert "GPT-5.4" in s.name

    def test_default_model_openai(self):
        config = _make_config(
            summary_provider="openai",
            openai_api_key="sk-test",
            summary_model="",
        )
        s = create_summarizer(config)
        assert "gpt-4o-mini" in s.name
