"""验证后台 Run 所有权、真实 Task 取消和幂等终态。"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

from mini_deer_agent.application import CancelOutcome, RunExecutionManager
from mini_deer_agent.application.run_stream import RunStreamService
from mini_deer_agent.domain import TextAttachment
from mini_deer_agent.persistence import open_sqlite_conversation_repository
from mini_deer_agent.streaming import RunEvent


THREAD_ID = "11111111-1111-4111-8111-111111111111"
MESSAGE_ID = "22222222-2222-4222-8222-222222222222"


class BlockingRunStreamService:
    """产生 run_started 后永久等待，用于观察 Task.cancel 是否真正抵达。"""

    def __init__(self) -> None:
        """创建取消观察信号。"""
        self.cancel_observed = asyncio.Event()

    async def astream_run_events(
        self,
        _message: str,
        thread_id: str,
        run_id: str,
        _attachments: tuple[TextAttachment, ...] = (),
    ) -> AsyncIterator[RunEvent]:
        """等待取消并重新抛出 CancelledError，让 Manager 负责统一终态。"""
        yield RunEvent(
            event="run_started",
            run_id=run_id,
            thread_id=thread_id,
            sequence=1,
            message_id=None,
            payload={"created_at": "2026-08-26T00:00:00+00:00"},
        )
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancel_observed.set()
            raise


class CompletedRunStreamService:
    """立即自然完成，用于验证迟到取消不能改写成功事实。"""

    async def astream_run_events(
        self,
        _message: str,
        thread_id: str,
        run_id: str,
        _attachments: tuple[TextAttachment, ...] = (),
    ) -> AsyncIterator[RunEvent]:
        """依次返回开始和完成终态。"""
        yield RunEvent(
            event="run_started",
            run_id=run_id,
            thread_id=thread_id,
            sequence=1,
            message_id=None,
            payload={"created_at": "2026-08-26T00:00:00+00:00"},
        )
        yield RunEvent(
            event="run_completed",
            run_id=run_id,
            thread_id=thread_id,
            sequence=2,
            message_id=None,
            payload={"finish_reason": "stop"},
        )


def test_cancel_stops_background_task_and_is_idempotent(tmp_path: Path) -> None:
    """显式取消必须抵达后台 Task，并稳定物化一次 interrupted 终态。"""

    async def scenario() -> None:
        """在单一事件循环中启动、取消并继续消费终止事件。"""
        with open_sqlite_conversation_repository(
            tmp_path / "application.sqlite"
        ) as repository:
            stream_service = BlockingRunStreamService()
            manager = RunExecutionManager(
                cast(RunStreamService, stream_service),
                repository,
            )
            started = await manager.start_run(
                "等待取消",
                THREAD_ID,
                MESSAGE_ID,
            )
            # 在订阅者读取第一帧前取消，run_started 仍必须保留在协议中。
            first_outcome = await manager.cancel_run(
                THREAD_ID,
                started.run_id,
            )
            events = [event async for event in started.events]
            second_outcome = await manager.cancel_run(
                THREAD_ID,
                started.run_id,
            )

            assert stream_service.cancel_observed.is_set()
            assert first_outcome is CancelOutcome.cancelled
            assert second_outcome is CancelOutcome.cancelled
            assert [event.event for event in events] == [
                "run_started",
                "run_interrupted",
            ]
            assert events[1].payload == {"reason": "user_cancelled"}

            record = repository.get_run(started.run_id)
            thread = repository.get_thread(THREAD_ID)
            assert record is not None
            assert record.status == "interrupted"
            assert record.finish_reason == "user_cancelled"
            assert record.error_code is None
            assert thread is not None
            assert thread.status == "idle"

            assert (
                await manager.cancel_run(
                    "33333333-3333-4333-8333-333333333333",
                    started.run_id,
                )
                is CancelOutcome.not_found
            )

    asyncio.run(scenario())


def test_completed_run_rejects_late_cancel(tmp_path: Path) -> None:
    """自然完成优先落库后，迟到取消必须返回冲突而不是伪造 interrupted。"""

    async def scenario() -> None:
        """完整消费成功事件，再发送迟到取消。"""
        with open_sqlite_conversation_repository(
            tmp_path / "application.sqlite"
        ) as repository:
            manager = RunExecutionManager(
                cast(RunStreamService, CompletedRunStreamService()),
                repository,
            )
            started = await manager.start_run(
                "正常完成",
                THREAD_ID,
                MESSAGE_ID,
            )
            events = [event async for event in started.events]
            outcome = await manager.cancel_run(THREAD_ID, started.run_id)

            assert [event.event for event in events] == [
                "run_started",
                "run_completed",
            ]
            assert outcome is CancelOutcome.not_cancellable
            record = repository.get_run(started.run_id)
            assert record is not None
            assert record.status == "completed"
            assert record.finish_reason == "stop"

    asyncio.run(scenario())
