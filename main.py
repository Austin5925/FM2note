import asyncio

import click
from loguru import logger

from src.version import VERSION


@click.group()
@click.version_option(version=VERSION)
def cli():
    """FM2note — 小宇宙播客 → Obsidian 笔记自动化管线"""


@cli.command()
def run_once():
    """手动执行一次检查和处理"""
    logger.info("FM2note v{} — run-once 模式", VERSION)
    asyncio.run(_run_once())


@cli.command()
def serve():
    """启动定时调度服务"""
    logger.info("FM2note v{} — serve 模式", VERSION)
    asyncio.run(_serve())


@cli.command()
@click.argument("audio_url")
def transcribe(audio_url: str):
    """单独测试转写一个音频 URL"""
    logger.info("FM2note v{} — 单次转写: {}", VERSION, audio_url)
    asyncio.run(_transcribe(audio_url))


async def _run_once():
    logger.info("run-once 尚未实现，将在 Phase 1 完成")


async def _serve():
    logger.info("serve 尚未实现，将在 Phase 2 完成")


async def _transcribe(audio_url: str):
    logger.info("transcribe 尚未实现，将在 Phase 0.5 完成")


if __name__ == "__main__":
    cli()
