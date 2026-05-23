"""Map raw exceptions / status codes to friendly user-facing Chinese text.

Centralized so the transcribe SSE handler and any future routes share the same
tone and vocabulary.
"""

from __future__ import annotations


def friendly_transcribe_error(exc: BaseException) -> str:
    """Translate a transcribe-stage exception into a user-facing message.

    Returns a short string suitable for showing in the GUI without exposing
    stack traces or raw upstream payloads.
    """
    name = type(exc).__name__
    raw = str(exc) or ""
    lower = raw.lower()

    # Common DashScope / OpenAI HTTP status patterns
    if "429" in raw or "rate" in lower and "limit" in lower:
        return "服务限速中，请稍后重试（一般 1 分钟内恢复）"
    if "402" in raw or "insufficient" in lower or "balance" in lower:
        return "API 余额不足，请充值后重试（详见顶部余额徽章）"
    if "401" in raw or "unauthor" in lower or "invalid api key" in lower:
        return "API Key 无效，请到设置页检查"
    if "403" in raw or "forbidden" in lower:
        return "API 拒绝访问（403），请确认 key 权限或配额"
    if "timeout" in lower or "TimeoutError" in name:
        return "请求超时，可能是网络抖动，稍后重试"
    if "FileExistsError" in name or "已存在" in raw:
        return "笔记已存在 — 请到 Obsidian 删除旧笔记后再试"
    if "ValueError" in name and "xiaoyuzhou" in lower:
        return "无法从小宇宙页面解析音频地址，请确认链接是剧集页"
    if "ConnectionError" in name or "connection" in lower:
        return "网络连接失败，请检查网络后重试"

    # Fallback — show type name only, never the raw message
    return f"转录失败（{name}）"
