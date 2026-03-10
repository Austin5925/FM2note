from __future__ import annotations

from datetime import datetime

from jinja2 import Environment, FileSystemLoader

from src.models import Episode, TranscriptResult
from src.version import VERSION


class MarkdownGenerator:
    """Jinja2 模板渲染器，生成 Markdown 笔记"""

    def __init__(self, template_dir: str = "templates"):
        self._env = Environment(
            loader=FileSystemLoader(template_dir),
            keep_trailing_newline=True,
        )

    def render(self, episode: Episode, transcript: TranscriptResult) -> str:
        """将剧集元数据和转写结果渲染为 Markdown 笔记。

        Args:
            episode: 剧集信息
            transcript: 转写结果

        Returns:
            渲染后的 Markdown 字符串
        """
        template = self._env.get_template("podcast_note.md.j2")
        return template.render(
            episode=episode,
            transcript=transcript,
            now=datetime.now(),
            version=VERSION,
            asr_engine="tingwu",
        )
