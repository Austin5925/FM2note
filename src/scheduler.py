from __future__ import annotations

import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from src.config import AppConfig
from src.pipeline import Pipeline


class FM2noteScheduler:
    """APScheduler 定时调度器"""

    def __init__(self, pipeline: Pipeline, config: AppConfig):
        self._pipeline = pipeline
        self._config = config
        self._scheduler = AsyncIOScheduler()
        self._shutdown_event = asyncio.Event()

    def start(self):
        """启动定时任务"""
        self._scheduler.add_job(
            self._run_job,
            "interval",
            hours=self._config.poll_interval_hours,
            id="poll_rss",
            name="RSS 轮询检查",
        )

        # 启动时立即执行一次
        self._scheduler.add_job(
            self._run_job,
            id="initial_run",
            name="启动时立即检查",
        )

        self._scheduler.start()
        logger.info(
            "调度器已启动: 每 {} 小时检查一次",
            self._config.poll_interval_hours,
        )

    async def run_forever(self):
        """阻塞运行直到收到停止信号"""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal, sig)

        self.start()
        await self._shutdown_event.wait()
        self.stop()

    def stop(self):
        """优雅停止调度器"""
        logger.info("正在停止调度器...")
        self._scheduler.shutdown(wait=False)
        logger.info("调度器已停止")

    def _handle_signal(self, sig):
        logger.info("收到信号 {}，准备关闭", sig.name)
        self._shutdown_event.set()

    async def _run_job(self):
        """执行一次管线任务"""
        try:
            results = await self._pipeline.run_once()
            logger.info("定时任务完成: 处理了 {} 个笔记", len(results))
        except Exception as e:
            logger.error("定时任务异常: {}", e)
