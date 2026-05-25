from __future__ import annotations

from datetime import datetime
from pathlib import Path

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
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(CREATE_TABLE_SQL)
        await self._db.commit()
        logger.debug("状态数据库已初始化: {}", self._db_path)

    async def close(self):
        """关闭数据库连接"""
        if self._db:
            await self._db.close()

    async def is_processed(self, guid: str, max_retries: int = 3) -> bool:
        """检查剧集是否已完成处理或已超过最大重试次数。

        v1.4.15: ``backfill_skipped`` is also treated as "processed" so that
        episodes the user explicitly opted to skip during onboarding never
        come back as "new" on the next poll.
        """
        assert self._db is not None
        cursor = await self._db.execute(
            """SELECT 1 FROM processed_episodes
               WHERE guid=? AND (
                 status='done'
                 OR status='backfill_skipped'
                 OR (status='failed' AND retry_count >= ?)
               )""",
            (guid, max_retries),
        )
        row = await cursor.fetchone()
        return row is not None

    async def mark_backfill_skipped(self, items: list[tuple[str, str, str]]) -> int:
        """Mark a batch of (guid, podcast_name, title) as ``backfill_skipped``
        in a single transaction.

        Returns the number of rows actually inserted. Uses ``INSERT OR
        IGNORE`` keyed on the existing PRIMARY KEY (``guid``) so:

          * Existing rows — especially ``done`` — are NEVER clobbered.
          * Two concurrent ``StateManager`` connections marking the same
            guid don't race and raise ``IntegrityError`` (Codex audit
            v1.4.15 BUG 2): the second simply becomes a no-op.

        v1.4.15 hardening (Code Review I3 + Codex BUG 2): the previous
        SELECT-then-INSERT loop had both a non-transactional retry hazard
        and a TOCTOU race between concurrent connections; ``INSERT OR
        IGNORE`` collapses both into a single atomic statement per row.
        """
        assert self._db is not None
        if not items:
            return 0
        now = datetime.now().isoformat()
        inserted = 0
        try:
            for guid, podcast_name, title in items:
                cursor = await self._db.execute(
                    """INSERT OR IGNORE INTO processed_episodes
                       (guid, podcast_name, title, status, created_at, updated_at)
                       VALUES (?, ?, ?, 'backfill_skipped', ?, ?)""",
                    (guid, podcast_name, title, now, now),
                )
                # rowcount is 1 on real insert, 0 when IGNORE fired
                if cursor.rowcount > 0:
                    inserted += 1
            await self._db.commit()
        except Exception:
            # Explicit rollback so a mid-loop failure doesn't leave buffered
            # writes hanging on the connection. aiosqlite's close() would
            # implicitly discard them, but being explicit beats relying on
            # close-time behavior.
            await self._db.rollback()
            raise
        return inserted

    async def has_any_recorded_in(self, guids: list[str]) -> bool:
        """Return True if at least one of ``guids`` already has a row in
        ``processed_episodes`` (any status).

        Used by ``RSSChecker._auto_protect_yaml_only_subs`` to decide whether
        a subscription is "brand new" (no row at all for any of its current
        feed entries) → if so, mark every current entry as backfill_skipped
        so the next poll doesn't re-transcribe the whole feed. Matches the
        v1.4.15 GUI-POST backfill protection for hand-edited yaml additions.
        """
        assert self._db is not None
        if not guids:
            return False
        placeholders = ",".join(["?"] * len(guids))
        cursor = await self._db.execute(
            f"SELECT 1 FROM processed_episodes WHERE guid IN ({placeholders}) LIMIT 1",
            guids,
        )
        return await cursor.fetchone() is not None

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
        """更新剧集处理状态.

        v1.5.2 Codex audit fix: previously this was a SELECT-then-UPDATE/
        INSERT sequence without a transaction. Two concurrent connections
        could both pass the SELECT on a brand-new guid and both try the
        INSERT — losing one row to an IntegrityError. Wrap the whole
        check-and-write in an exclusive transaction so retry_count updates
        and first-insert races are both safe.
        """
        assert self._db is not None
        now = datetime.now().isoformat()
        try:
            await self._db.execute("BEGIN IMMEDIATE")
            cursor = await self._db.execute(
                "SELECT retry_count FROM processed_episodes WHERE guid=?",
                (guid,),
            )
            row = await cursor.fetchone()

            if row is not None:
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
                await self._db.execute(
                    """INSERT INTO processed_episodes
                       (guid, podcast_name, title, status, error_msg, note_path,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (guid, podcast_name, title, status, error_msg, note_path, now, now),
                )
            await self._db.commit()
        except Exception:
            await self._db.rollback()
            raise

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

    async def get_recent_history(
        self,
        *,
        limit: int = 50,
        include_backfill_skipped: bool = False,
    ) -> list[ProcessedEpisode]:
        """Bounded query for the history page.

        v1.5.2 Code Review A3 fix: ``get_all()`` was O(N) full table scan
        + Python-side sort + slice on every history request. As state.db
        grows (every ``backfill_skipped`` row from large feeds counts) this
        wastes memory and time. ``ORDER BY updated_at DESC LIMIT ?`` does
        the work in the DB and the filter excludes backfill rows which
        have no note_path and aren't actionable for the user.
        """
        assert self._db is not None
        if include_backfill_skipped:
            where = ""
            params: tuple = (limit,)
        else:
            where = "WHERE status != 'backfill_skipped'"
            params = (limit,)
        cursor = await self._db.execute(
            f"""SELECT guid, podcast_name, title, status, error_msg, retry_count,
                       note_path, created_at, updated_at
                FROM processed_episodes
                {where}
                ORDER BY updated_at DESC
                LIMIT ?""",
            params,
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
