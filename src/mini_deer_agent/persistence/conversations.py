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
from mini_deer_agent.application.workspaces import ThreadProjectConflictError
from mini_deer_agent.application.memory import (
    DuplicateMemoryFactError,
    MemoryFactNotFoundError,
)
from mini_deer_agent.application.run_events import RunEventSequenceError
from mini_deer_agent.domain import (
    ConversationHistoryPage,
    BenchmarkAttempt,
    BenchmarkScore,
    MessageHistoryItem,
    MAX_MEMORY_CONTENT_LENGTH,
    MAX_MEMORY_QUERY_LENGTH,
    MAX_MEMORY_SEARCH_LIMIT,
    MEMORY_CATEGORIES,
    MemoryCategory,
    MemoryFact,
    RunRecord,
    StoredRunEventRecord,
    Attachment,
    ThreadRecord,
    TimelineHistoryItem,
    ToolExecutionHistoryItem,
    default_thread_title,
)
from mini_deer_agent.streaming.events import RunEvent
from mini_deer_agent.persistence.workspaces import (
    PROJECT_SCHEMA_STATEMENTS,
    SqliteProjectRepository,
)


_LATEST_MIGRATION_VERSION = 16

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
                    'run_started', 'reasoning_delta', 'ai_delta',
                    'tool_call_delta', 'tool_result',
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
    6: (
        """
        ALTER TABLE messages ADD COLUMN hidden_from_ui INTEGER NOT NULL DEFAULT 0
        CHECK (hidden_from_ui IN (0, 1))
        """,
        """
        ALTER TABLE messages ADD COLUMN human_input_response_json TEXT
        """,
    ),
    7: (
        """
        CREATE TABLE IF NOT EXISTS memory_facts (
            fact_id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            content_key TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL CHECK (
                category IN (
                    'preference', 'correction', 'context', 'goal',
                    'behavior', 'identity', 'constraint', 'decision', 'other'
                )
            ),
            confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
            source TEXT NOT NULL DEFAULT 'manual' CHECK (source = 'manual'),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_memory_facts_recent
        ON memory_facts(updated_at DESC, fact_id DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_memory_facts_category_recent
        ON memory_facts(category, updated_at DESC, fact_id DESC)
        """,
    ),
    8: (
        # assistant 消息持久化思考过程，供历史恢复时折叠展示。
        """
        ALTER TABLE messages ADD COLUMN reasoning TEXT
        """,
        # run_events 的 event CHECK 需要加入 reasoning_delta；SQLite 无法修改
        # 已有 CHECK 约束，只能重建表。先建新表并复制数据，再原子替换。
        """
        CREATE TABLE run_events_v8 (
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence >= 1),
            version TEXT NOT NULL,
            event TEXT NOT NULL CHECK (
                event IN (
                    'run_started', 'reasoning_delta', 'ai_delta',
                    'tool_call_delta', 'tool_result',
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
        INSERT INTO run_events_v8 (
            run_id, thread_id, sequence, version, event,
            message_id, payload_json, created_at
        )
        SELECT
            run_id, thread_id, sequence, version, event,
            message_id, payload_json, created_at
        FROM run_events
        """,
        """
        DROP TABLE run_events
        """,
        """
        ALTER TABLE run_events_v8 RENAME TO run_events
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_run_events_thread_run_sequence
        ON run_events(thread_id, run_id, sequence)
        """,
    ),
    9: PROJECT_SCHEMA_STATEMENTS,
    10: (
        # 不设 projects 外键：解除登记不能级联清空历史 Thread 的原项目身份。
        "ALTER TABLE threads ADD COLUMN project_id TEXT",
        """
        CREATE INDEX idx_threads_project_recent
        ON threads(project_id, updated_at DESC, thread_id DESC)
        """,
    ),
    11: (
        "DROP INDEX idx_projects_created",
        "ALTER TABLE projects RENAME TO projects_v10",
        PROJECT_SCHEMA_STATEMENTS[0],
        """
        INSERT INTO projects (
            project_id, name, root_path, root_key, root_identity, access_mode,
            status, status_reason, created_at, updated_at
        )
        SELECT
            project_id, name, root_path, root_key, root_identity, 'read_write',
            status, status_reason, created_at, updated_at
        FROM projects_v10
        """,
        "DROP TABLE projects_v10",
        PROJECT_SCHEMA_STATEMENTS[1],
    ),
    12: (
        "ALTER TABLE runs ADD COLUMN benchmark_case_id TEXT",
        "ALTER TABLE runs ADD COLUMN benchmark_task_completed INTEGER CHECK (benchmark_task_completed IN (0, 1))",
        "ALTER TABLE runs ADD COLUMN benchmark_score INTEGER CHECK (benchmark_score BETWEEN 1 AND 5)",
        "ALTER TABLE runs ADD COLUMN benchmark_notes TEXT",
        "ALTER TABLE runs ADD COLUMN benchmark_scored_at TEXT",
        """
        CREATE INDEX idx_runs_benchmark_recent
        ON runs(benchmark_case_id, created_at DESC)
        WHERE benchmark_case_id IS NOT NULL
        """,
    ),
    13: (
        "ALTER TABLE runs ADD COLUMN input_tokens INTEGER CHECK (input_tokens >= 0)",
        "ALTER TABLE runs ADD COLUMN output_tokens INTEGER CHECK (output_tokens >= 0)",
        "ALTER TABLE runs ADD COLUMN total_tokens INTEGER CHECK (total_tokens >= 0)",
        "ALTER TABLE runs ADD COLUMN model_calls INTEGER CHECK (model_calls >= 0)",
    ),
    14: (
        # Goal 评估阶段需要作为 Run 流的一部分可靠重放；SQLite 的 CHECK
        # 不能原地扩展，因此与 v8 一样重建事件表并保留既有数据。
        """
        CREATE TABLE run_events_v14 (
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence >= 1),
            version TEXT NOT NULL,
            event TEXT NOT NULL CHECK (
                event IN (
                    'run_started', 'reasoning_delta', 'ai_delta',
                    'tool_call_delta', 'tool_result', 'goal_status',
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
        INSERT INTO run_events_v14 (
            run_id, thread_id, sequence, version, event,
            message_id, payload_json, created_at
        )
        SELECT
            run_id, thread_id, sequence, version, event,
            message_id, payload_json, created_at
        FROM run_events
        """,
        "DROP TABLE run_events",
        "ALTER TABLE run_events_v14 RENAME TO run_events",
        """
        CREATE INDEX IF NOT EXISTS idx_run_events_thread_run_sequence
        ON run_events(thread_id, run_id, sequence)
        """,
    ),
    15: (
        """
        CREATE TABLE IF NOT EXISTS goal_context_snapshots (
            thread_id TEXT PRIMARY KEY REFERENCES threads(thread_id) ON DELETE CASCADE,
            goal_revision TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
    ),
    16: (
        "ALTER TABLE runs ADD COLUMN model_profile TEXT",
        "ALTER TABLE runs ADD COLUMN model_profile_revision TEXT",
        "ALTER TABLE runs ADD COLUMN model_selection_revision INTEGER CHECK (model_selection_revision >= 0)",
        "ALTER TABLE runs ADD COLUMN skill_catalog_hash TEXT",
    ),
}


def _event_counter(payload: dict[str, Any], field: str) -> int | None:
    """只接受非负整数；旧事件保持未知，以便基准回退到事件推导。"""
    value = payload.get(field)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _utc_now() -> str:
    """返回可按字符串比较的 UTC ISO 时间。"""
    return datetime.now(UTC).isoformat()


def _normalize_memory_content(value: str) -> tuple[str, str]:
    """返回可展示正文和用于并发安全去重、字面查询的 casefold key。"""
    normalized = value.strip()
    if not normalized:
        raise ValueError("memory content must not be empty")
    if len(normalized) > MAX_MEMORY_CONTENT_LENGTH:
        raise ValueError(
            f"memory content must not exceed {MAX_MEMORY_CONTENT_LENGTH} characters"
        )
    return normalized, normalized.casefold()


def _normalize_memory_category(value: str) -> MemoryCategory:
    """校验稳定分类，避免任意标签悄悄扩张存储契约。"""
    normalized = value.strip().casefold()
    if normalized not in MEMORY_CATEGORIES:
        raise ValueError(
            "memory category must be one of: " + ", ".join(MEMORY_CATEGORIES)
        )
    return cast(MemoryCategory, normalized)


def _normalize_memory_confidence(value: float) -> float:
    """拒绝 bool、NaN、无穷及区间外的置信度。"""
    normalized = float(value)
    if isinstance(value, bool) or not 0 <= normalized <= 1:
        raise ValueError("memory confidence must be a number between 0 and 1")
    return normalized


def _memory_fact_from_row(row: sqlite3.Row) -> MemoryFact:
    """把内部 SQLite 行映射为不可变领域对象。"""
    return MemoryFact(
        fact_id=str(row["fact_id"]),
        content=str(row["content"]),
        category=cast(MemoryCategory, row["category"]),
        confidence=float(row["confidence"]),
        source="manual",
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class SqliteConversationRepository:
    """以同一事务保存产品投影和原始 RunEvent，读取端口仍保持逻辑分离。"""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """保存长生命周期连接并初始化版本化 schema。"""
        self._connection = connection
        self._lock = RLock()
        self._setup()
        # 独立项目子仓储复用同一连接与锁，不另外启动迁移或恢复活动 Run。
        self.projects = SqliteProjectRepository(connection, self._lock)

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
            abandoned_runs = self._connection.execute(
                """
                SELECT runs.run_id, runs.thread_id,
                       COALESCE(MAX(run_events.sequence), 0)
                FROM runs
                LEFT JOIN run_events ON run_events.run_id = runs.run_id
                WHERE runs.status IN ('pending', 'running')
                GROUP BY runs.run_id, runs.thread_id
                """
            ).fetchall()
            for run_id, thread_id, last_sequence in abandoned_runs:
                self._connection.execute(
                    """
                    INSERT INTO run_events(
                        run_id, thread_id, sequence, version, event,
                        message_id, payload_json, created_at
                    ) VALUES (?, ?, ?, '1', 'run_interrupted', NULL, ?, ?)
                    """,
                    (
                        str(run_id),
                        str(thread_id),
                        int(last_sequence) + 1,
                        '{"reason":"server_restarted"}',
                        recovered_at,
                    ),
                )
            self._connection.execute(
                """
                UPDATE runs
                SET status = 'interrupted', updated_at = ?, finished_at = ?,
                    finish_reason = 'server_restarted', error_code = 'server_restarted'
                WHERE status IN ('pending', 'running')
                """,
                (recovered_at, recovered_at),
            )
            missing_terminal_events = self._connection.execute(
                """
                SELECT runs.run_id, runs.thread_id, runs.status,
                       runs.finish_reason, runs.error_code,
                       runs.input_tokens, runs.output_tokens,
                       runs.total_tokens, runs.model_calls,
                       COALESCE(MAX(run_events.sequence), 0)
                FROM runs
                LEFT JOIN run_events ON run_events.run_id = runs.run_id
                WHERE runs.status IN ('completed', 'failed', 'interrupted')
                  AND NOT EXISTS (
                      SELECT 1 FROM run_events AS terminal
                      WHERE terminal.run_id = runs.run_id
                        AND terminal.event IN (
                            'run_completed', 'run_error', 'run_interrupted'
                        )
                  )
                GROUP BY runs.run_id, runs.thread_id, runs.status,
                         runs.finish_reason, runs.error_code,
                         runs.input_tokens, runs.output_tokens,
                         runs.total_tokens, runs.model_calls
                """
            ).fetchall()
            for row in missing_terminal_events:
                (
                    run_id,
                    thread_id,
                    run_status,
                    finish_reason,
                    error_code,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    model_calls,
                    last_sequence,
                ) = row
                if run_status == "completed":
                    event_name = "run_completed"
                    payload = {
                        "finish_reason": finish_reason or "stop",
                        "input_tokens": int(input_tokens or 0),
                        "output_tokens": int(output_tokens or 0),
                        "total_tokens": int(total_tokens or 0),
                        "model_calls": int(model_calls or 0),
                    }
                elif run_status == "failed":
                    event_name = "run_error"
                    payload = {
                        "code": error_code or "run_failed",
                        "message": "Agent execution failed",
                        "retryable": True,
                    }
                else:
                    event_name = "run_interrupted"
                    payload = {
                        "reason": finish_reason or error_code or "interrupted"
                    }
                self._connection.execute(
                    """
                    INSERT INTO run_events(
                        run_id, thread_id, sequence, version, event,
                        message_id, payload_json, created_at
                    ) VALUES (?, ?, ?, '1', ?, NULL, ?, ?)
                    """,
                    (
                        str(run_id),
                        str(thread_id),
                        int(last_sequence) + 1,
                        event_name,
                        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        recovered_at,
                    ),
                )
            self._connection.execute(
                """
                UPDATE tool_executions
                SET status = 'cancelled'
                WHERE status = 'pending'
                  AND run_id IN (
                      SELECT run_id FROM runs WHERE status = 'interrupted'
                  )
                """
            )
            self._connection.execute(
                """
                UPDATE tool_executions
                SET status = 'failed'
                WHERE status = 'pending'
                  AND run_id IN (
                      SELECT run_id FROM runs WHERE status IN ('completed', 'failed')
                  )
                """
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

    def search_memory_facts(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 10,
    ) -> tuple[MemoryFact, ...]:
        """按规范化字面包含查询全局事实，空查询稳定返回最近记录。"""
        normalized_query = query.strip()
        if len(normalized_query) > MAX_MEMORY_QUERY_LENGTH:
            raise ValueError(
                f"memory query must not exceed {MAX_MEMORY_QUERY_LENGTH} characters"
            )
        if isinstance(limit, bool) or not 1 <= limit <= MAX_MEMORY_SEARCH_LIMIT:
            raise ValueError(
                f"memory search limit must be between 1 and {MAX_MEMORY_SEARCH_LIMIT}"
            )
        normalized_category = (
            _normalize_memory_category(category)
            if category is not None
            else None
        )
        conditions: list[str] = []
        parameters: list[object] = []
        if normalized_query:
            # instr 不把 %, _ 当通配符；content_key 已 casefold，查询语义稳定且字面化。
            conditions.append("instr(content_key, ?) > 0")
            parameters.append(normalized_query.casefold())
        if normalized_category is not None:
            conditions.append("category = ?")
            parameters.append(normalized_category)
        where_clause = (
            "WHERE " + " AND ".join(conditions) if conditions else ""
        )
        parameters.append(limit)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT fact_id, content, category, confidence, source,
                       created_at, updated_at
                FROM memory_facts
                {where_clause}
                ORDER BY updated_at DESC, fact_id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return tuple(_memory_fact_from_row(row) for row in rows)

    def create_memory_fact(
        self,
        content: str,
        *,
        category: str = "context",
        confidence: float = 1.0,
    ) -> MemoryFact:
        """原子创建单用户全局事实，由唯一 key 阻止并发重复写入。"""
        normalized_content, content_key = _normalize_memory_content(content)
        normalized_category = _normalize_memory_category(category)
        normalized_confidence = _normalize_memory_confidence(confidence)
        fact_id = f"fact_{uuid4().hex}"
        now = _utc_now()
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """
                    INSERT INTO memory_facts(
                        fact_id, content, content_key, category, confidence,
                        source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'manual', ?, ?)
                    """,
                    (
                        fact_id,
                        normalized_content,
                        content_key,
                        normalized_category,
                        normalized_confidence,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "memory_facts.content_key" in str(exc):
                raise DuplicateMemoryFactError("Duplicate fact") from exc
            raise
        return MemoryFact(
            fact_id=fact_id,
            content=normalized_content,
            category=normalized_category,
            confidence=normalized_confidence,
            source="manual",
            created_at=now,
            updated_at=now,
        )

    def update_memory_fact(
        self,
        fact_id: str,
        *,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
    ) -> MemoryFact:
        """在一个事务内读取并局部更新事实，保留创建时间与未提供字段。"""
        if content is None and category is None and confidence is None:
            raise ValueError("memory update requires at least one changed field")
        normalized_content: str | None = None
        content_key: str | None = None
        if content is not None:
            normalized_content, content_key = _normalize_memory_content(content)
        normalized_category = (
            _normalize_memory_category(category)
            if category is not None
            else None
        )
        normalized_confidence = (
            _normalize_memory_confidence(confidence)
            if confidence is not None
            else None
        )
        try:
            with self._lock, self._connection:
                existing = self._connection.execute(
                    """
                    SELECT fact_id, content, content_key, category, confidence,
                           source, created_at, updated_at
                    FROM memory_facts
                    WHERE fact_id = ?
                    """,
                    (fact_id,),
                ).fetchone()
                if existing is None:
                    raise MemoryFactNotFoundError(fact_id)
                updated_at = _utc_now()
                self._connection.execute(
                    """
                    UPDATE memory_facts
                    SET content = ?, content_key = ?, category = ?,
                        confidence = ?, updated_at = ?
                    WHERE fact_id = ?
                    """,
                    (
                        normalized_content
                        if normalized_content is not None
                        else existing["content"],
                        content_key
                        if content_key is not None
                        else existing["content_key"],
                        normalized_category
                        if normalized_category is not None
                        else existing["category"],
                        normalized_confidence
                        if normalized_confidence is not None
                        else existing["confidence"],
                        updated_at,
                        fact_id,
                    ),
                )
                row = self._connection.execute(
                    """
                    SELECT fact_id, content, category, confidence, source,
                           created_at, updated_at
                    FROM memory_facts
                    WHERE fact_id = ?
                    """,
                    (fact_id,),
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            if "memory_facts.content_key" in str(exc):
                raise DuplicateMemoryFactError("Duplicate fact") from exc
            raise
        if row is None:  # pragma: no cover - 同一事务内的防御性不变量
            raise MemoryFactNotFoundError(fact_id)
        return _memory_fact_from_row(row)

    def delete_memory_fact(self, fact_id: str) -> None:
        """物理删除明确指定的全局事实；不存在时不伪装成功。"""
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM memory_facts WHERE fact_id = ?",
                (fact_id,),
            )
            if cursor.rowcount != 1:
                raise MemoryFactNotFoundError(fact_id)

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
        attachments: tuple[Attachment, ...] = (),
        human_input_response: dict[str, object] | None = None,
        benchmark_case_id: str | None = None,
        hidden_from_ui: bool = False,
    ) -> None:
        """原子写入 Run、用户消息、附件和澄清元数据，拒绝并发活动 Run。"""
        now = _utc_now()
        title = default_thread_title(user_message)
        try:
            with self._lock, self._connection:
                cursor = self._connection.cursor()
                cursor.execute(
                    """
                    INSERT INTO threads(thread_id, title, status, next_sequence, created_at, updated_at)
                    VALUES (?, ?, 'busy', 1, ?, ?)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        status = 'busy',
                        title = COALESCE(threads.title, excluded.title),
                        updated_at = excluded.updated_at
                    """,
                    (thread_id, title, now, now),
                )
                cursor.execute(
                    """
                    INSERT INTO runs(
                        run_id, thread_id, user_message_id, status, created_at,
                        updated_at, benchmark_case_id
                    ) VALUES (?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (run_id, thread_id, user_message_id, now, now, benchmark_case_id),
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
                response_json = (
                    json.dumps(
                        human_input_response,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    if human_input_response is not None
                    else None
                )
                cursor.execute(
                    """
                    INSERT INTO messages(
                        item_id, role, content, hidden_from_ui,
                        human_input_response_json
                    ) VALUES (?, 'user', ?, ?, ?)
                    """,
                    (
                        user_message_id,
                        user_message,
                        1
                        if hidden_from_ui or human_input_response is not None
                        else 0,
                        response_json,
                    ),
                )
                # 沿用旧表名以兼容已有数据库；media_type 区分正文和标准图片 data URL。
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

    @staticmethod
    def _benchmark_attempt_from_row(row: sqlite3.Row) -> BenchmarkAttempt:
        """把带基准字段的 Run 行映射为稳定领域记录。"""
        return BenchmarkAttempt(
            case_id=str(row["benchmark_case_id"]),
            run_id=str(row["run_id"]),
            thread_id=str(row["thread_id"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            started_at=cast(str | None, row["started_at"]),
            finished_at=cast(str | None, row["finished_at"]),
            finish_reason=cast(str | None, row["finish_reason"]),
            error_code=cast(str | None, row["error_code"]),
            input_tokens=cast(int | None, row["input_tokens"]),
            output_tokens=cast(int | None, row["output_tokens"]),
            total_tokens=cast(int | None, row["total_tokens"]),
            model_calls=cast(int | None, row["model_calls"]),
            task_completed=(
                None
                if row["benchmark_task_completed"] is None
                else bool(row["benchmark_task_completed"])
            ),
            score=cast(int | None, row["benchmark_score"]),
            notes=cast(str | None, row["benchmark_notes"]),
            scored_at=cast(str | None, row["benchmark_scored_at"]),
        )

    def list_benchmark_attempts(self, *, limit: int) -> tuple[BenchmarkAttempt, ...]:
        """按创建时间倒序列出固定案例 Run。"""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT run_id, thread_id, status, created_at, started_at,
                       finished_at, finish_reason, error_code, input_tokens,
                       output_tokens, total_tokens, model_calls, benchmark_case_id,
                       benchmark_task_completed, benchmark_score, benchmark_notes,
                       benchmark_scored_at
                FROM runs
                WHERE benchmark_case_id IS NOT NULL
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(self._benchmark_attempt_from_row(row) for row in rows)

    def get_benchmark_attempt(self, run_id: str) -> BenchmarkAttempt | None:
        """按 Run ID 读取基准关联；普通 Run 返回 None。"""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT run_id, thread_id, status, created_at, started_at,
                       finished_at, finish_reason, error_code, input_tokens,
                       output_tokens, total_tokens, model_calls, benchmark_case_id,
                       benchmark_task_completed, benchmark_score, benchmark_notes,
                       benchmark_scored_at
                FROM runs
                WHERE run_id = ? AND benchmark_case_id IS NOT NULL
                """,
                (run_id,),
            ).fetchone()
        return None if row is None else self._benchmark_attempt_from_row(row)

    def update_benchmark_score(
        self,
        run_id: str,
        *,
        task_completed: bool,
        score: int,
        notes: str | None,
    ) -> BenchmarkScore | None:
        """只允许为已关联固定案例的 Run 写入人工评分。"""
        scored_at = _utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE runs
                SET benchmark_task_completed = ?, benchmark_score = ?,
                    benchmark_notes = ?, benchmark_scored_at = ?
                WHERE run_id = ? AND benchmark_case_id IS NOT NULL
                """,
                (1 if task_completed else 0, score, notes, scored_at, run_id),
            )
        if cursor.rowcount != 1:
            return None
        return BenchmarkScore(
            task_completed=task_completed,
            score=score,
            notes=notes,
            scored_at=scored_at,
        )

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
                model_profile = event.payload.get("model_profile")
                model_profile_revision = event.payload.get("model_profile_revision")
                model_selection_revision = event.payload.get("model_selection_revision")
                skill_catalog_hash = event.payload.get("skill_catalog_hash")
                cursor.execute(
                    """
                    UPDATE runs
                    SET status = 'running', started_at = COALESCE(started_at, ?),
                        updated_at = ?, model_profile = ?, model_profile_revision = ?,
                        model_selection_revision = ?, skill_catalog_hash = ?
                    WHERE run_id = ?
                    """,
                    (
                        started_at,
                        now,
                        model_profile if isinstance(model_profile, str) else None,
                        (
                            model_profile_revision
                            if isinstance(model_profile_revision, str)
                            else None
                        ),
                        (
                            model_selection_revision
                            if isinstance(model_selection_revision, int)
                            and not isinstance(model_selection_revision, bool)
                            and model_selection_revision >= 0
                            else None
                        ),
                        skill_catalog_hash if isinstance(skill_catalog_hash, str) else None,
                        event.run_id,
                    ),
                )
                return True

            if event.event == "reasoning_delta":
                # 思考过程与最终回答共享同一 assistant 消息；先到先建消息，
                # 后续 ai_delta 继续追加 content。
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
                        """
                        INSERT INTO messages(item_id, role, content, reasoning)
                        VALUES (?, 'assistant', '', ?)
                        """,
                        (item_id, text),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE messages
                        SET reasoning = COALESCE(reasoning, '') || ?
                        WHERE item_id = ?
                        """,
                        (text, item_id),
                    )
                cursor.execute(
                    "UPDATE timeline_items SET updated_at = ? WHERE item_id = ?",
                    (now, item_id),
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
                result_meta = event.payload.get("result_meta")
                result_status = (
                    str(result_meta.get("status"))
                    if isinstance(result_meta, dict)
                    else "success"
                )
                execution_status = (
                    "failed"
                    if result_status in {"retryable_error", "terminal_error"}
                    else "completed"
                )
                if created:
                    cursor.execute(
                        """
                        INSERT INTO tool_executions(
                            item_id, run_id, tool_call_id, name, input, result, status
                        ) VALUES (?, ?, ?, ?, '', ?, ?)
                        """,
                        (
                            item_id,
                            event.run_id,
                            tool_call_id,
                            name,
                            result,
                            execution_status,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE tool_executions
                        SET name = COALESCE(name, ?), result = ?, status = ?
                        WHERE item_id = ?
                        """,
                        (name, result, execution_status, item_id),
                    )
                cursor.execute(
                    "UPDATE timeline_items SET updated_at = ? WHERE item_id = ?",
                    (now, item_id),
                )
                return True

            if event.event == "goal_status":
                # 控制面事件只参与可靠重放，不投影成对话时间线或 Run 终态。
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
                    UPDATE runs SET
                        status = 'completed', updated_at = ?, finished_at = ?,
                        finish_reason = ?, input_tokens = ?, output_tokens = ?,
                        total_tokens = ?, model_calls = ?
                    WHERE run_id = ?
                    """,
                    (
                        now,
                        now,
                        str(event.payload.get("finish_reason") or "stop"),
                        _event_counter(event.payload, "input_tokens"),
                        _event_counter(event.payload, "output_tokens"),
                        _event_counter(event.payload, "total_tokens"),
                        _event_counter(event.payload, "model_calls"),
                        event.run_id,
                    ),
                )
                cursor.execute(
                    "UPDATE tool_executions SET status = 'failed' WHERE run_id = ? AND status = 'pending'",
                    (event.run_id,),
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
                SET status = 'interrupted', updated_at = ?, finished_at = ?,
                    finish_reason = ?, error_code = ?
                WHERE run_id = ? AND thread_id = ? AND status IN ('pending', 'running')
                """,
                (now, now, error_code, error_code, run_id, thread_id),
            )
            if updated.rowcount == 0:
                return
            last_sequence = int(
                self._connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM run_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            self._connection.execute(
                """
                INSERT INTO run_events(
                    run_id, thread_id, sequence, version, event,
                    message_id, payload_json, created_at
                ) VALUES (?, ?, ?, '1', 'run_interrupted', NULL, ?, ?)
                """,
                (
                    run_id,
                    thread_id,
                    last_sequence + 1,
                    json.dumps(
                        {"reason": error_code},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    now,
                ),
            )
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
                       started_at, finished_at, finish_reason, error_code,
                       input_tokens, output_tokens, total_tokens, model_calls,
                       model_profile, model_profile_revision,
                       model_selection_revision, skill_catalog_hash
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
            input_tokens=cast(int | None, row["input_tokens"]),
            output_tokens=cast(int | None, row["output_tokens"]),
            total_tokens=cast(int | None, row["total_tokens"]),
            model_calls=cast(int | None, row["model_calls"]),
            model_profile=cast(str | None, row["model_profile"]),
            model_profile_revision=cast(str | None, row["model_profile_revision"]),
            model_selection_revision=cast(int | None, row["model_selection_revision"]),
            skill_catalog_hash=cast(str | None, row["skill_catalog_hash"]),
        )

    def create_project_thread(
        self, *, thread_id: str, project_id: str
    ) -> ThreadRecord:
        """原子创建项目 Thread；同 ID 只能保持原归属，不能绑定或重绑。"""
        now = _utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO threads(
                    thread_id, title, status, next_sequence,
                    created_at, updated_at, project_id
                ) VALUES (?, NULL, 'idle', 1, ?, ?, ?)
                ON CONFLICT(thread_id) DO NOTHING
                """,
                (thread_id, now, now, project_id),
            )
            row = self._connection.execute(
                """
                SELECT thread_id, title, status, created_at, updated_at, project_id
                FROM threads WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("Thread insert did not produce a readable record")
            if row["project_id"] != project_id:
                raise ThreadProjectConflictError(
                    f"Thread {thread_id} already belongs to another context"
                )
        return self._thread_from_row(row)

    def ensure_thread(self, *, thread_id: str) -> ThreadRecord:
        """幂等创建普通 Thread；已有项目归属和标题均保持不变。"""
        now = _utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO threads(
                    thread_id, title, status, next_sequence,
                    created_at, updated_at, project_id
                ) VALUES (?, '新对话', 'idle', 1, ?, ?, NULL)
                ON CONFLICT(thread_id) DO NOTHING
                """,
                (thread_id, now, now),
            )
            row = self._connection.execute(
                """
                SELECT thread_id, title, status, created_at, updated_at, project_id
                FROM threads WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
        if row is None:  # pragma: no cover - 同一事务内的防御性不变量
            raise RuntimeError("Thread insert did not produce a readable record")
        return self._thread_from_row(row)

    def touch_thread(self, thread_id: str) -> ThreadRecord | None:
        """记录 Goal 控制操作的活动时间，不改变 Thread 运行状态。"""
        now = _utc_now()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE threads SET updated_at = ? WHERE thread_id = ?",
                (now, thread_id),
            )
        if cursor.rowcount == 0:
            return None
        return self.get_thread(thread_id)

    def list_project_threads(
        self, project_id: str, *, limit: int, offset: int = 0
    ) -> tuple[ThreadRecord, ...]:
        """使用 Project 最近活动索引返回严格归属的 Thread。"""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT thread_id, title, status, created_at, updated_at, project_id
                FROM threads
                WHERE project_id = ?
                ORDER BY updated_at DESC, thread_id DESC
                LIMIT ? OFFSET ?
                """,
                (project_id, limit, offset),
            ).fetchall()
        return tuple(self._thread_from_row(row) for row in rows)

    @staticmethod
    def _thread_from_row(row: sqlite3.Row) -> ThreadRecord:
        """集中映射 Thread 字段，防止全局列表与项目列表遗漏归属。"""
        return ThreadRecord(
            thread_id=str(row["thread_id"]),
            title=cast(str | None, row["title"]),
            status=cast(Any, row["status"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            project_id=cast(str | None, row["project_id"]),
        )

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """按主键查询 Thread 元数据。"""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT thread_id, title, status, created_at, updated_at, project_id
                FROM threads WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return self._thread_from_row(row)

    def save_goal_context_snapshot(
        self,
        *,
        thread_id: str,
        goal_revision: str,
        snapshot_json: str,
    ) -> None:
        """按 Thread 幂等保存 Goal 快照；新 revision 会完整替换旧上下文。"""
        now = _utc_now()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO goal_context_snapshots(
                    thread_id, goal_revision, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    goal_revision = excluded.goal_revision,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at
                """,
                (thread_id, goal_revision, snapshot_json, now, now),
            )

    def get_goal_context_snapshot(self, thread_id: str) -> tuple[str, str] | None:
        """读取跨进程恢复所需的 Goal revision 与序列化快照。"""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT goal_revision, snapshot_json
                FROM goal_context_snapshots
                WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["goal_revision"]), str(row["snapshot_json"])

    def delete_goal_context_snapshot(self, thread_id: str) -> None:
        """释放 Goal 生命周期结束后的冻结上下文。"""
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM goal_context_snapshots WHERE thread_id = ?",
                (thread_id,),
            )

    def list_threads(
        self, *, limit: int, offset: int = 0, standalone_only: bool = False
    ) -> tuple[ThreadRecord, ...]:
        """使用最近活动索引稳定倒序查询产品 Thread。"""
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT thread_id, title, status, created_at, updated_at, project_id
                FROM threads
                {"WHERE project_id IS NULL" if standalone_only else ""}
                ORDER BY updated_at DESC, thread_id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return tuple(
            self._thread_from_row(row)
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
                       started_at, finished_at, finish_reason, error_code,
                       input_tokens, output_tokens, total_tokens, model_calls,
                       model_profile, model_profile_revision,
                       model_selection_revision, skill_catalog_hash
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
                input_tokens=cast(int | None, row["input_tokens"]),
                output_tokens=cast(int | None, row["output_tokens"]),
                total_tokens=cast(int | None, row["total_tokens"]),
                model_calls=cast(int | None, row["model_calls"]),
                model_profile=cast(str | None, row["model_profile"]),
                model_profile_revision=cast(str | None, row["model_profile_revision"]),
                model_selection_revision=cast(int | None, row["model_selection_revision"]),
                skill_catalog_hash=cast(str | None, row["skill_catalog_hash"]),
            )
            for row in rows
        )

    def get_attachment(self, message_id: str, position: int) -> Attachment | None:
        """只查询可见用户消息中的附件，不依赖分页或最近历史窗口。"""
        with self._lock:
            row = self._connection.execute(
                """
                SELECT a.filename, a.media_type, a.size_bytes, a.content
                FROM text_attachments AS a
                JOIN messages AS m ON m.item_id = a.message_id
                WHERE a.message_id = ? AND a.position = ?
                  AND m.role = 'user' AND m.hidden_from_ui = 0
                """,
                (message_id, position),
            ).fetchone()
        if row is None:
            return None
        return Attachment(
            filename=str(row["filename"]), media_type=str(row["media_type"]),
            size_bytes=int(row["size_bytes"]), content=str(row["content"]),
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
                       messages.reasoning,
                       messages.hidden_from_ui,
                       messages.human_input_response_json,
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
        attachments_by_message: dict[str, list[Attachment]] = {}
        if message_ids:
            placeholders = ",".join("?" for _ in message_ids)
            with self._lock:
                attachment_rows = self._connection.execute(
                    f"""
                    SELECT message_id, filename, media_type, size_bytes, content
                    FROM text_attachments
                    WHERE message_id IN ({placeholders})
                    ORDER BY message_id, position
                    """,
                    message_ids,
                ).fetchall()
            for attachment_row in attachment_rows:
                message_id = str(attachment_row["message_id"])
                attachments_by_message.setdefault(message_id, []).append(
                    Attachment(
                        filename=str(attachment_row["filename"]),
                        media_type=str(attachment_row["media_type"]),
                        size_bytes=int(attachment_row["size_bytes"]),
                        content=str(attachment_row["content"]),
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
                response_json = cast(str | None, row["human_input_response_json"])
                response = json.loads(response_json) if response_json is not None else None
                if response is not None and not isinstance(response, dict):
                    raise RuntimeError(
                        "Stored human input response must be a JSON object"
                    )
                items.append(
                    MessageHistoryItem(
                        kind="message",
                        role=cast(Any, row["role"]),
                        content=str(row["content"]),
                        reasoning=cast(str | None, row["reasoning"]),
                        attachments=tuple(
                            attachments_by_message.get(str(row["item_id"]), [])
                        ),
                        hidden_from_ui=bool(row["hidden_from_ui"]),
                        human_input_response=cast(dict[str, Any] | None, response),
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
