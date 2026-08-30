"""定义 RunEvent 持久化查询端口和安全的复合身份查询用例。"""

from typing import Protocol

from mini_deer_agent.domain import RunRecord, StoredRunEventRecord


class RunEventSequenceError(RuntimeError):
    """表示 RunEvent sequence 重复、倒序或跳号，不能安全写入。"""


class RunEventStore(Protocol):
    """定义 Event Store 的只读应用端口；具体数据库不会泄露给 HTTP 层。"""

    def get_run(self, run_id: str) -> RunRecord | None:
        """读取 Run 事实，供查询入口执行 Thread 归属校验。"""

    def list_run_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        after_sequence: int,
        limit: int,
    ) -> tuple[StoredRunEventRecord, ...]:
        """按 sequence 正序返回游标之后的原始 RunEvent。"""


class RunEventHistoryService:
    """封装单 Run 原始事件查询，不把 Thread 归属规则放进 Router。"""

    def __init__(self, store: RunEventStore) -> None:
        """保存 Event Store 端口，允许以后替换 SQLite 实现。"""
        self._store = store

    def list_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        after_sequence: int,
        limit: int,
    ) -> tuple[StoredRunEventRecord, ...] | None:
        """查询路径 Thread 下的 RunEvent，归属不匹配时按不存在处理。"""
        run = self._store.get_run(run_id)
        if run is None or run.thread_id != thread_id:
            return None
        return self._store.list_run_events(
            thread_id,
            run_id,
            after_sequence=after_sequence,
            limit=limit,
        )
