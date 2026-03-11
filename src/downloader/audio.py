from __future__ import annotations

from pathlib import Path

import httpx
from loguru import logger


class DownloadError(Exception):
    """下载过程中的错误"""


class AudioDownloader:
    """音频文件下载器，支持断点续传"""

    def __init__(self, temp_dir: str):
        self._temp_dir = Path(temp_dir)
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    async def download(self, audio_url: str, filename: str) -> Path:
        """下载音频文件到临时目录，支持断点续传。

        Args:
            audio_url: 音频文件 URL
            filename: 保存的文件名

        Returns:
            本地文件路径

        Raises:
            DownloadError: 下载失败
        """
        filepath = self._temp_dir / filename

        headers = {}
        initial_size = 0
        if filepath.exists():
            initial_size = filepath.stat().st_size
            headers["Range"] = f"bytes={initial_size}-"
            logger.info("断点续传: {} (已下载 {:.1f}MB)", filename, initial_size / 1e6)

        try:
            async with (
                httpx.AsyncClient(timeout=600, follow_redirects=True) as client,
                client.stream("GET", audio_url, headers=headers) as resp,
            ):
                if resp.status_code == 416:
                    # Range 不满足，文件已完整
                    logger.info("文件已完整: {}", filename)
                    return filepath

                resp.raise_for_status()

                mode = "ab" if initial_size > 0 and resp.status_code == 206 else "wb"
                with open(filepath, mode) as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)

        except httpx.HTTPError as e:
            raise DownloadError(f"下载失败: {e}") from e

        final_size = filepath.stat().st_size
        logger.info("下载完成: {} ({:.1f}MB)", filename, final_size / 1e6)
        return filepath

    async def cleanup(self, filepath: Path):
        """删除临时音频文件"""
        if filepath.exists():
            filepath.unlink()
            logger.debug("已清理临时文件: {}", filepath.name)
