from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from dateutil import parser as dateutil_parser
from loguru import logger

from src.config import AppConfig
from src.models import Episode

ProgressCallback = Callable[[str, str, str], None]
"""(stage, status, message) — sync callback invoked at each pipeline stage.

stage:  one of resolve | subtitle_check | asr | summary | write
status: one of start | done | skipped | error
"""


@dataclass
class TranscribeOutcome:
    """Result of a single-URL transcribe run."""

    note_path: Path
    title: str
    podcast_name: str
    char_count: int
    paragraph_count: int
    elapsed_ms: int
    summary_failed: bool


def _emit(callback: ProgressCallback | None, stage: str, status: str, message: str = "") -> None:
    if callback is None:
        return
    try:
        callback(stage, status, message)
    except Exception as e:
        logger.warning("Progress callback raised: {}: {}", type(e).__name__, e)


async def _resolve_episode_url(
    url: str,
) -> tuple[str, str | None, str | None, str, str | None]:
    """If URL is a Xiaoyuzhou episode page, extract audio URL and metadata.

    Returns:
        (audio_url, title, podcast_name, link, date_published)
    """
    import json
    import re

    import httpx

    if "xiaoyuzhoufm.com/episode/" not in url:
        return url, None, None, "", None

    logger.info("Detected Xiaoyuzhou episode URL, parsing metadata...")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    match = re.search(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.+?)</script>',
        resp.text,
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"Cannot parse metadata from Xiaoyuzhou page: {url}")

    data = json.loads(match.group(1))
    audio_url = data.get("associatedMedia", {}).get("contentUrl", "")
    ep_title = data.get("name")
    ep_podcast = data.get("partOfSeries", {}).get("name")
    date_published = data.get("datePublished")

    if not audio_url:
        raise ValueError(f"Cannot extract audio URL from Xiaoyuzhou page: {url}")

    logger.info("Parsed: {} — {}", ep_podcast, ep_title)
    return audio_url, ep_title, ep_podcast, url, date_published


async def preview_episode(url: str) -> dict:
    """Lightweight metadata fetch used by the GUI before user clicks 转录.

    Returns a dict with: title, podcast_name, link, date_published, audio_url, source.
    For non-Xiaoyuzhou URLs the dict will only have audio_url set.
    """
    audio_url, title, podcast, link, date_pub = await _resolve_episode_url(url)
    return {
        "audio_url": audio_url,
        "title": title,
        "podcast_name": podcast,
        "link": link,
        "date_published": date_pub,
        "source": "xiaoyuzhou" if "xiaoyuzhoufm.com" in url else "direct",
    }


async def transcribe_single_url(
    audio_url: str,
    config: AppConfig,
    *,
    title: str | None = None,
    podcast_name: str = "单独转录",
    progress_callback: ProgressCallback | None = None,
) -> TranscribeOutcome:
    """End-to-end transcribe of a single audio/episode URL.

    Shared by the CLI ``transcribe`` command and the Web ``POST /api/transcribe`` route.
    Emits 5 fixed stages via ``progress_callback`` (resolve / subtitle_check / asr / summary
    / write). Stage ``subtitle_check`` currently always emits ``skipped`` because the
    single-URL flow does not have RSS-feed subtitle metadata.

    Raises:
        Any exception from the transcriber, summarizer (only summary failure is swallowed),
        or writer. The corresponding stage will emit an ``error`` event before propagating.
    """
    from src.summarizer.factory import create_summarizer
    from src.summarizer.pending import save_pending
    from src.transcriber.factory import create_transcriber
    from src.writer.obsidian import ObsidianWriter

    started_at = time.monotonic()

    # Stage 1: resolve URL & metadata
    _emit(progress_callback, "resolve", "start", "解析剧集信息...")
    try:
        resolved_url, ep_title, ep_podcast, link, date_pub = await _resolve_episode_url(audio_url)
    except Exception as e:
        _emit(progress_callback, "resolve", "error", f"解析失败: {e}")
        raise
    if not title and ep_title:
        title = ep_title
    if podcast_name == "单独转录" and ep_podcast:
        podcast_name = ep_podcast
    _emit(progress_callback, "resolve", "done", title or "")

    # Stage 2: subtitle check (currently always skipped for single-URL flow)
    _emit(progress_callback, "subtitle_check", "skipped", "无内置字幕，使用 ASR")

    # Stage 3: ASR
    transcriber = create_transcriber(config)
    _emit(progress_callback, "asr", "start", "语音转文字中...")
    try:
        result = await transcriber.transcribe(resolved_url)
    except Exception as e:
        _emit(progress_callback, "asr", "error", f"转写失败: {type(e).__name__}: {e}")
        raise
    logger.info(
        "Transcription done: {} chars, {} paragraphs",
        len(result.text),
        len(result.paragraphs),
    )
    _emit(
        progress_callback,
        "asr",
        "done",
        f"{len(result.text)} 字 · {len(result.paragraphs)} 段",
    )

    # Stage 4: summary (optional, failures don't abort)
    summary_failed = False
    summarizer = create_summarizer(config)
    if summarizer and result.text and not result.summary:
        _emit(progress_callback, "summary", "start", "生成 AI 摘要中...")
        try:
            summary = await summarizer.summarize(result.text, title or "")
            result.summary = summary.summary
            result.chapters = summary.chapters
            result.keywords = summary.keywords
            _emit(progress_callback, "summary", "done", "")
        except Exception as e:
            logger.warning("AI summary failed, continuing without: {}: {}", type(e).__name__, e)
            summary_failed = True
            _emit(progress_callback, "summary", "error", f"{type(e).__name__}: {e}")
    else:
        _emit(progress_callback, "summary", "skipped", "未配置摘要服务")

    # Title fallback when not provided and not auto-detected
    if not title:
        path = urlparse(resolved_url).path
        title = unquote(path.split("/")[-1]).rsplit(".", 1)[0] or "untitled"

    # Stage 5: write
    pub_date = datetime.now()
    if date_pub:
        with contextlib.suppress(ValueError, TypeError):
            pub_date = dateutil_parser.parse(date_pub)

    episode = Episode(
        guid=resolved_url,
        title=title,
        podcast_name=podcast_name,
        pub_date=pub_date,
        audio_url=resolved_url,
        duration="",
        show_notes="",
        link=link,
    )

    md_generator = _create_md_generator(config)
    content = md_generator.render(episode, result, asr_engine=config.asr_engine)
    writer = ObsidianWriter(config.vault_path, config.podcast_dir)

    _emit(progress_callback, "write", "start", "写入笔记...")
    try:
        note_path = writer.write_note(episode, content)
    except Exception as e:
        _emit(progress_callback, "write", "error", f"写入失败: {type(e).__name__}: {e}")
        raise
    _emit(progress_callback, "write", "done", str(note_path))

    if summary_failed:
        save_pending(
            guid=resolved_url,
            title=title,
            text=result.text,
            note_path=str(note_path),
            podcast_name=podcast_name,
        )

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    return TranscribeOutcome(
        note_path=note_path,
        title=title,
        podcast_name=podcast_name,
        char_count=len(result.text),
        paragraph_count=len(result.paragraphs),
        elapsed_ms=elapsed_ms,
        summary_failed=summary_failed,
    )


def _create_md_generator(config: AppConfig):
    from src.writer.markdown import MarkdownGenerator

    if config.template_path:
        tp = Path(config.template_path)
        return MarkdownGenerator(template_dir=str(tp.parent), template_name=tp.name)
    return MarkdownGenerator()
