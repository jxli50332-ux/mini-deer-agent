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
OTHER_THREAD_ID = "33333333-3333-4333-8333-333333333333"
OTHER_MESSAGE_ID = "44444444-4444-4444-8444-444444444444"


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


class CancellationResistantRunStreamService:
    """模拟底层调用吞掉第一次取消，验证管理器不会无限等待。"""

    def __init__(self) -> None:
        self.cancel_observed = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()

    async def astream_run_events(
        self,
        _message: str,
        thread_id: str,
        run_id: str,
        _attachments: tuple[TextAttachment, ...] = (),
    ) -> AsyncIterator[RunEvent]:
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
            await self.release.wait()
        self.finished.set()


class FailingRunStreamService:
    """在管理器边界抛错，验证客户端仍收到可审计终态。"""

    async def astream_run_events(
        self,
        _message: str,
        _thread_id: str,
        _run_id: str,
        _attachments: tuple[TextAttachment, ...] = (),
    ) -> AsyncIterator[RunEvent]:
        if False:
            yield cast(RunEvent, None)
        raise RuntimeError("private provider failure")


class MissingTerminalRunStreamService:
    """模拟上游静默结束，管理器必须补成失败终态而不能遗留 busy。"""

    async def astream_run_events(
        self,
        _message: str,
        thread_id: str,
        run_id: str,
        _attachments: tuple[TextAttachment, ...] = (),
    ) -> AsyncIterator[RunEvent]:
        yield RunEvent(
            event="run_started",
            run_id=run_id,
            thread_id=thread_id,
            sequence=1,
            message_id=None,
            payload={},
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


def test_stream_without_terminal_is_failed_and_releases_thread(tmp_path: Path) -> None:
    async def scenario() -> None:
        with open_sqlite_conversation_repository(
            tmp_path / "missing-terminal.sqlite"
        ) as repository:
            manager = RunExecutionManager(
                cast(RunStreamService, MissingTerminalRunStreamService()),
                repository,
            )
            started = await manager.start_run(
                "静默结束",
                THREAD_ID,
                MESSAGE_ID,
            )
            events = [event async for event in started.events]
            record = repository.get_run(started.run_id)
            thread = repository.get_thread(THREAD_ID)

        assert [event.event for event in events] == ["run_started", "run_error"]
        assert record is not None and record.status == "failed"
        assert thread is not None and thread.status == "error"

    asyncio.run(scenario())


def test_cancel_timeout_forces_terminal_state_and_releases_thread(
    tmp_path: Path,
) -> None:
    """底层 Task 不响应取消时，取消 API 仍须有界返回并释放 Thread。"""

    async def scenario() -> None:
        with open_sqlite_conversation_repository(
            tmp_path / "application.sqlite"
        ) as repository:
            stream_service = CancellationResistantRunStreamService()
            manager = RunExecutionManager(
                cast(RunStreamService, stream_service),
                repository,
                cancel_grace_seconds=0.01,
            )
            started = await manager.start_run(
                "等待超时取消",
                THREAD_ID,
                MESSAGE_ID,
            )

            outcome = await asyncio.wait_for(
                manager.cancel_run(THREAD_ID, started.run_id),
                timeout=0.5,
            )

            assert outcome is CancelOutcome.cancelled
            assert stream_service.cancel_observed.is_set()
            record = repository.get_run(started.run_id)
            thread = repository.get_thread(THREAD_ID)
            assert record is not None
            assert record.status == "interrupted"
            assert record.finish_reason == "user_cancelled"
            assert thread is not None
            assert thread.status == "idle"
            assert [event.event async for event in started.events] == [
                "run_interrupted"
            ]

            stream_service.release.set()
            await asyncio.wait_for(stream_service.finished.wait(), 0.5)

    asyncio.run(scenario())


def test_different_threads_can_run_and_cancel_independently(tmp_path: Path) -> None:
    """不同 Thread 可同时运行，终止其中一个不会改变另一个的状态。"""

    async def scenario() -> None:
        with open_sqlite_conversation_repository(
            tmp_path / "application.sqlite"
        ) as repository:
            manager = RunExecutionManager(
                cast(RunStreamService, BlockingRunStreamService()),
                repository,
            )
            first = await manager.start_run("线程 A", THREAD_ID, MESSAGE_ID)
            second = await manager.start_run(
                "线程 B",
                OTHER_THREAD_ID,
                OTHER_MESSAGE_ID,
            )
            await asyncio.sleep(0)

            first_record = repository.get_run(first.run_id)
            second_record = repository.get_run(second.run_id)
            assert first_record is not None and first_record.status == "running"
            assert second_record is not None and second_record.status == "running"

            assert (
                await manager.cancel_run(THREAD_ID, first.run_id)
                is CancelOutcome.cancelled
            )
            first_record = repository.get_run(first.run_id)
            second_record = repository.get_run(second.run_id)
            assert first_record is not None and first_record.status == "interrupted"
            assert second_record is not None and second_record.status == "running"

            assert (
                await manager.cancel_run(OTHER_THREAD_ID, second.run_id)
                is CancelOutcome.cancelled
            )
            second_record = repository.get_run(second.run_id)
            assert second_record is not None and second_record.status == "interrupted"

    asyncio.run(scenario())


def test_whole_run_timeout_interrupts_and_releases_thread(tmp_path: Path) -> None:
    """无响应的模型/工具不能永久占用同一 Thread。"""

    async def scenario() -> None:
        with open_sqlite_conversation_repository(
            tmp_path / "run-timeout.sqlite"
        ) as repository:
            manager = RunExecutionManager(
                cast(RunStreamService, BlockingRunStreamService()),
                repository,
                run_timeout_seconds=0.01,
            )
            started = await manager.start_run("永久等待", THREAD_ID, MESSAGE_ID)
            events = await asyncio.wait_for(
                _collect(started.events),
                timeout=1,
            )
            record = repository.get_run(started.run_id)
            thread = repository.get_thread(THREAD_ID)

            assert [event.event for event in events] == [
                "run_started",
                "run_interrupted",
            ]
            assert events[-1].payload == {"reason": "run_timeout"}
            assert record is not None and record.status == "interrupted"
            assert record.finish_reason == "run_timeout"
            assert thread is not None and thread.status == "idle"

    async def _collect(events: AsyncIterator[RunEvent]) -> list[RunEvent]:
        return [event async for event in events]

    asyncio.run(scenario())


def test_manager_exception_publishes_run_error_terminal(tmp_path: Path) -> None:
    """管理器异常必须同时收敛数据库和 SSE，不能只在库内静默中断。"""

    async def scenario() -> None:
        with open_sqlite_conversation_repository(
            tmp_path / "manager-error.sqlite"
        ) as repository:
            manager = RunExecutionManager(
                cast(RunStreamService, FailingRunStreamService()),
                repository,
            )
            started = await manager.start_run("触发异常", THREAD_ID, MESSAGE_ID)
            events = [event async for event in started.events]
            record = repository.get_run(started.run_id)

            assert [event.event for event in events] == [
                "run_started",
                "run_error",
            ]
            assert events[-1].payload["code"] == "run_execution_manager_failed"
            assert "private provider failure" not in str(events[-1].payload)
            assert record is not None and record.status == "failed"

    asyncio.run(scenario())
