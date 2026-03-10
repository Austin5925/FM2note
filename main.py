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
@click.option("--config", "config_path", default="config/config.yaml", help="配置文件路径")
def transcribe(audio_url: str, config_path: str):
    """单独测试转写一个音频 URL"""
    logger.info("FM2note v{} — 单次转写: {}", VERSION, audio_url)
    asyncio.run(_transcribe(audio_url, config_path))


async def _run_once(config_path: str, subs_path: str):
    from src.config import load_config, load_subscriptions
    from src.downloader.audio import AudioDownloader
    from src.monitor.rss_checker import RSSChecker
    from src.monitor.state import StateManager
    from src.transcriber.factory import create_transcriber
    from src.writer.markdown import MarkdownGenerator
    from src.writer.obsidian import ObsidianWriter
    from src.pipeline import Pipeline

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

        pipeline = Pipeline(
            config=config,
            rss_checker=rss_checker,
            downloader=downloader,
            transcriber=transcriber,
            md_generator=md_generator,
            writer=writer,
            state=state,
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

        pipeline = Pipeline(
            config=config,
            rss_checker=rss_checker,
            downloader=downloader,
            transcriber=transcriber,
            md_generator=md_generator,
            writer=writer,
            state=state,
        )

        scheduler = FM2noteScheduler(pipeline, config)
        await scheduler.run_forever()
    finally:
        await state.close()


async def _transcribe(audio_url: str, config_path: str):
    from src.config import load_config
    from src.transcriber.factory import create_transcriber

    config = load_config(config_path)
    transcriber = create_transcriber(config)
    result = await transcriber.transcribe(audio_url)
    logger.info("转写完成: {} 字, {} 段", len(result.text), len(result.paragraphs))
    if result.summary:
        logger.info("摘要: {}", result.summary[:200])
    print(result.text)


if __name__ == "__main__":
    cli()
