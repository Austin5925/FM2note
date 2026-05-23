from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict, dataclass, field
from typing import Literal

Stage = Literal["resolve", "subtitle_check", "asr", "summary", "write"]
Status = Literal["start", "progress", "done", "skipped", "error"]

STAGES: tuple[Stage, ...] = ("resolve", "subtitle_check", "asr", "summary", "write")


@dataclass
class ProgressEvent:
    """A single progress event pushed onto a task's queue."""

    stage: Stage
    status: Status
    message: str = ""
    percent: int | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaskRecord:
    """Final outcome attached to a task once the pipeline completes."""

    note_path: str | None = None
    title: str | None = None
    podcast_name: str | None = None
    char_count: int = 0
    paragraph_count: int = 0
    elapsed_ms: int = 0
    summary_failed: bool = False
    error: str | None = None


class ProgressBus:
    """In-memory pub/sub for transcribe progress, keyed by task_id.

    Each task gets one asyncio.Queue. The producer (background transcribe task)
    pushes ProgressEvent items. Consumers (SSE endpoints) await get().
    A terminal None sentinel signals stream end.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}
        self._records: dict[str, TaskRecord] = {}
        self._cleanup_delay = 60.0

    def create(self) -> tuple[str, asyncio.Queue]:
        task_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[task_id] = queue
        self._records[task_id] = TaskRecord()
        return task_id, queue

    def get_queue(self, task_id: str) -> asyncio.Queue | None:
        return self._queues.get(task_id)

    def get_record(self, task_id: str) -> TaskRecord | None:
        return self._records.get(task_id)

    def update_record(self, task_id: str, **fields) -> None:
        record = self._records.get(task_id)
        if record is None:
            return
        for key, value in fields.items():
            if hasattr(record, key):
                setattr(record, key, value)

    def publish(self, task_id: str, event: ProgressEvent) -> None:
        queue = self._queues.get(task_id)
        if queue is not None:
            queue.put_nowait(event)

    def close(self, task_id: str) -> None:
        """End the stream and schedule cleanup."""
        queue = self._queues.get(task_id)
        if queue is None:
            return
        queue.put_nowait(None)

        async def _cleanup() -> None:
            await asyncio.sleep(self._cleanup_delay)
            self._queues.pop(task_id, None)
            self._records.pop(task_id, None)

        try:
            asyncio.get_running_loop().create_task(_cleanup())
        except RuntimeError:
            # No running loop (test contexts) — drop immediately
            self._queues.pop(task_id, None)
            self._records.pop(task_id, None)


_bus: ProgressBus | None = None


def get_bus() -> ProgressBus:
    global _bus
    if _bus is None:
        _bus = ProgressBus()
    return _bus


def reset_bus() -> None:
    """Reset the singleton (test helper)."""
    global _bus
    _bus = None
