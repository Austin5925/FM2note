"""Subscription poller pipeline.

Thin orchestrator: ``RSSChecker`` finds new episodes, then we hand each one
to :class:`EpisodeProcessor` for the actual transcribe → summarize → write.
As of v1.5.0 this file owns nothing pipeline-specific — the core work lives
in ``src/episode_processor.py`` and is shared with the single-URL Web flow.

Progress callbacks emitted by ``EpisodeProcessor`` are fanned out to a
module-level subscriber list so the Web layer can attach a daemon-progress
SSE stream and surface live status in the history page.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from src.config import AppConfig
from src.episode_processor import EpisodeProcessor, ProcessingOptions
from src.models import Episode
from src.monitor.rss_checker import RSSChecker
from src.monitor.state import StateManager
from src.summarizer.base import Summarizer
from src.transcriber.base import Transcriber
from src.writer.markdown import MarkdownGenerator
from src.writer.obsidian import ObsidianWriter

# (stage, status, message, episode_guid) — emitted for every stage transition
# during a Pipeline.process_episode call. Callers attach to the global list
# via subscribe_daemon_progress() and receive events from every episode the
# daemon handles. Used by the v1.5.0 GUI history page for live updates.
DaemonProgressCallback = Callable[[str, str, str, str], None]
_daemon_subscribers: list[DaemonProgressCallback] = []


def subscribe_daemon_progress(cb: DaemonProgressCallback) -> Callable[[], None]:
    """Register ``cb`` to receive every Pipeline progress event until the
    returned unsubscribe function is called. Idempotent on duplicate cb."""
    if cb not in _daemon_subscribers:
        _daemon_subscribers.append(cb)

    def _unsub() -> None:
        with contextlib.suppress(ValueError):
            _daemon_subscribers.remove(cb)

    return _unsub


def _broadcast_daemon_event(stage: str, status: str, message: str, guid: str) -> None:
    """Fan-out one event to every subscriber. A misbehaving subscriber is
    logged and skipped — never blocks the pipeline."""
    for cb in list(_daemon_subscribers):
        try:
            cb(stage, status, message, guid)
        except Exception as e:
            logger.warning("daemon progress subscriber raised: {}: {}", type(e).__name__, e)


class Pipeline:
    """Subscription processing orchestrator.

    v1.5.0 reduced this class to a thin wrapper around :class:`EpisodeProcessor`.
    The old "implements its own download/ASR/render/write" version lived here
    until v1.4.16 and duplicated transcribe_flow.py — see CLAUDE.md Version
    History for the rationale.
    """

    def __init__(
        self,
        config: AppConfig,
        rss_checker: RSSChecker,
        transcriber: Transcriber,
        md_generator: MarkdownGenerator,
        writer: ObsidianWriter,
        state: StateManager,
        summarizer: Summarizer | None = None,
        # v1.5.0 audit (Codex debt): _downloader used to be stored here but
        # was never actually called by Pipeline (the transcriber fetches the
        # audio itself via its SDK). Dropped. Keep the keyword for backward
        # compat with old test fixtures and main.py:_serve.
        downloader=None,
    ):
        self._config = config
        self._rss_checker = rss_checker
        self._state = state
        # All actual processing lives here now.
        self._processor = EpisodeProcessor.from_config(
            config,
            state,
            transcriber=transcriber,
            summarizer=summarizer,
            md_generator=md_generator,
            writer=writer,
        )
        # Daemon path WANTS shared cache (both fetch and upload) and MCP
        # dedup; the single-URL Web path opts those off via its own
        # ProcessingOptions.
        self._options = ProcessingOptions(
            use_shared_cache_fetch=True,
            use_shared_cache_upload=True,
            do_mcp_dedup=True,
            save_pending_on_summary_fail=True,
        )
        # Exposed for backward-compat with tests that introspect attributes.
        self._writer = writer
        self._transcriber = transcriber
        self._md_generator = md_generator
        self._summarizer = summarizer

    # ---- backward-compat shims for tests written against pre-v1.5.0 Pipeline ----
    @property
    def _shared_cache(self):
        """Test compatibility: pre-v1.5.0 tests assign Pipeline._shared_cache
        directly to inject a mock. Forward both reads and writes to the
        processor so that monkeypatching keeps working."""
        return self._processor.shared_cache

    @_shared_cache.setter
    def _shared_cache(self, value) -> None:
        self._processor.shared_cache = value

    async def process_episode(self, episode: Episode) -> Path:
        """Process a single episode end-to-end.

        Stages are emitted to both the per-episode state.db (via
        EpisodeProcessor) AND the global daemon subscriber list, so the
        GUI history page can show live progress.

        Raises:
            FileExistsError — when MCP dedup or the local file path indicates
              the note already exists. Caller may swallow this as a "skipped".
            Exception — any other failure marks state as 'failed' and re-raises.
        """
        guid = episode.guid

        def _cb(stage: str, status: str, message: str) -> None:
            _broadcast_daemon_event(stage, status, message, guid)

        try:
            outcome = await self._processor.process(
                episode, progress_callback=_cb, options=self._options
            )
            return outcome.note_path
        except FileExistsError:
            raise
        except Exception as e:
            logger.error("处理失败: {} — {}", episode.title, e)
            await self._state.mark_status(guid, "failed", error_msg=str(e))
            raise

    async def run_once(self) -> list[Path]:
        """One full cycle: check feeds, process each new episode."""
        logger.info("开始检查新剧集...")
        new_episodes = await self._rss_checker.check_all()
        if not new_episodes:
            logger.info("没有新剧集需要处理")
            return []

        results: list[Path] = []
        success_count = 0
        fail_count = 0
        for episode in new_episodes:
            try:
                path = await self.process_episode(episode)
                results.append(path)
                success_count += 1
            except FileExistsError:
                # MCP dedup / on-disk duplicate — not counted as failure.
                pass
            except Exception:
                fail_count += 1

        logger.info(
            "处理完成: 共 {} 集, 成功 {}, 失败 {}",
            len(new_episodes),
            success_count,
            fail_count,
        )
        return results
