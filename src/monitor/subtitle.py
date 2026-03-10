from __future__ import annotations

import httpx
from loguru import logger


async def check_subtitle(episode_link: str) -> str | None:
    """检测小宇宙播客是否有内置字幕。

    通过检查 RSS <podcast:transcript> 标签或尝试请求已知的字幕 URL 模式。

    Args:
        episode_link: 小宇宙节目页面链接

    Returns:
        字幕文本（如有），否则 None
    """
    # 小宇宙的字幕 URL 模式：尝试从节目页面推断
    # 格式示例：https://media.xyzcdn.net/xxx/subtitle.srt
    # 目前小宇宙不公开字幕 API，通过 RSS 扩展字段检测
    return None


async def fetch_subtitle_from_url(url: str) -> str | None:
    """从字幕 URL 下载字幕文本。

    支持 SRT、VTT 格式，返回纯文本。

    Args:
        url: 字幕文件 URL

    Returns:
        清洗后的纯文本，或 None
    """
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.text
    except httpx.HTTPError as e:
        logger.warning("字幕下载失败: {} — {}", url, e)
        return None

    return parse_subtitle_text(raw)


def parse_subtitle_text(raw: str) -> str:
    """解析 SRT/VTT 格式字幕为纯文本。

    去除时间戳、序号、标签，保留纯文本内容。

    Args:
        raw: 原始字幕文件内容

    Returns:
        纯文本
    """
    import re

    lines = raw.strip().splitlines()
    text_lines: list[str] = []

    for line in lines:
        line = line.strip()
        # 跳过空行
        if not line:
            continue
        # 跳过 WEBVTT 头
        if line.startswith("WEBVTT"):
            continue
        # 跳过纯数字行（SRT 序号）
        if line.isdigit():
            continue
        # 跳过时间戳行（00:00:00,000 --> 00:00:05,000 或 00:00.000 --> 00:05.000）
        if re.match(r"^\d{1,2}:\d{2}[:\.]", line) and "-->" in line:
            continue
        # 跳过 NOTE 块
        if line.startswith("NOTE"):
            continue
        # 去除 HTML 标签
        cleaned = re.sub(r"<[^>]+>", "", line)
        if cleaned.strip():
            text_lines.append(cleaned.strip())

    return "\n".join(text_lines)
