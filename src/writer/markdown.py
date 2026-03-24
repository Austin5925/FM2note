from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.models import Episode, TranscriptResult
from src.version import VERSION
from src.writer.html_cleaner import clean_show_notes

# Package-bundled templates directory (inside src/templates/)
_PACKAGE_TEMPLATE_DIR = str(Path(__file__).resolve().parent.parent / "templates")

# Default section labels (Chinese for backward compatibility)
DEFAULT_LABELS = {
    "ai_summary": "AI 摘要",
    "chapters": "章节速览",
    "show_notes": "Show Notes",
    "transcript": "全文转写",
    "podcast": "播客",
    "date": "日期",
    "duration": "时长",
    "link": "链接",
    "link_text": "小宇宙",
    "footer": "由 FM2note v{version} 自动生成",
}


class MarkdownGenerator:
    """Jinja2 template renderer for Markdown notes."""

    def __init__(
        self,
        template_dir: str | None = None,
        template_name: str = "podcast_note.md.j2",
        labels: dict[str, str] | None = None,
    ):
        # Resolve template directory: explicit > CWD "templates/" > package-bundled
        if template_dir is None:
            cwd_templates = Path("templates")
            template_dir = str(cwd_templates) if cwd_templates.is_dir() else _PACKAGE_TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(template_dir),
            keep_trailing_newline=True,
        )
        self._template_name = template_name
        self._labels = {**DEFAULT_LABELS, **(labels or {})}

    def render(
        self,
        episode: Episode,
        transcript: TranscriptResult,
        asr_engine: str = "tingwu",
    ) -> str:
        """Render episode metadata and transcript into a Markdown note.

        Args:
            episode: Episode information.
            transcript: Transcription result.
            asr_engine: Name of the ASR engine used.

        Returns:
            Rendered Markdown string.
        """
        cleaned_show_notes = clean_show_notes(episode.show_notes)

        template = self._env.get_template(self._template_name)
        return template.render(
            episode=episode,
            transcript=transcript,
            show_notes_cleaned=cleaned_show_notes,
            now=datetime.now(),
            version=VERSION,
            asr_engine=asr_engine,
            labels=self._labels,
        )
