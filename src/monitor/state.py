from __future__ import annotations

from datetime import datetime

import aiosqlite
from loguru import logger

from src.models import ProcessedEpisode

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS processed_episodes (
    guid TEXT PRIMARY KEY,
    podcast_name TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error_msg TEXT,
    retry_count INTEGER DEFAULT 0,
    note_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class StateManager:
    """SQLite 状态管理器，跟踪已处理的剧集"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self):
        """初始化数据库连接和表"""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(CREATE_TABLE_SQL)
        await self._db.commit()
        logger.debug("状态数据库已初始化: {}", self._db_path)

    async def close(self):
        """关闭数据库连接"""
        if self._db:
            await self._db.close()

    async def is_processed(self, guid: str) -> bool:
        """检查剧集是否已成功处理"""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT 1 FROM processed_episodes WHERE guid=? AND status='done'",
            (guid,),
        )
        row = await cursor.fetchone()
        return row is not None

    async def mark_status(
        self,
        guid: str,
        status: str,
        *,
        podcast_name: str = "",
        title: str = "",
        error_msg: str | None = None,
        note_path: str | None = None,
    ):
        """更新剧集处理状态（INSERT OR REPLACE）"""
        assert self._db is not None
        now = datetime.now().isoformat()

        # 先查是否存在
        cursor = await self._db.execute(
            "SELECT retry_count FROM processed_episodes WHERE guid=?",
            (guid,),
        )
        row = await cursor.fetchone()

        if row is not None:
            # 更新
            retry_count = row[0]
            if status == "failed":
                retry_count += 1

            update_fields = ["status=?", "updated_at=?"]
            update_values: list = [status, now]

            if error_msg is not None:
                update_fields.append("error_msg=?")
                update_values.append(error_msg)
            if note_path is not None:
                update_fields.append("note_path=?")
                update_values.append(note_path)
            if status == "failed":
                update_fields.append("retry_count=?")
                update_values.append(retry_count)

            update_values.append(guid)
            await self._db.execute(
                f"UPDATE processed_episodes SET {', '.join(update_fields)} WHERE guid=?",
                update_values,
            )
        else:
            # 插入
            await self._db.execute(
                """INSERT INTO processed_episodes
                   (guid, podcast_name, title, status, error_msg, note_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (guid, podcast_name, title, status, error_msg, note_path, now, now),
            )

        await self._db.commit()

    async def get_failed(self, max_retries: int = 3) -> list[ProcessedEpisode]:
        """获取可重试的失败任务"""
        assert self._db is not None
        cursor = await self._db.execute(
            """SELECT guid, podcast_name, title, status, error_msg, retry_count,
                      note_path, created_at, updated_at
               FROM processed_episodes
               WHERE status='failed' AND retry_count < ?""",
            (max_retries,),
        )
        rows = await cursor.fetchall()
        return [
            ProcessedEpisode(
                guid=r[0],
                podcast_name=r[1],
                title=r[2],
                status=r[3],
                error_msg=r[4],
                retry_count=r[5],
                note_path=r[6],
                created_at=datetime.fromisoformat(r[7]) if r[7] else datetime.now(),
                updated_at=datetime.fromisoformat(r[8]) if r[8] else datetime.now(),
            )
            for r in rows
        ]

    async def get_all(self) -> list[ProcessedEpisode]:
        """获取所有处理记录"""
        assert self._db is not None
        cursor = await self._db.execute(
            """SELECT guid, podcast_name, title, status, error_msg, retry_count,
                      note_path, created_at, updated_at
               FROM processed_episodes"""
        )
        rows = await cursor.fetchall()
        return [
            ProcessedEpisode(
                guid=r[0],
                podcast_name=r[1],
                title=r[2],
                status=r[3],
                error_msg=r[4],
                retry_count=r[5],
                note_path=r[6],
                created_at=datetime.fromisoformat(r[7]) if r[7] else datetime.now(),
                updated_at=datetime.fromisoformat(r[8]) if r[8] else datetime.now(),
            )
            for r in rows
        ]
