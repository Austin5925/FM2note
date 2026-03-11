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
        """检查笔记文件是否已存在（文件系统层去重）"""
        return self._build_path(episode).exists()

    async def search_existing_mcp(self, title: str) -> bool:
        """通过 Obsidian MCP 搜索是否已有同名笔记（第三层去重）。

        这是可选的去重机制，MCP 不可用时降级为 False。

        Args:
            title: 笔记标题

        Returns:
            是否找到同名笔记
        """
        try:
            # 延迟导入，MCP 不可用时不影响核心功能
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
        """构建笔记文件路径"""
        date_str = episode.pub_date.strftime("%Y-%m-%d")
        title = self._sanitize_filename(episode.title)
        filename = f"{date_str}-{title}.md"

        return self._vault_path / self._podcast_dir / episode.podcast_name / filename

    def _sanitize_filename(self, name: str) -> str:
        """清理文件名，移除非法字符并截断"""
        cleaned = self.ILLEGAL_CHARS.sub("", name)
        cleaned = cleaned.strip()
        if len(cleaned) > 200:
            cleaned = cleaned[:200]
        return cleaned or "untitled"
