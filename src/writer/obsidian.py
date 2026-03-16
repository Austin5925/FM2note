from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from src.models import Episode


class ObsidianWriter:
    """Obsidian vault file writer."""

    # Illegal filename characters
    ILLEGAL_CHARS = re.compile(r'[/\\:*?"<>|]')

    def __init__(self, vault_path: str, podcast_dir: str = "Podcasts"):
        self._vault_path = Path(vault_path).resolve()
        self._podcast_dir = podcast_dir

    def write_note(self, episode: Episode, content: str) -> Path:
        """Write Markdown content to Obsidian vault.

        Path format: {vault_path}/{podcast_dir}/{podcast_name}/{date}-{title}.md

        Args:
            episode: Episode info.
            content: Markdown content.

        Returns:
            Written file path.

        Raises:
            FileExistsError: If the note already exists.
            ValueError: If the path would escape the vault directory.
        """
        note_path = self._build_path(episode)

        if note_path.exists():
            raise FileExistsError(f"笔记已存在: {note_path}")

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(content, encoding="utf-8")

        logger.info("笔记已写入: {}", note_path)
        return note_path

    def note_exists(self, episode: Episode) -> bool:
        """Check if note file already exists (filesystem-level dedup)."""
        return self._build_path(episode).exists()

    async def search_existing_mcp(self, title: str) -> bool:
        """Search via Obsidian MCP for an existing note with the same title.

        Optional dedup mechanism. Degrades to False if MCP unavailable.
        """
        try:
            from src.writer.mcp_client import search_notes

            results = await search_notes(title)
            if results:
                logger.info("MCP 搜索发现同名笔记: {}", title)
                return True
        except ImportError:
            logger.debug("Obsidian MCP 客户端不可用，跳过 MCP 去重")
        except Exception as e:
            logger.warning("MCP 搜索失败，降级跳过: {}", e)
        return False

    def _build_path(self, episode: Episode) -> Path:
        """Build note file path with path traversal guard."""
        date_str = episode.pub_date.strftime("%Y-%m-%d")
        title = self._sanitize_filename(episode.title)
        podcast_name = self._sanitize_filename(episode.podcast_name)
        filename = f"{date_str}-{title}.md"

        note_path = (self._vault_path / self._podcast_dir / podcast_name / filename).resolve()

        # Guard against path traversal
        if not note_path.is_relative_to(self._vault_path):
            raise ValueError(f"Path traversal detected: {note_path}")

        return note_path

    def _sanitize_filename(self, name: str) -> str:
        """Sanitize filename: remove illegal chars, strip dots, truncate."""
        cleaned = self.ILLEGAL_CHARS.sub("", name)
        cleaned = cleaned.replace("..", "").strip(". ")
        if len(cleaned) > 200:
            cleaned = cleaned[:200]
        return cleaned or "untitled"
