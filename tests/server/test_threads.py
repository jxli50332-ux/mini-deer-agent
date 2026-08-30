"""验证 Thread 删除 API 的业务边界和跨存储编排。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

from fastapi.testclient import TestClient

from mini_deer_agent.core import Settings
from mini_deer_agent.domain import ThreadRecord
from mini_deer_agent.server import create_app


THREAD_ID = "11111111-1111-4111-8111-111111111111"
MISSING_THREAD_ID = "22222222-2222-4222-8222-222222222222"


@dataclass
class StubCheckpointStore:
    """记录应用服务请求删除的 LangGraph Thread。"""

    deleted_thread_ids: list[str]

    async def adelete_thread(self, thread_id: str) -> None:
        """模拟真实 Checkpointer 的异步删除契约。"""
        self.deleted_thread_ids.append(thread_id)


class StubConversationRepository:
    """为路由测试提供最小 Thread 仓储，并记录业务删除。"""

    def __init__(self, *, status: str = "idle") -> None:
        self.record: ThreadRecord | None = ThreadRecord(
            thread_id=THREAD_ID,
            title="待删除会话",
            status=cast(Any, status),
            created_at="2026-08-30T08:00:00+00:00",
            updated_at="2026-08-30T09:00:00+00:00",
        )
        self.deleted_thread_ids: list[str] = []

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """只返回测试预置的 Thread。"""
        if self.record is None or self.record.thread_id != thread_id:
            return None
        return self.record

    def delete_thread(self, thread_id: str) -> bool:
        """模拟业务库级联删除的最终提交。"""
        if self.record is None or self.record.thread_id != thread_id:
            return False
        self.deleted_thread_ids.append(thread_id)
        self.record = None
        return True


class StubRunExecutionManager:
    """满足应用生命周期关闭契约，删除测试不启动后台 Run。"""

    async def shutdown(self) -> None:
        """测试中没有待收束任务。"""


def create_thread_test_app(
    repository: StubConversationRepository,
    checkpoint_store: StubCheckpointStore,
):
    """以同一组替身资源启动完整 FastAPI 生命周期。"""

    @asynccontextmanager
    async def open_checkpoint_store(_path: str) -> AsyncIterator[Any]:
        yield checkpoint_store

    @asynccontextmanager
    async def open_repository(_path: str) -> AsyncIterator[Any]:
        yield repository

    return create_app(
        settings_factory=lambda: Settings(_env_file=None),
        checkpointer_context_factory=open_checkpoint_store,
        conversation_repository_context_factory=open_repository,
        run_stream_service_factory=lambda _checkpointer, _repository: object(),
        run_execution_manager_factory=lambda _service, _repository: (
            StubRunExecutionManager()
        ),
    )


def test_delete_thread_removes_checkpoint_and_business_record() -> None:
    """204 只有在模型上下文与业务 Thread 都已删除后才能返回。"""
    repository = StubConversationRepository()
    checkpoint_store = StubCheckpointStore([])

    with TestClient(create_thread_test_app(repository, checkpoint_store)) as client:
        response = client.delete(f"/api/v1/threads/{THREAD_ID}")

    assert response.status_code == 204
    assert response.content == b""
    assert checkpoint_store.deleted_thread_ids == [THREAD_ID]
    assert repository.deleted_thread_ids == [THREAD_ID]


def test_delete_missing_thread_returns_stable_404_without_touching_checkpoint() -> None:
    """不存在的 Thread 不应制造 checkpoint 删除副作用。"""
    repository = StubConversationRepository()
    checkpoint_store = StubCheckpointStore([])

    with TestClient(create_thread_test_app(repository, checkpoint_store)) as client:
        response = client.delete(f"/api/v1/threads/{MISSING_THREAD_ID}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "thread_not_found"
    assert checkpoint_store.deleted_thread_ids == []
    assert repository.deleted_thread_ids == []


def test_delete_busy_thread_returns_409_and_preserves_both_stores() -> None:
    """活动 Run 持有 Thread 时不得拆除任一侧持久化状态。"""
    repository = StubConversationRepository(status="busy")
    checkpoint_store = StubCheckpointStore([])

    with TestClient(create_thread_test_app(repository, checkpoint_store)) as client:
        response = client.delete(f"/api/v1/threads/{THREAD_ID}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "thread_busy"
    assert checkpoint_store.deleted_thread_ids == []
    assert repository.deleted_thread_ids == []
