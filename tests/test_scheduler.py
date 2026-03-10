from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.config import AppConfig
from src.scheduler import FM2noteScheduler


@pytest.fixture
def mock_config():
    return AppConfig(vault_path="/tmp/vault", poll_interval_hours=3)


@pytest.fixture
def mock_pipeline():
    pipeline = AsyncMock()
    pipeline.run_once = AsyncMock(return_value=[])
    return pipeline


class TestFM2noteScheduler:
    def test_init(self, mock_pipeline, mock_config):
        scheduler = FM2noteScheduler(mock_pipeline, mock_config)
        assert scheduler._config.poll_interval_hours == 3

    @pytest.mark.asyncio
    async def test_start_adds_jobs(self, mock_pipeline, mock_config):
        scheduler = FM2noteScheduler(mock_pipeline, mock_config)
        scheduler.start()

        jobs = scheduler._scheduler.get_jobs()
        job_ids = [j.id for j in jobs]
        assert "poll_rss" in job_ids
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_does_not_raise(self, mock_pipeline, mock_config):
        scheduler = FM2noteScheduler(mock_pipeline, mock_config)
        scheduler.start()
        # stop 应该不抛出异常
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_run_job_calls_pipeline(self, mock_pipeline, mock_config):
        scheduler = FM2noteScheduler(mock_pipeline, mock_config)
        await scheduler._run_job()
        mock_pipeline.run_once.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_job_handles_error(self, mock_pipeline, mock_config):
        mock_pipeline.run_once = AsyncMock(side_effect=Exception("测试异常"))
        scheduler = FM2noteScheduler(mock_pipeline, mock_config)
        # 不应抛出异常
        await scheduler._run_job()
