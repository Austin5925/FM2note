"""Tests for the Aliyun balance service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.web.services import balance as balance_module
from src.web.services.balance import _alert_level, fetch_balance, reset_cache


def test_alert_level_thresholds():
    # ok at >= 50, warn at [10, 50), critical at < 10
    assert _alert_level(100) == "ok"
    assert _alert_level(50.01) == "ok"
    assert _alert_level(50.0) == "ok"
    assert _alert_level(49.99) == "warn"
    assert _alert_level(11) == "warn"
    assert _alert_level(10.0) == "warn"
    assert _alert_level(9.99) == "critical"
    assert _alert_level(0) == "critical"


@pytest.mark.asyncio
async def test_not_configured_returns_configured_false(monkeypatch):
    monkeypatch.delenv("ALIYUN_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIYUN_ACCESS_KEY_SECRET", raising=False)
    reset_cache()
    state = await fetch_balance()
    assert state.configured is False
    assert state.snapshot is None


@pytest.mark.asyncio
async def test_happy_path_parses_response(monkeypatch):
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    reset_cache()

    fake_data = MagicMock()
    fake_data.to_map.return_value = {
        "AvailableAmount": "123.45",
        "AvailableCashAmount": "99.50",
        "Currency": "CNY",
    }
    fake_body = SimpleNamespace(data=fake_data)
    fake_resp = SimpleNamespace(body=fake_body)
    fake_client = MagicMock()
    fake_client.query_account_balance.return_value = fake_resp

    with patch.object(balance_module, "_build_client", return_value=fake_client):
        state = await fetch_balance()

    assert state.configured is True
    assert state.snapshot is not None
    assert state.snapshot.available_amount == 123.45
    assert state.snapshot.available_cash_amount == 99.50
    assert state.snapshot.alert_level == "ok"


@pytest.mark.asyncio
async def test_critical_alert_when_low_cash(monkeypatch):
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    reset_cache()

    fake_data = MagicMock()
    fake_data.to_map.return_value = {
        "AvailableAmount": "5.0",
        "AvailableCashAmount": "5.0",
        "Currency": "CNY",
    }
    fake_client = MagicMock()
    fake_client.query_account_balance.return_value = SimpleNamespace(
        body=SimpleNamespace(data=fake_data)
    )

    with patch.object(balance_module, "_build_client", return_value=fake_client):
        state = await fetch_balance()

    assert state.snapshot.alert_level == "critical"


@pytest.mark.asyncio
async def test_sdk_error_returns_sanitized_error(monkeypatch):
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    reset_cache()

    fake_client = MagicMock()
    fake_client.query_account_balance.side_effect = RuntimeError("InvalidAccessKeyId")

    with patch.object(balance_module, "_build_client", return_value=fake_client):
        state = await fetch_balance()

    assert state.configured is True
    assert state.snapshot is None
    assert state.error is not None
    # Sanitized: exception type name only, raw message stripped
    assert "RuntimeError" in state.error
    assert "InvalidAccessKeyId" not in state.error


@pytest.mark.asyncio
async def test_secret_never_appears_in_error_path(monkeypatch):
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak-pubid")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "super-secret-shhh-1234")
    reset_cache()

    fake_client = MagicMock()
    fake_client.query_account_balance.side_effect = RuntimeError("boom")

    with patch.object(balance_module, "_build_client", return_value=fake_client):
        state = await fetch_balance()

    assert state.error is not None
    assert "super-secret-shhh-1234" not in state.error


@pytest.mark.asyncio
async def test_exception_message_with_key_is_not_leaked(monkeypatch):
    """Some Aliyun SDK exceptions embed credentials in their message string —
    we must not forward those verbatim to the client."""
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "LTAI5tABCDEFG")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "leaked-secret-token-xyz")
    reset_cache()

    fake_client = MagicMock()
    fake_client.query_account_balance.side_effect = RuntimeError(
        "auth failed with key leaked-secret-token-xyz"
    )

    with patch.object(balance_module, "_build_client", return_value=fake_client):
        state = await fetch_balance()

    assert state.error is not None
    assert "leaked-secret-token-xyz" not in state.error
    assert "LTAI5tABCDEFG" not in state.error


@pytest.mark.asyncio
async def test_cache_hits_skip_sdk(monkeypatch):
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    reset_cache()

    fake_data = MagicMock()
    fake_data.to_map.return_value = {
        "AvailableAmount": "100",
        "AvailableCashAmount": "100",
        "Currency": "CNY",
    }
    fake_client = MagicMock()
    fake_client.query_account_balance.return_value = SimpleNamespace(
        body=SimpleNamespace(data=fake_data)
    )

    with patch.object(balance_module, "_build_client", return_value=fake_client):
        await fetch_balance()
        await fetch_balance()  # second call should hit cache

    assert fake_client.query_account_balance.call_count == 1


@pytest.mark.asyncio
async def test_force_refresh_skips_cache(monkeypatch):
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "sk")
    reset_cache()

    fake_data = MagicMock()
    fake_data.to_map.return_value = {
        "AvailableAmount": "100",
        "AvailableCashAmount": "100",
        "Currency": "CNY",
    }
    fake_client = MagicMock()
    fake_client.query_account_balance.return_value = SimpleNamespace(
        body=SimpleNamespace(data=fake_data)
    )

    with patch.object(balance_module, "_build_client", return_value=fake_client):
        await fetch_balance()
        await fetch_balance(force_refresh=True)

    assert fake_client.query_account_balance.call_count == 2
