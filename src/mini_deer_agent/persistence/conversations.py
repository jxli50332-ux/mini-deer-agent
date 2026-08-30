"""使用独立 SQLite 业务库保存 Thread、Run、Message 与 ToolExecution。"""

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, cast
from uuid import uuid4

from mini_deer_agent.application.conversations import (
    ActiveRunConflictError,
    ActiveThreadDeleteConflictError,
)
from mini_deer_agent.application.run_events import RunEventSequenceError
from mini_deer_agent.domain import (
    ConversationHistoryPage,
    MessageHistoryItem,
    RunRecord,
    StoredRunEventRecord,
    TextAttachment,
    TextAttachmentMetadata,
    ThreadRecord,
    TimelineHistoryItem,
    ToolExecutionHistoryItem,
    default_thread_title,
)
from mini_deer_agent.streaming.events import RunEvent


_LATEST_MIGRATION_VERSION = 5

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS threads (
        thread_id TEXT PRIMARY KEY,
        status TEXT NOT NULL CHECK (status IN ('idle', 'busy', 'error')),
        next_sequence INTEGER NOT NULL DEFAULT 1 CHECK (next_sequence >= 1),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
        user_message_id TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (
            status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'interrupted')
        ),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        finish_reason TEXT,
        error_code TEXT
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_thread_active
    ON runs(thread_id)
    WHERE status IN ('pending', 'running')
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_runs_thread_created
    ON runs(thread_id, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS timeline_items (
        item_id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        thread_sequence INTEGER NOT NULL CHECK (thread_sequence >= 1),
        kind TEXT NOT NULL CHECK (kind IN ('message', 'tool')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_timeline_items_thread_sequence
    ON timeline_items(thread_id, thread_sequence)
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        item_id TEXT PRIMARY KEY REFERENCES timeline_items(item_id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_executions (
        item_id TEXT PRIMARY KEY REFERENCES timeline_items(item_id) ON DELETE CASCADE,
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        tool_call_id TEXT NOT NULL,
        name TEXT,
        input TEXT NOT NULL DEFAULT '',
        result TEXT,
        status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed', 'cancelled')),
        UNIQUE(run_id, tool_call_id)
    )
    """,
)

# 迁移逐版执行，确保已有 v1 产品数据库无需删除即可补上最近 Thread 查询索引。
_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: _SCHEMA_STATEMENTS,
    2: (
        """
        CREATE INDEX IF NOT EXISTS idx_threads_recent
        ON threads(updated_at DESC, thread_id DESC)
        """,
    ),
    3: (
        """
        CREATE TABLE IF NOT EXISTS run_events (
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence >= 1),
            version TEXT NOT NULL,
            event TEXT NOT NULL CHECK (
                event IN (
                    'run_started', 'ai_delta', 'tool_call_delta', 'tool_result',
                    'run_error', 'run_interrupted', 'run_completed'
                )
            ),
            message_id TEXT,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, sequence)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_run_events_thread_run_sequence
        ON run_events(thread_id, run_id, sequence)
        """,
    ),
    4: (
        """
        ALTER TABLE threads ADD COLUMN title TEXT
        """,
    ),
    5: (
        """
        CREATE TABLE IF NOT EXISTS text_attachments (
            attachment_id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL REFERENCES messages(item_id) ON DELETE CASCADE,
            thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
            position INTEGER NOT NULL CHECK (position >= 0),
            filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 1),
            content TEXT NOT NULL,
            UNIQUE(message_id, position)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_text_attachments_thread_message
        ON text_attachments(thread_id, message_id, position)
        """,
    ),
}


def _utc_now() -> str:
    """返回可按字符串比较的 UTC ISO 时间。"""
    return datetime.now(UTC).isoformat()


class SqliteConversationRepository:
    """以同一事务保存产品投影和原始 RunEvent，读取端口仍保持逻辑分离。"""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """保存长生命周期连接并初始化版本化 schema。"""
        self._connection = connection
        self._lock = RLock()
        self._setup()

    def _setup(self) -> None:
        """应用幂等迁移，并把上次异常退出的活动 Run 标记为 interrupted。"""
        with self._lock, self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            # 每一版单独登记；旧数据库跳过已应用版本并继续升级到最新版。
            for version in range(1, _LATEST_MIGRATION_VERSION + 1):
                applied = self._connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?",
                    (version,),
                ).fetchone()
                if applied is not None:
                    continue
                for statement in _MIGRATIONS[version]:
                    self._connection.execute(statement)
                self._connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, _utc_now()),
                )

            recovered_at = _utc_now()
            self._connection.execute(
                """
                UPDATE runs
                SET status = 'interrupted', updated_at = ?, finished_at = ?, error_code = 'server_restarted'
                WHERE status IN ('pending', 'running')
                """,
                (recovered_at, recovered_at),
            )
            self._connection.execute(
                """
                UPDATE threads
                SET status = 'idle', updated_at = ?
                WHERE status = 'busy'
                  AND NOT EXISTS (
                      SELECT 1 FROM runs
                      WHERE runs.thread_id = threads.thread_id
                        AND runs.status IN ('pending', 'running')
                  )
                """,
                (recovered_at,),
            )
        # 迁移后收集查询规划统计，索引只围绕当前正式查询创建。
        self._connection.execute("PRAGMA optimize")

    @staticmethod
    def _allocate_sequence(cursor: sqlite3.Cursor, thread_id: str) -> int:
        """在当前事务中原子分配一个 Thread 全局时间线序号。"""
        row = cursor.execute(
            "SELECT next_sequence FROM threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Thread must exist before allocating a sequence")
        sequence = int(row[0])
        cursor.execute(
            "UPDATE threads SET next_sequence = ? WHERE thread_id = ?",
            (sequence + 1, thread_id),
        )
        return sequence

    def create_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        user_message_id: str,
        user_message: str,
        attachments: tuple[TextAttachment, ...] = (),
    ) -> None:
        """原子写入 Thread、Run、用户消息和附件，拒绝并发活动 Run。"""
        now = _utc_now()
        title = default_thread_title(user_message)
        try:
            with self._lock, self._connection:
                cursor = self._connection.cursor()
                cursor.execute(
                    """
                    INSERT INTO threads(thread_id, title, status, next_sequence, created_at, updated_at)
                    VALUES (?, ?, 'busy', 1, ?, ?)
                    ON CONFLICT(thread_id) DO UPDATE SET status = 'busy', updated_at = excluded.updated_at
                    """,
                    (thread_id, title, now, now),
                )
                cursor.execute(
                    """
                    INSERT INTO runs(
                        run_id, thread_id, user_message_id, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (run_id, thread_id, user_message_id, now, now),
                )
                sequence = self._allocate_sequence(cursor, thread_id)
                cursor.execute(
                    """
                    INSERT INTO timeline_items(
                        item_id, thread_id, run_id, thread_sequence, kind, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'message', ?, ?)
                    """,
                    (user_message_id, thread_id, run_id, sequence, now, now),
                )
                cursor.execute(
                    "INSERT INTO messages(item_id, role, content) VALUES (?, 'user', ?)",
                    (user_message_id, user_message),
                )
                for position, attachment in enumerate(attachments):
                    cursor.execute(
                        """
                        INSERT INTO text_attachments(
                            attachment_id, message_id, thread_id, position,
                            filename, media_type, size_bytes, content
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid4()),
                            user_message_id,
                            thread_id,
                            position,
                            attachment.filename,
                            attachment.media_type,
                            attachment.size_bytes,
                            attachment.content,
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            # 部分唯一索引和消息 ID 唯一约束共同阻止并发或重复提交污染历史。
            raise ActiveRunConflictError(
                "Thread already has an active run or duplicate message identity"
            ) from exc

    def _require_run(
        self,
        cursor: sqlite3.Cursor,
        event: RunEvent,
    ) -> str:
        """验证事件所属 Run 与 Thread，并返回事务内观察到的状态。"""
        row = cursor.execute(
            "SELECT thread_id, status FROM runs WHERE run_id = ?",
            (event.run_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Run must exist before applying events")
        if str(row[0]) != event.thread_id:
            raise RuntimeError("Run event thread does not match persisted run")
        return str(row[1])

    def _ensure_timeline_item(
        self,
        cursor: sqlite3.Cursor,
        *,
        item_id: str,
        thread_id: str,
        run_id: str,
        kind: str,
        now: str,
    ) -> bool:
        """确保时间线基项存在，返回本次是否创建了新项。"""
        row = cursor.execute(
            "SELECT thread_id, run_id, kind FROM timeline_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        if row is not None:
            if tuple(row) != (thread_id, run_id, kind):
                raise RuntimeError("Timeline item identity collision")
            return False

        sequence = self._allocate_sequence(cursor, thread_id)
        cursor.execute(
            """
            INSERT INTO timeline_items(
                item_id, thread_id, run_id, thread_sequence, kind, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, thread_id, run_id, sequence, kind, now, now),
        )
        return True

    def apply_run_event(self, event: RunEvent) -> bool:
        """原子保存原始事件并物化历史，终态竞争失败时两者都不写入。"""
        now = _utc_now()
        with self._lock, self._connection:
            cursor = self._connection.cursor()
            run_status = self._require_run(cursor, event)
            if run_status not in {"pending", "running"}:
                # 取消与自然完成竞争时，以第一个写入的终态为准。
                return False

            # Mini Deer 的 sequence 属于单个 Run。严格要求下一值恰好为 max + 1，
            # 这样未来按游标重放时不会把缺口误认为完整历史。
            last_sequence_row = cursor.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM run_events WHERE run_id = ?",
                (event.run_id,),
            ).fetchone()
            last_sequence = int(last_sequence_row[0])
            if event.sequence != last_sequence + 1:
                raise RunEventSequenceError(
                    "RunEvent sequence must be contiguous within one run"
                )
            payload_json = json.dumps(
                dict(event.payload),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            cursor.execute(
                """
                INSERT INTO run_events(
                    run_id, thread_id, sequence, version, event,
                    message_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.thread_id,
                    event.sequence,
                    event.version,
                    event.event,
                    event.message_id,
                    payload_json,
                    now,
                ),
            )

            if event.event == "run_started":
                started_at = str(event.payload.get("created_at") or now)
                cursor.execute(
                    """
                    UPDATE runs
                    SET status = 'running', started_at = COALESCE(started_at, ?), updated_at = ?
                    WHERE run_id = ?
                    """,
                    (started_at, now, event.run_id),
                )
                return True

            if event.event == "ai_delta":
                item_id = event.message_id or f"{event.run_id}:assistant"
                created = self._ensure_timeline_item(
                    cursor,
                    item_id=item_id,
                    thread_id=event.thread_id,
                    run_id=event.run_id,
                    kind="message",
                    now=now,
                )
                text = str(event.payload.get("text") or "")
                if created:
                    cursor.execute(
                        "INSERT INTO messages(item_id, role, content) VALUES (?, 'assistant', ?)",
                        (item_id, text),
                    )
                else:
                    cursor.execute(
                        "UPDATE messages SET content = content || ? WHERE item_id = ?",
                        (text, item_id),
                    )
                cursor.execute(
                    "UPDATE timeline_items SET updated_at = ? WHERE item_id = ?",
                    (now, item_id),
                )
                return True

            if event.event == "tool_call_delta":
                tool_call_id = str(event.payload["tool_call_id"])
                item_id = f"tool:{event.run_id}:{tool_call_id}"
                created = self._ensure_timeline_item(
                    cursor,
                    item_id=item_id,
                    thread_id=event.thread_id,
                    run_id=event.run_id,
                    kind="tool",
                    now=now,
                )
                name = event.payload.get("name")
                arguments_delta = str(event.payload.get("arguments_delta") or "")
                if created:
                    cursor.execute(
                        """
                        INSERT INTO tool_executions(
                            item_id, run_id, tool_call_id, name, input, result, status
                        ) VALUES (?, ?, ?, ?, ?, NULL, 'pending')
                        """,
                        (item_id, event.run_id, tool_call_id, name, arguments_delta),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE tool_executions
                        SET name = COALESCE(name, ?), input = input || ?
                        WHERE item_id = ? AND status = 'pending'
                        """,
                        (name, arguments_delta, item_id),
                    )
                cursor.execute(
                    "UPDATE timeline_items SET updated_at = ? WHERE item_id = ?",
                    (now, item_id),
                )
                return True

            if event.event == "tool_result":
                tool_call_id = str(event.payload["tool_call_id"])
                item_id = f"tool:{event.run_id}:{tool_call_id}"
                created = self._ensure_timeline_item(
                    cursor,
                    item_id=item_id,
                    thread_id=event.thread_id,
                    run_id=event.run_id,
                    kind="tool",
                    now=now,
                )
                name = event.payload.get("name")
                result = str(event.payload.get("content") or "")
                if created:
                    cursor.execute(
                        """
                        INSERT INTO tool_executions(
                            item_id, run_id, tool_call_id, name, input, result, status
                        ) VALUES (?, ?, ?, ?, '', ?, 'completed')
                        """,
                        (item_id, event.run_id, tool_call_id, name, result),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE tool_executions
                        SET name = COALESCE(name, ?), result = ?, status = 'completed'
                        WHERE item_id = ?
                        """,
                        (name, result, item_id),
                    )
                cursor.execute(
                    "UPDATE timeline_items SET updated_at = ? WHERE item_id = ?",
                    (now, item_id),
                )
                return True

            if event.event == "run_error":
                cursor.execute(
                    """
                    UPDATE runs
                    SET status = 'failed', updated_at = ?, finished_at = ?, error_code = ?
                    WHERE run_id = ?
                    """,
                    (now, now, str(event.payload.get("code") or "run_failed"), event.run_id),
                )
                cursor.execute(
                    "UPDATE tool_executions SET status = 'failed' WHERE run_id = ? AND status = 'pending'",
                    (event.run_id,),
                )
                cursor.execute(
                    "UPDATE threads SET status = 'error', updated_at = ? WHERE thread_id = ?",
                    (now, event.thread_id),
                )
                return True

            if event.event == "run_interrupted":
                reason = str(event.payload.get("reason") or "interrupted")
                updated = cursor.execute(
                    """
                    UPDATE runs
                    SET status = 'interrupted', updated_at = ?, finished_at = ?,
                        finish_reason = ?, error_code = NULL
                    WHERE run_id = ? AND status IN ('pending', 'running')
                    """,
                    (now, now, reason, event.run_id),
                )
                # 自然终态与取消竞争时，已经完成的事实不能被迟到取消覆盖。
                if updated.rowcount == 0:
                    return False
                cursor.execute(
                    "UPDATE tool_executions SET status = 'cancelled' WHERE run_id = ? AND status = 'pending'",
                    (event.run_id,),
                )
                cursor.execute(
                    "UPDATE threads SET status = 'idle', updated_at = ? WHERE thread_id = ?",
                    (now, event.thread_id),
                )
                return True

            if event.event == "run_completed":
                cursor.execute(
                    """
                    UPDATE runs
                    SET status = 'completed', updated_at = ?, finished_at = ?, finish_reason = ?
                    WHERE run_id = ?
                    """,
                    (now, now, str(event.payload.get("finish_reason") or "stop"), event.run_id),
                )
                cursor.execute(
                    "UPDATE threads SET status = 'idle', updated_at = ? WHERE thread_id = ?",
                    (now, event.thread_id),
                )
                return True

            raise RuntimeError(f"Unsupported RunEvent: {event.event}")

    def list_run_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        after_sequence: int,
        limit: int,
    ) -> tuple[StoredRunEventRecord, ...]:
        """使用前向游标按原始 Run sequence 正序读取 Event Store。"""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT version, event, run_id, thread_id, sequence,
                       message_id, payload_json, created_at
                FROM run_events
                WHERE thread_id = ? AND run_id = ? AND sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (thread_id, run_id, after_sequence, limit),
            ).fetchall()

        records: list[StoredRunEventRecord] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                # 写入端只接受对象；若磁盘被外部篡改则失败关闭，不能伪造协议。
                raise RuntimeError("Stored RunEvent payload must be a JSON object")
            records.append(
                StoredRunEventRecord(
                    version=str(row["version"]),
                    event=str(row["event"]),
                    run_id=str(row["run_id"]),
                    thread_id=str(row["thread_id"]),
                    sequence=int(row["sequence"]),
                    message_id=cast(str | None, row["message_id"]),
                    payload=cast(dict[str, Any], payload),
                    created_at=str(row["created_at"]),
                )
            )
        return tuple(records)

    def interrupt_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        error_code: str,
    ) -> None:
        """把未终止 Run 标记为 interrupted，并让 Thread 可以接受下一轮。"""
        now = _utc_now()
        with self._lock, self._connection:
            updated = self._connection.execute(
                """
                UPDATE runs
                SET status = 'interrupted', updated_at = ?, finished_at = ?, error_code = ?
                WHERE run_id = ? AND thread_id = ? AND status IN ('pending', 'running')
                """,
                (now, now, error_code, run_id, thread_id),
            )
            if updated.rowcount == 0:
                return
            self._connection.execute(
                "UPDATE tool_executions SET status = 'cancelled' WHERE run_id = ? AND status = 'pending'",
                (run_id,),
            )
            self._connection.execute(
                "UPDATE threads SET status = 'idle', updated_at = ? WHERE thread_id = ?",
                (now, thread_id),
            )

    def get_run(self, run_id: str) -> RunRecord | None:
        """按主键读取一个 Run，以持久化记录作为生命周期事实。"""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT run_id, thread_id, status, user_message_id, created_at,
                       started_at, finished_at, finish_reason, error_code
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return RunRecord(
            run_id=str(row["run_id"]),
            thread_id=str(row["thread_id"]),
            status=cast(Any, row["status"]),
            user_message_id=str(row["user_message_id"]),
            created_at=str(row["created_at"]),
            started_at=cast(str | None, row["started_at"]),
            finished_at=cast(str | None, row["finished_at"]),
            finish_reason=cast(str | None, row["finish_reason"]),
            error_code=cast(str | None, row["error_code"]),
        )

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """按主键查询 Thread 元数据。"""
        with self._lock:
            row = self._connection.execute(
                "SELECT thread_id, title, status, created_at, updated_at FROM threads WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return ThreadRecord(
            thread_id=str(row["thread_id"]),
            title=cast(str | None, row["title"]),
            status=cast(Any, row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list_threads(self, *, limit: int) -> tuple[ThreadRecord, ...]:
        """使用最近活动索引稳定倒序查询产品 Thread。"""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT thread_id, title, status, created_at, updated_at
                FROM threads
                ORDER BY updated_at DESC, thread_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(
            ThreadRecord(
                thread_id=str(row["thread_id"]),
                title=cast(str | None, row["title"]),
                status=cast(Any, row["status"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        )

    def update_thread_title(
        self,
        thread_id: str,
        title: str,
    ) -> ThreadRecord | None:
        """在业务库内更新标题和活动时间，并返回提交后的服务端事实。"""
        now = _utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE threads SET title = ?, updated_at = ? WHERE thread_id = ?",
                (title, now, thread_id),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_thread(thread_id)

    def delete_thread(self, thread_id: str) -> bool:
        """原子拒绝活动 Thread，或由外键级联删除其完整业务历史。"""
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT status FROM threads WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] == "busy":
                raise ActiveThreadDeleteConflictError(
                    f"Thread {thread_id} still has an active run"
                )
            cursor = self._connection.execute(
                "DELETE FROM threads WHERE thread_id = ?",
                (thread_id,),
            )
        return cursor.rowcount > 0

    def list_runs(self, thread_id: str, *, limit: int) -> tuple[RunRecord, ...]:
        """使用 Thread 与创建时间复合索引查询最近 Run。"""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT run_id, thread_id, status, user_message_id, created_at,
                       started_at, finished_at, finish_reason, error_code
                FROM runs
                WHERE thread_id = ?
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        return tuple(
            RunRecord(
                run_id=str(row["run_id"]),
                thread_id=str(row["thread_id"]),
                status=cast(Any, row["status"]),
                user_message_id=str(row["user_message_id"]),
                created_at=str(row["created_at"]),
                started_at=cast(str | None, row["started_at"]),
                finished_at=cast(str | None, row["finished_at"]),
                finish_reason=cast(str | None, row["finish_reason"]),
                error_code=cast(str | None, row["error_code"]),
            )
            for row in rows
        )

    def list_history(
        self,
        thread_id: str,
        *,
        limit: int,
        before_sequence: int | None,
    ) -> ConversationHistoryPage:
        """读取最新一页并反转为前端需要的时间正序。"""
        if self.get_thread(thread_id) is None:
            return ConversationHistoryPage(
                thread_id=thread_id,
                thread_exists=False,
                items=(),
                has_more=False,
                next_before_sequence=None,
            )

        parameters: list[object] = [thread_id]
        cursor_clause = ""
        if before_sequence is not None:
            cursor_clause = "AND timeline_items.thread_sequence < ?"
            parameters.append(before_sequence)
        parameters.append(limit + 1)

        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT timeline_items.item_id, timeline_items.thread_id,
                       timeline_items.run_id, timeline_items.thread_sequence,
                       timeline_items.kind, timeline_items.created_at,
                       messages.role, messages.content,
                       tool_executions.tool_call_id, tool_executions.name,
                       tool_executions.input, tool_executions.result,
                       tool_executions.status AS tool_status
                FROM timeline_items
                LEFT JOIN messages ON messages.item_id = timeline_items.item_id
                LEFT JOIN tool_executions ON tool_executions.item_id = timeline_items.item_id
                WHERE timeline_items.thread_id = ? {cursor_clause}
                ORDER BY timeline_items.thread_sequence DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        has_more = len(rows) > limit
        selected_rows = rows[:limit]
        message_ids = [
            str(row["item_id"])
            for row in selected_rows
            if row["kind"] == "message"
        ]
        attachments_by_message: dict[str, list[TextAttachmentMetadata]] = {}
        if message_ids:
            placeholders = ",".join("?" for _ in message_ids)
            with self._lock:
                attachment_rows = self._connection.execute(
                    f"""
                    SELECT message_id, filename, media_type, size_bytes
                    FROM text_attachments
                    WHERE message_id IN ({placeholders})
                    ORDER BY message_id, position
                    """,
                    message_ids,
                ).fetchall()
            for attachment_row in attachment_rows:
                message_id = str(attachment_row["message_id"])
                attachments_by_message.setdefault(message_id, []).append(
                    TextAttachmentMetadata(
                        filename=str(attachment_row["filename"]),
                        media_type=str(attachment_row["media_type"]),
                        size_bytes=int(attachment_row["size_bytes"]),
                    )
                )
        items: list[TimelineHistoryItem] = []
        for row in reversed(selected_rows):
            common = {
                "item_id": str(row["item_id"]),
                "thread_id": str(row["thread_id"]),
                "run_id": str(row["run_id"]),
                "thread_sequence": int(row["thread_sequence"]),
                "created_at": str(row["created_at"]),
            }
            if row["kind"] == "message":
                items.append(
                    MessageHistoryItem(
                        kind="message",
                        role=cast(Any, row["role"]),
                        content=str(row["content"]),
                        attachments=tuple(
                            attachments_by_message.get(str(row["item_id"]), [])
                        ),
                        **common,
                    )
                )
            else:
                items.append(
                    ToolExecutionHistoryItem(
                        kind="tool",
                        tool_call_id=str(row["tool_call_id"]),
                        name=cast(str | None, row["name"]),
                        input=str(row["input"]),
                        result=cast(str | None, row["result"]),
                        status=cast(Any, row["tool_status"]),
                        **common,
                    )
                )

        next_before_sequence = (
            items[0].thread_sequence if has_more and items else None
        )
        return ConversationHistoryPage(
            thread_id=thread_id,
            thread_exists=True,
            items=tuple(items),
            has_more=has_more,
            next_before_sequence=next_before_sequence,
        )


@contextmanager
def open_sqlite_conversation_repository(
    database_path: str | Path,
) -> Iterator[SqliteConversationRepository]:
    """打开独立业务数据库，并在退出时可靠关闭连接。"""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield SqliteConversationRepository(connection)
    finally:
        connection.close()


@asynccontextmanager
async def open_async_sqlite_conversation_repository(
    database_path: str | Path,
) -> AsyncIterator[SqliteConversationRepository]:
    """在线程池中管理同步 SQLite 业务仓储，避免阻塞 ASGI 生命周期。"""
    manager = open_sqlite_conversation_repository(database_path)
    repository = await asyncio.to_thread(manager.__enter__)
    try:
        yield repository
    except BaseException as exc:
        suppressed = await asyncio.shield(
            asyncio.to_thread(
                manager.__exit__,
                type(exc),
                exc,
                exc.__traceback__,
            )
        )
        if not suppressed:
            raise
    else:
        await asyncio.shield(
            asyncio.to_thread(manager.__exit__, None, None, None)
        )
