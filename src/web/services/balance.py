from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Literal

from loguru import logger

AlertLevel = Literal["ok", "warn", "critical"]

# Default thresholds in CNY. Lower than ``warn`` is OK; >= ``critical`` triggers red.
DEFAULT_WARN_BELOW = 50.0
DEFAULT_CRITICAL_BELOW = 10.0
CACHE_TTL_SEC = 300.0  # 5 min


@dataclass
class BalanceSnapshot:
    available_amount: float
    available_cash_amount: float
    currency: str
    alert_level: AlertLevel
    fetched_at: float


@dataclass
class BalanceState:
    """Returned by ``GET /api/balance``."""

    configured: bool
    snapshot: BalanceSnapshot | None = None
    error: str | None = None


_cache: BalanceSnapshot | None = None


def _alert_level(cash: float) -> AlertLevel:
    if cash < DEFAULT_CRITICAL_BELOW:
        return "critical"
    if cash < DEFAULT_WARN_BELOW:
        return "warn"
    return "ok"


def _credentials() -> tuple[str, str] | None:
    ak = os.environ.get("ALIYUN_ACCESS_KEY_ID", "").strip()
    sk = os.environ.get("ALIYUN_ACCESS_KEY_SECRET", "").strip()
    if not ak or not sk:
        return None
    return ak, sk


def _build_client(ak: str, sk: str):
    """Construct the BSS OpenAPI client. Imported lazily so the dep stays optional."""
    from alibabacloud_bssopenapi20171214.client import Client
    from alibabacloud_tea_openapi.models import Config

    config = Config(
        access_key_id=ak,
        access_key_secret=sk,
        # BSS OpenAPI lives in the central region; only the global endpoint is supported.
        endpoint="business.aliyuncs.com",
    )
    return Client(config)


def _safe_float(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def fetch_balance(force_refresh: bool = False) -> BalanceState:
    """Fetch the current balance, using a 5-minute cache.

    Returns a ``BalanceState`` that callers can serialize directly to JSON.
    Never raises — failures populate ``error`` so the UI can degrade gracefully.
    """
    global _cache

    creds = _credentials()
    if creds is None:
        return BalanceState(configured=False)

    now = time.monotonic()
    if not force_refresh and _cache is not None and (now - _cache.fetched_at) < CACHE_TTL_SEC:
        return BalanceState(configured=True, snapshot=_cache)

    ak, sk = creds
    try:
        client = _build_client(ak, sk)
    except ImportError as e:
        logger.warning("aliyun BSS SDK missing — pip install fm2note[aliyun]: {}", e)
        return BalanceState(
            configured=True,
            error="alibabacloud-bssopenapi20171214 未安装，请 pip install fm2note[aliyun]",
        )

    try:
        import asyncio

        response = await asyncio.to_thread(client.query_account_balance)
    except Exception as e:
        # AK/SK invalid, network, rate limit, etc.
        # Critical: never log or surface the raw exception message — some SDK
        # exception types embed credential context. Log only the exception type
        # plus an opaque SK fingerprint for support correlation.
        from hashlib import sha256

        sk_fp = sha256(sk.encode()).hexdigest()[:6]
        logger.warning("QueryAccountBalance failed (sk_fp={}): {}", sk_fp, type(e).__name__)
        return BalanceState(configured=True, error=f"Aliyun BSS API 调用失败（{type(e).__name__}）")

    try:
        body = response.body
        # SDK responses expose attributes; tolerate both attribute and dict access.
        data = getattr(body, "data", None) or {}
        if hasattr(data, "to_map"):
            data = data.to_map()
        if not isinstance(data, dict):
            data = {}
        available = _safe_float(data.get("AvailableAmount"))
        cash = _safe_float(data.get("AvailableCashAmount"))
        currency = str(data.get("Currency") or "CNY")
    except Exception as e:
        logger.warning("BSS response parse failed: {}: {}", type(e).__name__, e)
        return BalanceState(configured=True, error="failed to parse BSS response")

    snapshot = BalanceSnapshot(
        available_amount=available,
        available_cash_amount=cash,
        currency=currency,
        alert_level=_alert_level(cash),
        fetched_at=now,
    )
    _cache = snapshot
    return BalanceState(configured=True, snapshot=snapshot)


def reset_cache() -> None:
    """Test helper — wipe the module-level cache."""
    global _cache
    _cache = None
