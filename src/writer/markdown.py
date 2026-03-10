from __future__ import annotations

from datetime import datetime

from jinja2 import Environment, FileSystemLoader

from src.models import Episode, TranscriptResult
from src.version import VERSION
from src.writer.html_cleaner import clean_show_notes


class MarkdownGenerator:
    """Jinja2 模板渲染器，生成 Markdown 笔记"""

    def __init__(self, template_dir: str = "templates"):
        self._env = Environment(
            loader=FileSystemLoader(template_dir),
            keep_trailing_newline=True,
        )

    def render(
        self,
        episode: Episode,
        transcript: TranscriptResult,
        asr_engine: str = "tingwu",
    ) -> str:
        """将剧集元数据和转写结果渲染为 Markdown 笔记。

        Args:
            episode: 剧集信息
            transcript: 转写结果
            asr_engine: 使用的 ASR 引擎名称

        Returns:
            渲染后的 Markdown 字符串
        """
        # 清洗 show notes HTML
        cleaned_show_notes = clean_show_notes(episode.show_notes)

        template = self._env.get_template("podcast_note.md.j2")
        return template.render(
            episode=episode,
            transcript=transcript,
            show_notes_cleaned=cleaned_show_notes,
            now=datetime.now(),
            version=VERSION,
            asr_engine=asr_engine,
        )
