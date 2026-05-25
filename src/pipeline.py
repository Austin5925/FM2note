from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.config import AppConfig
from src.downloader.audio import AudioDownloader
from src.models import Episode, TranscriptResult
from src.monitor.rss_checker import RSSChecker
from src.monitor.state import StateManager
from src.monitor.subtitle import fetch_subtitle_from_url
from src.shared_cache import SharedCacheClient
from src.summarizer.base import Summarizer
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
        summarizer: Summarizer | None = None,
    ):
        self._config = config
        self._rss_checker = rss_checker
        self._downloader = downloader
        self._transcriber = transcriber
        self._md_generator = md_generator
        self._writer = writer
        self._state = state
        self._summarizer = summarizer
        # v1.4.16: shared-cache client is None when the user hasn't configured
        # SHARED_CACHE_URL + SHARED_CACHE_TOKEN. Every call site guards on
        # ``if self._shared_cache:`` so single-user deployments pay zero overhead.
        self._shared_cache = SharedCacheClient.from_env()

    async def process_episode(self, episode: Episode) -> Path:
        """处理单集的完整流程。

        流程：
        1. 检查 MCP 去重（可选）
        2. 若有内置字幕 → 直接使用，跳过 ASR
        3. 否则 → 调用 ASR 转写
        4. 生成 Markdown 笔记
        5. 写入 Obsidian vault

        Args:
            episode: 剧集信息

        Returns:
            写入的笔记文件路径

        Raises:
            Exception: 任何步骤失败时抛出
        """
        guid = episode.guid
        try:
            # v1.4.16: shared-cache short-circuit. If another fm2note instance
            # has already processed this episode and uploaded the rendered
            # markdown, just write that to the vault and skip ASR + summary
            # entirely. Saves the full ¥0.79/hr DashScope + Poe call.
            if self._shared_cache is not None:
                try:
                    cached = await self._shared_cache.fetch(guid)
                except Exception as e:
                    logger.debug(
                        "shared cache fetch raised (treating as miss): {}: {}",
                        type(e).__name__,
                        e,
                    )
                    cached = None
                if cached:
                    logger.info(
                        "shared cache HIT, skipping ASR+summary: {} ({} bytes)",
                        episode.title,
                        len(cached),
                    )
                    # v1.4.16 audit fix (Code Review #3 + Codex #3): cache-hit
                    # branch skips the MCP same-title check, so a local re-run
                    # where the note already exists on disk would otherwise
                    # raise FileExistsError from write_note() and bubble up
                    # as a "failed" episode in run_once metrics — even though
                    # the user already has the right file. Detect that state
                    # and treat it as a clean idempotent success.
                    if self._writer.note_exists(episode):
                        existing_path = self._writer._build_path(episode)
                        logger.info(
                            "cache hit but note already on disk — no-op: {}",
                            existing_path,
                        )
                        await self._state.mark_status(
                            guid,
                            "done",
                            podcast_name=episode.podcast_name,
                            title=episode.title,
                            note_path=str(existing_path),
                        )
                        return existing_path
                    note_path = self._writer.write_note(episode, cached)
                    await self._state.mark_status(
                        guid,
                        "done",
                        podcast_name=episode.podcast_name,
                        title=episode.title,
                        note_path=str(note_path),
                    )
                    logger.success("cache-only 处理完成: {} → {}", episode.title, note_path)
                    return note_path

            # MCP 去重检查（可选，失败不阻断）
            if await self._writer.search_existing_mcp(episode.title):
                logger.info("MCP 发现同名笔记，跳过: {}", episode.title)
                await self._state.mark_status(
                    guid,
                    "done",
                    podcast_name=episode.podcast_name,
                    title=episode.title,
                )
                raise FileExistsError(f"MCP 发现同名笔记: {episode.title}")

            # 获取转写结果
            asr_engine = self._config.asr_engine
            if episode.subtitle_url:
                # 有内置字幕，直接下载文本，跳过 ASR
                await self._state.mark_status(
                    guid,
                    "transcribing",
                    podcast_name=episode.podcast_name,
                    title=episode.title,
                )
                logger.info("发现内置字幕，跳过 ASR: {}", episode.title)
                subtitle_text = await fetch_subtitle_from_url(episode.subtitle_url)
                if subtitle_text:
                    paragraphs = [p.strip() for p in subtitle_text.split("\n") if p.strip()]
                    transcript = TranscriptResult(
                        text=subtitle_text,
                        paragraphs=paragraphs,
                    )
                    asr_engine = "subtitle"
                else:
                    logger.warning("字幕下载失败，回退到 ASR: {}", episode.title)
                    transcript = await self._transcriber.transcribe(episode.audio_url)
            else:
                # 正常 ASR 转写
                await self._state.mark_status(
                    guid,
                    "transcribing",
                    podcast_name=episode.podcast_name,
                    title=episode.title,
                )
                logger.info("开始转写: {}", episode.title)
                transcript = await self._transcriber.transcribe(episode.audio_url)

            # AI 摘要（如果配置了 Poe summarizer 且转写无自带摘要）
            summary_failed = False
            if self._summarizer and transcript.text and not transcript.summary:
                try:
                    logger.info("调用 Poe AI 摘要: {}", episode.title)
                    summary = await self._summarizer.summarize(transcript.text, episode.title)
                    transcript.summary = summary.summary
                    transcript.chapters = summary.chapters
                    transcript.keywords = summary.keywords
                except Exception as e:
                    logger.warning(
                        "AI 摘要失败（重试耗尽），降级为无摘要: {}: {}",
                        type(e).__name__,
                        e,
                    )
                    summary_failed = True

            # 生成 Markdown
            await self._state.mark_status(guid, "writing")
            content = self._md_generator.render(episode, transcript, asr_engine=asr_engine)

            # 写入 Obsidian
            note_path = self._writer.write_note(episode, content)
            await self._state.mark_status(guid, "done", note_path=str(note_path))

            # v1.4.16: upload the rendered note to the shared cache (if
            # configured) so other users sharing this subscription can skip
            # the ASR + summary work. Failures are logged but not raised —
            # the cache is an optimization, never blocks the local pipeline.
            if self._shared_cache is not None:
                try:
                    ok = await self._shared_cache.upload(guid, content)
                    if ok:
                        logger.debug("shared cache upload OK: {}", guid)
                except Exception as e:
                    logger.warning(
                        "shared cache upload raised (treating as no-op): {}: {}",
                        type(e).__name__,
                        e,
                    )

            # 摘要失败时缓存转录结果，后续可用 retry-summaries 补摘要
            if summary_failed:
                from src.summarizer.pending import save_pending

                save_pending(
                    guid=guid,
                    title=episode.title,
                    text=transcript.text,
                    note_path=str(note_path),
                    podcast_name=episode.podcast_name,
                )

            logger.success("处理完成: {} → {}", episode.title, note_path)
            return note_path

        except FileExistsError:
            raise
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

        # 获取新剧集（含失败重试：is_processed 会跳过 done 和超过 max_retries 的）
        new_episodes = await self._rss_checker.check_all()

        if not new_episodes:
            logger.info("没有新剧集需要处理")
            return []

        # 逐个处理（不并发，避免 API 限流）
        results: list[Path] = []
        success_count = 0
        fail_count = 0

        for episode in new_episodes:
            try:
                path = await self.process_episode(episode)
                results.append(path)
                success_count += 1
            except Exception:
                fail_count += 1

        logger.info(
            "处理完成: 共 {} 集, 成功 {}, 失败 {}",
            len(new_episodes),
            success_count,
            fail_count,
        )
        return results
