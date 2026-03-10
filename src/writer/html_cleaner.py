from __future__ import annotations

import re

from markdownify import markdownify


def clean_show_notes(html: str) -> str:
    """将 HTML 格式的 show notes 转为干净的 Markdown。

    处理：
    - 移除 script/style/img 标签及其内容
    - HTML → Markdown 转换（保留链接、列表、加粗等）
    - 去除多余空行（连续 3 个以上空行合并为 2 个）
    - 去除首尾空白

    Args:
        html: HTML 格式的 show notes

    Returns:
        清洗后的 Markdown 文本
    """
    if not html or not html.strip():
        return ""

    # 检测是否是 HTML（包含标签）
    if "<" in html and ">" in html:
        # 先移除 script/style/img 标签及其内容
        cleaned_html = re.sub(
            r"<(script|style)[^>]*>.*?</\1>",
            "",
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        cleaned_html = re.sub(
            r"<img[^>]*>",
            "",
            cleaned_html,
            flags=re.IGNORECASE,
        )

        md = markdownify(cleaned_html)
    else:
        md = html

    # 清理多余空行
    md = re.sub(r"\n{3,}", "\n\n", md)

    # 清理行尾空格
    md = "\n".join(line.rstrip() for line in md.splitlines())

    # 首尾空白
    md = md.strip()

    return md
