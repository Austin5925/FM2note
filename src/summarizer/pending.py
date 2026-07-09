from __future__ import annotations

import hashlib
import json
from pathlib import Path

from loguru import logger

from src.app_paths import app_paths
from src.models import SummaryResult


def _pending_dir() -> Path:
    """v1.5.2 Code Review A5 fix: the old module-level
    ``PENDING_DIR = Path("data/pending_summaries")`` was CWD-relative.
    When ``fm2note app`` was launched by double-clicking from Finder
    (CWD becomes ``/``), pending summaries landed in ``/data/...`` and
    the history page found nothing. Resolve via the AppPaths singleton
    so the location is always anchored to the project root.
    """
    return app_paths().pending_dir


# Backward-compat: tests that monkeypatch ``PENDING_DIR`` directly still
# work via this module-level attribute. Production callers go through
# ``_get_pending_dir()`` which respects test overrides but defaults to the
# AppPaths singleton.
PENDING_DIR: Path | None = None  # tests set this; production reads via getter


def _get_pending_dir() -> Path:
    """Resolve the active pending dir. Test-set ``PENDING_DIR`` wins so
    existing fixtures keep working without changes."""
    if PENDING_DIR is not None:
        return PENDING_DIR
    return _pending_dir()


def save_pending(
    guid: str,
    title: str,
    text: str,
    note_path: str,
    podcast_name: str = "",
) -> Path:
    """保存待补摘要的转录数据。

    Args:
        guid: 剧集唯一标识
        title: 剧集标题（用于 Poe 摘要 prompt）
        text: 转写全文
        note_path: 已写入的笔记路径（补摘要时更新此文件）
        podcast_name: 播客名称

    Returns:
        保存的 JSON 文件路径
    """
    _get_pending_dir().mkdir(parents=True, exist_ok=True)

    safe_name = hashlib.md5(guid.encode()).hexdigest()[:16]
    filepath = _get_pending_dir() / f"{safe_name}.json"

    data = {
        "guid": guid,
        "title": title,
        "podcast_name": podcast_name,
        "text": text,
        "note_path": note_path,
    }
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("已缓存待补摘要: {} → {}", title, filepath.name)
    return filepath


def load_all_pending() -> list[dict]:
    """加载所有待补摘要记录。

    Returns:
        包含 _filepath 字段的 dict 列表
    """
    if not _get_pending_dir().exists():
        return []

    results = []
    for f in sorted(_get_pending_dir().glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_filepath"] = str(f)
            results.append(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("读取 pending 文件失败: {} - {}", f.name, e)
    return results


def remove_pending(filepath: str) -> None:
    """删除已处理的 pending 文件。"""
    Path(filepath).unlink(missing_ok=True)


def insert_summary_into_note(note_path: str, summary: SummaryResult) -> bool:
    """将摘要插入已有笔记文件（在 '## Show Notes' 或 '## 全文转写' 之前）。

    Args:
        note_path: 笔记文件路径
        summary: AI 摘要结果

    Returns:
        是否成功插入
    """
    path = Path(note_path)
    if not path.exists():
        logger.warning("笔记文件不存在，跳过补摘要: {}", note_path)
        return False

    content = path.read_text(encoding="utf-8")

    # 构建摘要 Markdown 片段
    sections: list[str] = []
    if summary.analysis:
        sections.append(f"## 播客内容分析\n\n{summary.analysis}\n")
    if summary.summary:
        sections.append(f"## AI 摘要\n\n{summary.summary}\n")
    if summary.chapters:
        chapter_parts = ["## 章节速览\n"]
        for ch in summary.chapters:
            chapter_parts.append(f"### {ch['title']}\n")
            chapter_parts.append(f"{ch['summary']}\n")
        sections.append("\n".join(chapter_parts))

    if not sections:
        return False

    summary_md = "\n".join(sections) + "\n"

    # 在 "## Show Notes" 或 "## 全文转写" 前插入
    for marker in ("## Show Notes", "## 全文转写"):
        if marker in content:
            content = content.replace(marker, summary_md + marker, 1)
            path.write_text(content, encoding="utf-8")
            logger.info("摘要已插入笔记: {}", path.name)
            return True

    logger.warning("笔记中未找到插入点，跳过: {}", note_path)
    return False
