from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.models import SummaryResult


@runtime_checkable
class Summarizer(Protocol):
    """LLM summarizer protocol — any backend must implement this."""

    async def summarize(self, text: str, title: str) -> SummaryResult: ...

    @property
    def name(self) -> str: ...
