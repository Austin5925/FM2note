import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env():
    """Restore os.environ after every test.

    Routes like ``PUT /api/settings`` mutate ``os.environ`` directly (so a
    saved key takes effect immediately within the running web process). Without
    this fixture those mutations leak across tests and produce order-dependent
    failures.
    """
    snapshot = os.environ.copy()
    yield
    # Remove keys added during the test
    for k in list(os.environ.keys()):
        if k not in snapshot:
            del os.environ[k]
    # Restore values that changed
    for k, v in snapshot.items():
        if os.environ.get(k) != v:
            os.environ[k] = v


@pytest.fixture(autouse=True)
def _reset_balance_cache():
    """Wipe the balance module cache between tests so leaked state never crosses runs."""
    from src.web.services import balance as _balance

    _balance.reset_cache()
    yield
    _balance.reset_cache()


@pytest.fixture(autouse=True)
def _reset_legacy_env_warning():
    """Reset the module-level stale-env warning dedup flag between tests.

    v1.4.12 introduced a process-wide flag (``_legacy_env_warning_emitted``)
    so the warning fires once per process instead of once per request. In
    tests, that means whichever test calls ``load_config`` first flips the
    flag and every later test sees no warning — silently breaking tests
    that assert on warning emission. This fixture restores the "fresh
    process" precondition between every test.
    """
    import src.config as _cfg

    _cfg._legacy_env_warning_emitted = False
    yield
    _cfg._legacy_env_warning_emitted = False


@pytest.fixture
def fixtures_dir():
    """测试 fixtures 目录"""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_config(tmp_path):
    """创建临时配置文件"""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
vault_path: "/tmp/test-vault"
podcast_dir: "Podcasts"
poll_interval_hours: 3
asr_engine: "tingwu"
temp_dir: "./data/tmp"
max_retries: 3
log_level: "DEBUG"
""",
        encoding="utf-8",
    )
    return config_path


@pytest.fixture
def tmp_subscriptions(tmp_path):
    """创建临时订阅配置文件"""
    subs_path = tmp_path / "subscriptions.yaml"
    subs_path.write_text(
        """
podcasts:
  - name: "测试播客A"
    rss_url: "http://localhost:1200/xiaoyuzhou/podcast/AAA"
    tags: ["tech", "ai"]
  - name: "测试播客B"
    rss_url: "http://localhost:1200/xiaoyuzhou/podcast/BBB"
    tags: ["business"]
""",
        encoding="utf-8",
    )
    return subs_path
