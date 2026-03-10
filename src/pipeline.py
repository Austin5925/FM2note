from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.config import AppConfig
from src.downloader.audio import AudioDownloader
from src.models import Episode
from src.monitor.rss_checker import RSSChecker
from src.monitor.state import StateManager
from src.transcriber.base import Transcriber
from src.writer.markdown import MarkdownGenerator
from src.writer.obsidian import ObsidianWriter


class Pipeline:
    """主管线编排，处理从 RSS 检测到笔记写入的完整流程"""

    def __init__(
        self,
        config: AppConfig,
        rss_checker: RSSChecker,
        downloader: AudioDownloader,
        transcriber: Transcriber,
        md_generator: MarkdownGenerator,
        writer: ObsidianWriter,
        state: StateManager,
    ):
        self._config = config
        self._rss_checker = rss_checker
        self._downloader = downloader
        self._transcriber = transcriber
        self._md_generator = md_generator
        self._writer = writer
        self._state = state

    async def process_episode(self, episode: Episode) -> Path:
        """处理单集的完整流程。

        流程：标记状态 → 转写 → 生成笔记 → 写入 vault

        Args:
            episode: 剧集信息

        Returns:
            写入的笔记文件路径

        Raises:
            Exception: 任何步骤失败时抛出
        """
        guid = episode.guid
        try:
            # 转写（通义听悟直接接受 URL，无需先下载）
            await self._state.mark_status(
                guid, "transcribing", podcast_name=episode.podcast_name, title=episode.title
            )
            logger.info("开始转写: {}", episode.title)
            transcript = await self._transcriber.transcribe(episode.audio_url)

            # 生成 Markdown
            await self._state.mark_status(guid, "writing")
            content = self._md_generator.render(episode, transcript)

            # 写入 Obsidian
            note_path = self._writer.write_note(episode, content)
            await self._state.mark_status(guid, "done", note_path=str(note_path))

            logger.success("处理完成: {} → {}", episode.title, note_path)
            return note_path

        except Exception as e:
            logger.error("处理失败: {} — {}", episode.title, e)
            await self._state.mark_status(guid, "failed", error_msg=str(e))
            raise

    async def run_once(self) -> list[Path]:
        """执行一次完整的检查-处理循环。

        Returns:
            所有成功写入的笔记路径列表
        """
        logger.info("开始检查新剧集...")

        # 获取新剧集
        new_episodes = await self._rss_checker.check_all()

        # 获取可重试的失败任务
        failed = await self._state.get_failed(max_retries=self._config.max_retries)
        retry_episodes = []
        for f in failed:
            # 重新构建 Episode（简化版，实际使用时需从 RSS 重新获取完整信息）
            logger.info("重试失败任务: {} (第 {} 次)", f.title, f.retry_count + 1)

        all_episodes = new_episodes + retry_episodes

        if not all_episodes:
            logger.info("没有新剧集需要处理")
            return []

        # 逐个处理（不并发，避免 API 限流）
        results: list[Path] = []
        success_count = 0
        fail_count = 0

        for episode in all_episodes:
            try:
                path = await self.process_episode(episode)
                results.append(path)
                success_count += 1
            except Exception:
                fail_count += 1

        logger.info(
            "处理完成: 共 {} 集, 成功 {}, 失败 {}",
            len(all_episodes),
            success_count,
            fail_count,
        )
        return results
