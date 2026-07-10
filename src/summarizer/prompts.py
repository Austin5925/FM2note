"""Shared prompts for all LLM summarizer providers."""

from __future__ import annotations

from src.models import SummaryResult

SUMMARY_JSON_SCHEMA = (
    '{"analysis": "...", "summary": "...", "chapters": '
    '[{"title": "...", "summary": "..."}], "keywords": ["...", "..."]}'
)

SYSTEM_PROMPT = f"""你是播客内容分析专家。根据播客转写文本，生成：

1. **精简版博客**（对应 JSON 的 `analysis` 字段，放在笔记最前面）：
   这不是摘要或主题归纳，而是信息保真的精简改写。沿着原节目的讨论顺序，保留
   每个实质观点、论据、案例、数据、反例、原因和机制，并保留限制条件、分歧与
   讨论推进关系，让不看全文的读者仍能获得全部重要信息。

   可以合并相邻且相关的表达，把冗长口语改写成更紧凑的书面语，也可以压缩案例和
   解释的措辞；但精简只能减少表达篇幅，不能删除它们承载的不同信息。语义重复的
   内容可以合并，但新增细节必须保留。只删除口头禅、语气词、寒暄、无信息量回应、
   广告和片尾；如果不确定一项内容是否有信息，宁可保留。

   禁止只选择重点或只保留主要主题，禁止把多个不同观点压成一句空泛结论。可以
   修正明显的语音识别断句，但不能补充原文没有的信息。把内容整理成连贯、可独立
   阅读的中文博客，使用 Markdown 小标题和自然段，不保留逐字对话格式。

   篇幅由完整表达全部非重复信息所需的长度自然决定，不设固定字数、比例或段落
   数量。`analysis` 必须是一个包含 Markdown 的 JSON 字符串，不能返回数组或对象。
2. **摘要**（250-500 字，概括核心观点和关键讨论）
3. **章节**（按话题自然分段，每章给出标题和一句话总结）
4. **关键词**（5-10 个核心概念）

严格按以下 JSON 格式输出，不要添加任何其他文字：
{SUMMARY_JSON_SCHEMA}"""


def normalize_condensed_blog(value: object) -> str | None:
    """Normalize the model's ``analysis`` field to Markdown text.

    The schema requires a string, but some OpenAI-compatible models return a
    JSON array of paragraphs. Accept that known wire shape without leaking a
    Python list representation into the rendered note.
    """
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, list):
        paragraphs = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        return "\n\n".join(paragraphs) or None
    return None


def validate_condensed_blog(result: SummaryResult) -> None:
    """Reject a silently missing condensed-blog field."""
    if not result.analysis:
        raise ValueError("摘要响应缺少有效的 analysis（精简版博客）字段")
