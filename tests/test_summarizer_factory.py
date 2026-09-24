"""Tests for summary provider selection."""

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
        "deepseek_api_key": "",
        "openai_api_key": "",
    }
    defaults.update(overrides)
    return AppConfig(**defaults)


class TestSummarizerFactory:
    def test_provider_none(self):
        assert create_summarizer(_make_config(summary_provider="none")) is None

    def test_provider_deepseek_with_key(self):
        s = create_summarizer(_make_config(summary_provider="deepseek", deepseek_api_key="sk-test"))
        assert s is not None
        assert "deepseek-flash" in s.name

    def test_provider_deepseek_without_key(self):
        assert create_summarizer(_make_config(summary_provider="deepseek")) is None

    def test_provider_openai_with_key(self):
        s = create_summarizer(_make_config(summary_provider="openai", openai_api_key="sk-test"))
        assert s is not None
        assert "openai" in s.name

    def test_provider_openai_without_key(self):
        assert create_summarizer(_make_config(summary_provider="openai")) is None

    def test_auto_prefers_deepseek(self):
        s = create_summarizer(_make_config(deepseek_api_key="ds-test", openai_api_key="sk-test"))
        assert s is not None
        assert "deepseek-flash" in s.name

    def test_auto_falls_back_to_openai(self):
        s = create_summarizer(_make_config(openai_api_key="sk-test"))
        assert s is not None
        assert "openai" in s.name

    def test_auto_no_keys(self):
        assert create_summarizer(_make_config()) is None

    def test_custom_model(self):
        s = create_summarizer(
            _make_config(
                summary_provider="deepseek", deepseek_api_key="sk-test", summary_model="custom"
            )
        )
        assert "custom" in s.name

    def test_custom_base_url(self):
        s = create_summarizer(
            _make_config(
                summary_provider="openai",
                openai_api_key="sk-test",
                summary_base_url="https://api.example/v1",
            )
        )
        assert s is not None

    def test_default_model_openai(self):
        s = create_summarizer(_make_config(summary_provider="openai", openai_api_key="sk-test"))
        assert "gpt-4o-mini" in s.name
