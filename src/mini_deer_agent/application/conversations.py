"""定义对话持久化端口和可由多个入口复用的历史查询用例。"""

from typing import Protocol

from mini_deer_agent.domain import (
    ConversationHistoryPage,
    MAX_THREAD_TITLE_LENGTH,
    RunRecord,
    TextAttachment,
    ThreadRecord,
    normalize_thread_title,
)
from mini_deer_agent.streaming.events import RunEvent
from mini_deer_agent.application.memory import MemoryStore


class ActiveRunConflictError(RuntimeError):
    """表示同一 Thread 已有会修改上下文的活动 Run。"""


class ActiveThreadDeleteConflictError(RuntimeError):
    """表示活动 Run 仍在使用 Thread，当前不能删除。"""


class ThreadCheckpointStore(Protocol):
    """定义删除 Thread 模型上下文所需的最小 Checkpointer 端口。"""

    async def adelete_thread(self, thread_id: str) -> None:
        """删除一个 Thread 的全部 LangGraph checkpoint。"""


class ConversationRepository(MemoryStore, Protocol):
    """定义运行写入和历史查询共同依赖的产品数据仓储契约。"""

    def create_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        user_message_id: str,
        user_message: str,
        attachments: tuple[TextAttachment, ...] = (),
        human_input_response: dict[str, object] | None = None,
    ) -> None:
        """原子创建 Thread、Run、本轮用户消息、附件与澄清响应。"""

    def create_project_thread(
        self, *, thread_id: str, project_id: str
    ) -> ThreadRecord:
        """创建空闲项目 Thread，已有 Thread 只能按原 Project 幂等读取。"""

    def list_project_threads(
        self, project_id: str, *, limit: int
    ) -> tuple[ThreadRecord, ...]:
        """只返回归属于指定 Project 的最近 Thread。"""

    def apply_run_event(self, event: RunEvent) -> bool:
        """物化 RunEvent；返回 False 表示终态竞争使事件不再可写。"""

    def interrupt_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        error_code: str,
    ) -> None:
        """收束没有产生终止事件的 Run，并释放 Thread 活动锁。"""

    def get_run(self, run_id: str) -> RunRecord | None:
        """按 Run ID 查询持久化状态。"""

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """返回 Thread 元数据；不存在时返回 None。"""

    def list_threads(self, *, limit: int) -> tuple[ThreadRecord, ...]:
        """按最近活动时间稳定倒序返回产品 Thread。"""

    def update_thread_title(
        self,
        thread_id: str,
        title: str,
    ) -> ThreadRecord | None:
        """更新一个已存在 Thread 的业务标题。"""

    def delete_thread(self, thread_id: str) -> bool:
        """删除空闲 Thread 及其业务历史；不存在时返回 False。"""

    def list_runs(self, thread_id: str, *, limit: int) -> tuple[RunRecord, ...]:
        """按创建时间倒序返回 Thread 的 Run。"""

    def list_history(
        self,
        thread_id: str,
        *,
        limit: int,
        before_sequence: int | None,
    ) -> ConversationHistoryPage:
        """返回一页按时间正序排列的可见历史。"""


class ConversationHistoryService:
    """封装 Thread、Run、标题与消息历史应用用例。"""

    def __init__(self, repository: ConversationRepository) -> None:
        """保存仓储端口，不让 HTTP Router 感知具体数据库。"""
        self._repository = repository

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """查询单个 Thread。"""
        return self._repository.get_thread(thread_id)

    def list_threads(self, *, limit: int = 20) -> tuple[ThreadRecord, ...]:
        """查询最近活动的产品 Thread。"""
        return self._repository.list_threads(limit=limit)

    def update_thread_title(
        self,
        thread_id: str,
        title: str,
    ) -> ThreadRecord | None:
        """校验并更新标题，使非 HTTP 入口也遵守同一业务规则。"""
        normalized = normalize_thread_title(title)
        if not normalized or len(normalized) > MAX_THREAD_TITLE_LENGTH:
            raise ValueError("Thread title must contain 1 to 60 characters")
        return self._repository.update_thread_title(thread_id, normalized)

    def list_runs(self, thread_id: str, *, limit: int = 100) -> tuple[RunRecord, ...]:
        """查询 Thread 的最近 Run。"""
        return self._repository.list_runs(thread_id, limit=limit)

    def get_run(self, thread_id: str, run_id: str) -> RunRecord | None:
        """查询路径 Thread 下的单个 Run，归属不匹配时按不存在处理。"""
        record = self._repository.get_run(run_id)
        if record is None or record.thread_id != thread_id:
            return None
        return record

    def list_history(
        self,
        thread_id: str,
        *,
        limit: int,
        before_sequence: int | None,
    ) -> ConversationHistoryPage:
        """查询 Thread 的稳定可见时间线。"""
        return self._repository.list_history(
            thread_id,
            limit=limit,
            before_sequence=before_sequence,
        )


class ThreadLifecycleService:
    """编排业务历史与 LangGraph checkpoint 的 Thread 生命周期。"""

    def __init__(
        self,
        repository: ConversationRepository,
        checkpoint_store: ThreadCheckpointStore,
    ) -> None:
        """保存两个持久化端口，避免 Router 感知双 SQLite。"""
        self._repository = repository
        self._checkpoint_store = checkpoint_store

    async def delete_thread(self, thread_id: str) -> bool:
        """删除空闲 Thread 的模型上下文与完整业务投影。"""
        record = self._repository.get_thread(thread_id)
        if record is None:
            return False
        if record.status == "busy":
            # 必须在触碰任一数据库前拒绝，避免活动 Run 只剩一半状态。
            raise ActiveThreadDeleteConflictError(
                f"Thread {thread_id} still has an active run"
            )

        # Checkpoint 中保存模型可恢复上下文；先清它，才能保证相同 UUID 不会复活旧上下文。
        await self._checkpoint_store.adelete_thread(thread_id)
        return self._repository.delete_thread(thread_id)
