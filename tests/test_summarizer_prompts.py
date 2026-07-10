from __future__ import annotations

import pytest

from src.models import SummaryResult
from src.summarizer.prompts import (
    SYSTEM_PROMPT,
    normalize_condensed_blog,
    validate_condensed_blog,
)


def test_condensed_blog_prompt_preserves_information_without_fixed_length():
    assert "**精简版博客**" in SYSTEM_PROMPT
    for required in (
        "观点",
        "论据",
        "案例",
        "数据",
        "反例",
        "讨论推进关系",
        "口头禅",
        "寒暄",
        "无信息量回应",
        "精简改写",
        "新增细节必须保留",
        "精简只能减少表达篇幅",
        "宁可保留",
    ):
        assert required in SYSTEM_PROMPT

    assert "不设固定字数、比例或" in SYSTEM_PROMPT
    assert "3000" not in SYSTEM_PROMPT
    assert "10 倍" not in SYSTEM_PROMPT
    assert "2-5 分钟" not in SYSTEM_PROMPT


def test_existing_summary_chapter_and_keyword_instructions_are_unchanged():
    assert "2. **摘要**（250-500 字，概括核心观点和关键讨论）" in SYSTEM_PROMPT
    assert "3. **章节**（按话题自然分段，每章给出标题和一句话总结）" in SYSTEM_PROMPT
    assert "4. **关键词**（5-10 个核心概念）" in SYSTEM_PROMPT


def test_normalize_condensed_blog_accepts_string_or_real_world_array():
    assert normalize_condensed_blog("  正文  ") == "正文"
    assert normalize_condensed_blog(["第一段", " ", "第二段"]) == "第一段\n\n第二段"
    assert normalize_condensed_blog({"unexpected": "shape"}) is None


def test_validate_condensed_blog_checks_presence_not_length():
    validate_condensed_blog(SummaryResult(summary="很长的摘要" * 100, analysis="短但有效"))

    with pytest.raises(ValueError, match="缺少有效"):
        validate_condensed_blog(SummaryResult(summary="摘要", analysis=None))
