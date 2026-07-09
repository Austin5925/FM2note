"""Core episode processor — single source of truth for download → ASR →
summary → render → write.

Before v1.5.0, the same five stages were re-implemented in two places:

  * ``src/transcribe_flow.py::transcribe_single_url`` — used by the Web UI's
    single-URL transcribe button and the ``fm2note transcribe`` CLI.
  * ``src/pipeline.py::Pipeline.process_episode`` — used by ``fm2note serve``
    when the RSS poller hands it a new episode.

Bug fixes had to be applied twice, the shared cache was wired into only one
of them, and the daemon path had no progress callback at all. v1.5.0
collapses both into this class so:

  * The fix-once / fix-twice problem disappears.
  * Both paths get progress callbacks → the GUI history page can finally
    see daemon-driven episodes light up in real time.
  * Shared-cache short-circuit, MCP dedup, AI summary fallback, and
    state.db lifecycle are all centralized here.

The two old call sites remain thin adapters: they build the ``Episode``
object (their unique input) and pass it in along with a tailored
``ProcessingOptions`` describing which subsystem features to enable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from src.config import AppConfig
from src.models import Episode, TranscriptResult
from src.monitor.state import StateManager
from src.monitor.subtitle import fetch_subtitle_from_url
from src.shared_cache import SharedCacheClient
from src.summarizer.base import Summarizer
from src.transcriber.base import Transcriber
from src.writer.markdown import MarkdownGenerator
from src.writer.obsidian import ObsidianWriter

# (stage, status, message) — sync callback invoked at each stage transition.
# stage:  one of resolve | subtitle_check | asr | summary | write
# status: one of start | done | skipped | error
ProgressCallback = Callable[[str, str, str], None]


@dataclass
class ProcessingOptions:
    """Per-call switches so single-URL and daemon paths can ask for slightly
    different behavior without duplicating code."""

    # Try shared-cache fetch before doing ASR (daemon path: yes; single-URL: no
    # because the user explicitly asked for fresh work via the UI).
    use_shared_cache_fetch: bool = True
    # Upload result to shared cache after a successful local write.
    use_shared_cache_upload: bool = True
    # Run the MCP "is there already a same-titled note?" dedup check.
    do_mcp_dedup: bool = True
    # On summary failure, save the transcript to ``data/pending_summaries/``
    # so ``fm2note retry-summaries`` can pick it up later.
    save_pending_on_summary_fail: bool = True


@dataclass
class ProcessOutcome:
    """What ``EpisodeProcessor.process`` returns."""

    note_path: Path
    char_count: int
    paragraph_count: int
    summary_failed: bool = False
    cache_hit: bool = False  # True if the result came from the shared cache
    # When cache_hit=True or MCP dedup short-circuited, we don't have a real
    # TranscriptResult — fields below are populated only when ASR ran.
    transcript: TranscriptResult | None = None
    asr_engine_used: str = ""  # "funasr" | "subtitle" | "" (cache hit, no ASR)


def _emit(callback: ProgressCallback | None, stage: str, status: str, message: str = "") -> None:
    if callback is None:
        return
    try:
        callback(stage, status, message)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("Progress callback raised: {}: {}", type(e).__name__, e)


@dataclass
class EpisodeProcessor:
    """Shared implementation. Hold injected dependencies; ``process()`` does
    the work."""

    config: AppConfig
    state: StateManager
    transcriber: Transcriber
    md_generator: MarkdownGenerator
    writer: ObsidianWriter
    summarizer: Summarizer | None = None
    shared_cache: SharedCacheClient | None = field(default=None)

    @classmethod
    def from_config(
        cls,
        config: AppConfig,
        state: StateManager,
        *,
        transcriber: Transcriber | None = None,
        summarizer: Summarizer | None = None,
        md_generator: MarkdownGenerator | None = None,
        writer: ObsidianWriter | None = None,
    ) -> EpisodeProcessor:
        """Build a processor wiring up every default-from-config component.

        Callers that already have constructed instances (e.g. existing tests
        with mocks) can use the dataclass constructor directly.
        """
        from src.summarizer.factory import create_summarizer
        from src.transcriber.factory import create_transcriber

        if transcriber is None:
            transcriber = create_transcriber(config)
        if summarizer is None:
            summarizer = create_summarizer(config)
        if md_generator is None:
            template_path = config.template_path
            if template_path:
                tp = Path(template_path)
                md_generator = MarkdownGenerator(template_dir=str(tp.parent), template_name=tp.name)
            else:
                md_generator = MarkdownGenerator()
        if writer is None:
            writer = ObsidianWriter(config.vault_path, config.podcast_dir)
        return cls(
            config=config,
            state=state,
            transcriber=transcriber,
            md_generator=md_generator,
            writer=writer,
            summarizer=summarizer,
            shared_cache=SharedCacheClient.from_env(),
        )

    async def process(
        self,
        episode: Episode,
        *,
        progress_callback: ProgressCallback | None = None,
        options: ProcessingOptions | None = None,
    ) -> ProcessOutcome:
        """Run the full pipeline for one episode. Returns the outcome on
        success; raises on any non-recoverable failure (the writer level —
        ASR / summary handle their own retries internally).

        Stage ordering: shared_cache → mcp_dedup → subtitle_or_asr →
        summary → render → write → shared_cache_upload.
        """
        opts = options or ProcessingOptions()
        guid = episode.guid

        # ---- Stage 0: shared cache short-circuit ----
        # Done before any state mutation so a cache hit is a clean no-op
        # path that never touches the transcriber.
        if opts.use_shared_cache_fetch and self.shared_cache is not None:
            cached = await self._fetch_from_cache(guid, episode.title)
            if cached is not None:
                outcome = await self._handle_cache_hit(episode, cached, progress_callback)
                return outcome

        # ---- Stage 1: MCP dedup (cheap, may short-circuit) ----
        if opts.do_mcp_dedup and await self.writer.search_existing_mcp(episode.title):
            logger.info("MCP 发现同名笔记，跳过: {}", episode.title)
            await self.state.mark_status(
                guid,
                "done",
                podcast_name=episode.podcast_name,
                title=episode.title,
            )
            # Same semantics as the legacy code: raise to signal "skipped
            # because already present". Caller (Pipeline) re-raises into its
            # outer except FileExistsError handler.
            raise FileExistsError(f"MCP 发现同名笔记: {episode.title}")

        # ---- Stage 2: transcript (subtitle or ASR) ----
        transcript, asr_engine = await self._get_transcript(episode, progress_callback)

        # ---- Stage 3: summary (best-effort) ----
        summary_failed = await self._maybe_summarize(transcript, episode.title, progress_callback)

        # ---- Stage 4: render markdown ----
        await self.state.mark_status(guid, "writing")
        content = self.md_generator.render(episode, transcript, asr_engine=asr_engine)

        # ---- Stage 5: write to vault ----
        _emit(progress_callback, "write", "start", "写入笔记...")
        try:
            note_path = self.writer.write_note(episode, content)
        except Exception as e:
            _emit(
                progress_callback,
                "write",
                "error",
                f"写入失败: {type(e).__name__}: {e}",
            )
            raise
        # v1.4.16 + v1.5.0 audit fix: pass podcast_name and title here so the
        # row is fully populated even if upstream mark_status calls were
        # skipped (e.g. cache-hit retry path).
        await self.state.mark_status(
            guid,
            "done",
            podcast_name=episode.podcast_name,
            title=episode.title,
            note_path=str(note_path),
        )
        _emit(progress_callback, "write", "done", str(note_path))

        # ---- Stage 6: shared cache upload (fire-and-forget) ----
        if opts.use_shared_cache_upload and self.shared_cache is not None:
            await self._upload_to_cache(
                guid,
                content,
                podcast_name=episode.podcast_name,
                title=episode.title,
            )

        # ---- Stage 7: pending-summary cache ----
        if summary_failed and opts.save_pending_on_summary_fail:
            from src.summarizer.pending import save_pending

            save_pending(
                guid=guid,
                title=episode.title,
                text=transcript.text,
                note_path=str(note_path),
                podcast_name=episode.podcast_name,
            )

        logger.success("处理完成: {} → {}", episode.title, note_path)
        return ProcessOutcome(
            note_path=note_path,
            char_count=len(transcript.text),
            paragraph_count=len(transcript.paragraphs),
            summary_failed=summary_failed,
            cache_hit=False,
            transcript=transcript,
            asr_engine_used=asr_engine,
        )

    # ------- internal helpers -------

    async def _fetch_from_cache(self, guid: str, title: str) -> str | None:
        try:
            return await self.shared_cache.fetch(guid)
        except Exception as e:
            logger.debug(
                "shared cache fetch raised (treating as miss): {}: {}",
                type(e).__name__,
                e,
            )
            return None

    async def _handle_cache_hit(
        self,
        episode: Episode,
        cached: str,
        progress_callback: ProgressCallback | None,
    ) -> ProcessOutcome:
        guid = episode.guid
        logger.info(
            "shared cache HIT, skipping ASR+summary: {} ({} bytes)",
            episode.title,
            len(cached),
        )
        _emit(progress_callback, "asr", "skipped", "命中共享缓存")
        # Idempotent guard: if the local note already exists (re-run case),
        # don't call write_note (would raise FileExistsError).
        if self.writer.note_exists(episode):
            existing_path = self.writer._build_path(episode)
            logger.info("cache hit but note already on disk — no-op: {}", existing_path)
            await self.state.mark_status(
                guid,
                "done",
                podcast_name=episode.podcast_name,
                title=episode.title,
                note_path=str(existing_path),
            )
            _emit(progress_callback, "write", "skipped", str(existing_path))
            return ProcessOutcome(
                note_path=existing_path,
                char_count=len(cached),
                paragraph_count=cached.count("\n\n") + 1,
                cache_hit=True,
            )
        _emit(progress_callback, "write", "start", "写入缓存命中的笔记...")
        note_path = self.writer.write_note(episode, cached)
        await self.state.mark_status(
            guid,
            "done",
            podcast_name=episode.podcast_name,
            title=episode.title,
            note_path=str(note_path),
        )
        _emit(progress_callback, "write", "done", str(note_path))
        return ProcessOutcome(
            note_path=note_path,
            char_count=len(cached),
            paragraph_count=cached.count("\n\n") + 1,
            cache_hit=True,
        )

    async def _get_transcript(
        self,
        episode: Episode,
        progress_callback: ProgressCallback | None,
    ) -> tuple[TranscriptResult, str]:
        """Return (transcript, asr_engine_used). Honors subtitle_url when
        present; otherwise calls the configured transcriber."""
        guid = episode.guid
        # subtitle fast path
        if episode.subtitle_url:
            await self.state.mark_status(
                guid,
                "transcribing",
                podcast_name=episode.podcast_name,
                title=episode.title,
            )
            _emit(progress_callback, "subtitle_check", "done", "发现内置字幕")
            logger.info("发现内置字幕，跳过 ASR: {}", episode.title)
            subtitle_text = await fetch_subtitle_from_url(episode.subtitle_url)
            if subtitle_text:
                paragraphs = [p.strip() for p in subtitle_text.split("\n") if p.strip()]
                return (
                    TranscriptResult(text=subtitle_text, paragraphs=paragraphs),
                    "subtitle",
                )
            logger.warning("字幕下载失败，回退到 ASR: {}", episode.title)
            _emit(progress_callback, "subtitle_check", "error", "字幕下载失败，回退到 ASR")
        else:
            _emit(progress_callback, "subtitle_check", "skipped", "无内置字幕")

        # ASR path
        await self.state.mark_status(
            guid,
            "transcribing",
            podcast_name=episode.podcast_name,
            title=episode.title,
        )
        _emit(progress_callback, "asr", "start", "语音转文字中...")
        try:
            transcript = await self.transcriber.transcribe(episode.audio_url)
        except Exception as e:
            _emit(
                progress_callback,
                "asr",
                "error",
                f"转写失败: {type(e).__name__}: {e}",
            )
            raise
        logger.info(
            "Transcription done: {} chars, {} paragraphs",
            len(transcript.text),
            len(transcript.paragraphs),
        )
        _emit(
            progress_callback,
            "asr",
            "done",
            f"{len(transcript.text)} 字 · {len(transcript.paragraphs)} 段",
        )
        return transcript, self.config.asr_engine

    async def _maybe_summarize(
        self,
        transcript: TranscriptResult,
        title: str,
        progress_callback: ProgressCallback | None,
    ) -> bool:
        """Returns True if summary was attempted and failed (so caller can
        save_pending). False means no summarizer / not needed / success."""
        if not self.summarizer:
            _emit(progress_callback, "summary", "skipped", "未配置摘要服务")
            return False
        if not transcript.text:
            return False
        if transcript.summary:
            # Engine produced its own (e.g. TingWu). v1.5.0 Code Review #3
            # fix: emit a "skipped" event so the GUI progress bar advances
            # past this stage instead of stalling at asr.
            _emit(progress_callback, "summary", "skipped", "引擎内置摘要")
            return False
        _emit(progress_callback, "summary", "start", "生成 AI 摘要中...")
        try:
            summary = await self.summarizer.summarize(transcript.text, title)
            transcript.analysis = summary.analysis
            transcript.summary = summary.summary
            transcript.chapters = summary.chapters
            transcript.keywords = summary.keywords
            _emit(progress_callback, "summary", "done", "")
            return False
        except Exception as e:
            logger.warning(
                "AI summary failed (retry exhausted), continuing without: {}: {}",
                type(e).__name__,
                e,
            )
            _emit(progress_callback, "summary", "error", f"{type(e).__name__}: {e}")
            return True

    async def _upload_to_cache(
        self,
        guid: str,
        content: str,
        *,
        podcast_name: str = "",
        title: str = "",
    ) -> None:
        try:
            ok = await self.shared_cache.upload(
                guid, content, podcast_name=podcast_name, title=title
            )
            if ok:
                logger.debug("shared cache upload OK: {}", guid)
        except Exception as e:
            logger.warning(
                "shared cache upload raised (treating as no-op): {}: {}",
                type(e).__name__,
                e,
            )
