from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from src.models import Episode


class ObsidianWriter:
    """Obsidian vault 文件写入器"""

    # 文件名非法字符
    ILLEGAL_CHARS = re.compile(r'[/\\:*?"<>|]')

    def __init__(self, vault_path: str, podcast_dir: str = "Podcasts"):
        self._vault_path = Path(vault_path)
        self._podcast_dir = podcast_dir

    def write_note(self, episode: Episode, content: str) -> Path:
        """将 Markdown 内容写入 Obsidian vault。

        路径格式：{vault_path}/{podcast_dir}/{podcast_name}/{date} {title}.md

        Args:
            episode: 剧集信息
            content: Markdown 内容

        Returns:
            写入的文件路径

        Raises:
            FileExistsError: 文件已存在
        """
        note_path = self._build_path(episode)

        if note_path.exists():
            raise FileExistsError(f"笔记已存在: {note_path}")

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(content, encoding="utf-8")

        logger.info("笔记已写入: {}", note_path)
        return note_path

    def note_exists(self, episode: Episode) -> bool:
        """检查笔记文件是否已存在"""
        return self._build_path(episode).exists()

    def _build_path(self, episode: Episode) -> Path:
        """构建笔记文件路径"""
        date_str = episode.pub_date.strftime("%Y-%m-%d")
        title = self._sanitize_filename(episode.title)
        filename = f"{date_str} {title}.md"

        return self._vault_path / self._podcast_dir / episode.podcast_name / filename

    def _sanitize_filename(self, name: str) -> str:
        """清理文件名，移除非法字符并截断"""
        cleaned = self.ILLEGAL_CHARS.sub("", name)
        cleaned = cleaned.strip()
        if len(cleaned) > 200:
            cleaned = cleaned[:200]
        return cleaned or "untitled"
