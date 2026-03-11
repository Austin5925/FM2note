import asyncio

import click
from loguru import logger

from src.version import VERSION


@click.group()
@click.version_option(version=VERSION)
def cli():
    """FM2note — 小宇宙播客 → Obsidian 笔记自动化管线"""


@cli.command()
@click.option("--config", "config_path", default="config/config.yaml", help="配置文件路径")
@click.option("--subs", "subs_path", default="config/subscriptions.yaml", help="订阅配置路径")
def run_once(config_path: str, subs_path: str):
    """手动执行一次检查和处理"""
    logger.info("FM2note v{} — run-once 模式", VERSION)
    asyncio.run(_run_once(config_path, subs_path))


@cli.command()
@click.option("--config", "config_path", default="config/config.yaml", help="配置文件路径")
@click.option("--subs", "subs_path", default="config/subscriptions.yaml", help="订阅配置路径")
def serve(config_path: str, subs_path: str):
    """启动定时调度服务"""
    logger.info("FM2note v{} — serve 模式", VERSION)
    asyncio.run(_serve(config_path, subs_path))


@cli.command()
@click.argument("audio_url")
@click.option("--title", default=None, help="笔记标题（默认从 URL 提取）")
@click.option("--podcast", "podcast_name", default="单独转录", help="播客名称（用于目录分类）")
@click.option("--config", "config_path", default="config/config.yaml", help="配置文件路径")
def transcribe(audio_url: str, title: str | None, podcast_name: str, config_path: str):
    """单独转写音频 URL，生成 AI 摘要并写入 Obsidian"""
    logger.info("FM2note v{} — 单次转写: {}", VERSION, audio_url)
    asyncio.run(_transcribe(audio_url, title, podcast_name, config_path))


def _create_summarizer(config):
    """创建 Poe 摘要器（如配置了 POE_API_KEY）"""
    if config.poe_api_key:
        from src.summarizer.poe_client import PoeSummarizer

        logger.info("已配置 Poe 摘要: model={}", config.summary_model)
        return PoeSummarizer(
            api_key=config.poe_api_key,
            model=config.summary_model,
        )
    logger.info("未配置 POE_API_KEY，跳过 AI 摘要")
    return None


async def _run_once(config_path: str, subs_path: str):
    from src.config import load_config, load_subscriptions
    from src.downloader.audio import AudioDownloader
    from src.monitor.rss_checker import RSSChecker
    from src.monitor.state import StateManager
    from src.pipeline import Pipeline
    from src.transcriber.factory import create_transcriber
    from src.writer.markdown import MarkdownGenerator
    from src.writer.obsidian import ObsidianWriter

    config = load_config(config_path)
    subscriptions = load_subscriptions(subs_path)

    state = StateManager(config.db_path)
    await state.init()

    try:
        rss_checker = RSSChecker(subscriptions, state)
        downloader = AudioDownloader(config.temp_dir)
        transcriber = create_transcriber(config)
        md_generator = MarkdownGenerator()
        writer = ObsidianWriter(config.vault_path, config.podcast_dir)
        summarizer = _create_summarizer(config)

        pipeline = Pipeline(
            config=config,
            rss_checker=rss_checker,
            downloader=downloader,
            transcriber=transcriber,
            md_generator=md_generator,
            writer=writer,
            state=state,
            summarizer=summarizer,
        )

        results = await pipeline.run_once()
        logger.info("完成: 共处理 {} 个笔记", len(results))
    finally:
        await state.close()


async def _serve(config_path: str, subs_path: str):
    from src.config import load_config, load_subscriptions
    from src.downloader.audio import AudioDownloader
    from src.monitor.rss_checker import RSSChecker
    from src.monitor.state import StateManager
    from src.pipeline import Pipeline
    from src.scheduler import FM2noteScheduler
    from src.transcriber.factory import create_transcriber
    from src.writer.markdown import MarkdownGenerator
    from src.writer.obsidian import ObsidianWriter

    config = load_config(config_path)
    subscriptions = load_subscriptions(subs_path)

    state = StateManager(config.db_path)
    await state.init()

    try:
        rss_checker = RSSChecker(subscriptions, state)
        downloader = AudioDownloader(config.temp_dir)
        transcriber = create_transcriber(config)
        md_generator = MarkdownGenerator()
        writer = ObsidianWriter(config.vault_path, config.podcast_dir)
        summarizer = _create_summarizer(config)

        pipeline = Pipeline(
            config=config,
            rss_checker=rss_checker,
            downloader=downloader,
            transcriber=transcriber,
            md_generator=md_generator,
            writer=writer,
            state=state,
            summarizer=summarizer,
        )

        scheduler = FM2noteScheduler(pipeline, config)
        await scheduler.run_forever()
    finally:
        await state.close()


async def _resolve_episode_url(
    url: str,
) -> tuple[str, str | None, str | None, str, str | None]:
    """如果 URL 是小宇宙剧集页面，解析出音频 URL、标题、播客名、链接和发布日期。

    Returns:
        (audio_url, title, podcast_name, link, date_published)
    """
    import json
    import re

    import httpx

    if "xiaoyuzhoufm.com/episode/" not in url:
        return url, None, None, "", None

    logger.info("检测到小宇宙剧集 URL，解析元数据...")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    # 从 JSON-LD <script type="application/ld+json"> 提取
    match = re.search(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.+?)</script>',
        resp.text,
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"无法从小宇宙页面解析元数据: {url}")

    data = json.loads(match.group(1))
    audio_url = data.get("associatedMedia", {}).get("contentUrl", "")
    ep_title = data.get("name")
    ep_podcast = data.get("partOfSeries", {}).get("name")
    date_published = data.get("datePublished")

    if not audio_url:
        raise ValueError(f"无法从小宇宙页面提取音频 URL: {url}")

    logger.info("解析成功: {} — {}", ep_podcast, ep_title)
    return audio_url, ep_title, ep_podcast, url, date_published


async def _transcribe(
    audio_url: str, title: str | None, podcast_name: str, config_path: str
):
    from datetime import datetime
    from urllib.parse import unquote, urlparse

    from src.config import load_config
    from src.models import Episode
    from src.transcriber.factory import create_transcriber
    from src.writer.markdown import MarkdownGenerator
    from src.writer.obsidian import ObsidianWriter

    config = load_config(config_path)

    from dateutil import parser as dateutil_parser

    # 解析小宇宙剧集 URL → 音频 URL + 元数据
    resolved_url, ep_title, ep_podcast, link, date_pub = await _resolve_episode_url(
        audio_url
    )
    if not title and ep_title:
        title = ep_title
    if podcast_name == "单独转录" and ep_podcast:
        podcast_name = ep_podcast

    # 发布日期：优先用页面解析的，否则用当前时间
    pub_date = datetime.now()
    if date_pub:
        import contextlib

        with contextlib.suppress(ValueError, TypeError):
            pub_date = dateutil_parser.parse(date_pub)

    transcriber = create_transcriber(config)

    # 转写
    result = await transcriber.transcribe(resolved_url)
    logger.info("转写完成: {} 字, {} 段", len(result.text), len(result.paragraphs))

    # AI 摘要
    summarizer = _create_summarizer(config)
    if summarizer and result.text and not result.summary:
        try:
            logger.info("调用 AI 摘要...")
            summary = await summarizer.summarize(result.text, title or "")
            result.summary = summary.summary
            result.chapters = summary.chapters
            result.keywords = summary.keywords
        except Exception as e:
            logger.warning("AI 摘要失败（3 次重试后），降级为无摘要: {}: {}", type(e).__name__, e)

    # 构建 Episode 元数据
    if not title:
        path = urlparse(resolved_url).path
        title = unquote(path.split("/")[-1]).rsplit(".", 1)[0] or "未命名"

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

    # 生成 Markdown 并写入 Obsidian
    md_generator = MarkdownGenerator()
    content = md_generator.render(episode, result, asr_engine=config.asr_engine)
    writer = ObsidianWriter(config.vault_path, config.podcast_dir)
    note_path = writer.write_note(episode, content)

    logger.success("笔记已写入: {}", note_path)


if __name__ == "__main__":
    cli()
