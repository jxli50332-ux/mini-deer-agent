"""验证后台 Run 所有权、真实 Task 取消和幂等终态。"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver

from mini_deer_agent.application import CancelOutcome, RunExecutionManager
from mini_deer_agent.application.run_stream import RunContextSnapshot, RunStreamService
from mini_deer_agent.domain import TextAttachment
from mini_deer_agent.llms import ModelProfile, ModelSnapshot
from mini_deer_agent.persistence import open_sqlite_conversation_repository
from mini_deer_agent.skills import (
    BuiltInSkill,
    BuiltInSkillCatalog,
    SkillCatalogError,
    SkillResource,
)
from mini_deer_agent.skills.management import SkillManagementService
from mini_deer_agent.skills.user import UserSkillManager
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


class AuthorizedCompletedRunStreamService(CompletedRunStreamService):
    """记录隐藏授权与新建 Run 的精确绑定。"""

    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.bindings: list[tuple[str, str, str]] = []

    def bind_skill_install_authorization(
        self,
        authorization_token: str,
        *,
        thread_id: str,
        run_id: str,
    ) -> None:
        self.bindings.append((authorization_token, thread_id, run_id))
        if self.reject:
            raise SkillCatalogError("authorization rejected")


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


class SnapshotRunStreamService(CompletedRunStreamService):
    def create_context_snapshot(self) -> RunContextSnapshot:
        return RunContextSnapshot(None, None, "catalog-hash")

    async def astream_run_events(
        self,
        _message: str,
        thread_id: str,
        run_id: str,
        _attachments: tuple[TextAttachment, ...] = (),
        **_options: object,
    ) -> AsyncIterator[RunEvent]:
        yield RunEvent(
            event="run_started",
            run_id=run_id,
            thread_id=thread_id,
            sequence=1,
            message_id=None,
            payload={},
        )
        yield RunEvent(
            event="run_completed",
            run_id=run_id,
            thread_id=thread_id,
            sequence=2,
            message_id=None,
            payload={"finish_reason": "stop"},
        )


class PersistentSnapshotRunStreamService:
    def __init__(self, profile_name: str) -> None:
        self.profile = ModelProfile(
            name=profile_name,
            display_name=profile_name,
            provider="openai",
            model=f"model-{profile_name}",
            api_key_env="TEST_API_KEY",
        )
        self.model = cast(BaseChatModel, object())
        self.catalog = BuiltInSkillCatalog((
            BuiltInSkill(
                name=f"skill-{profile_name}",
                description="snapshot skill",
                instructions=f"use {profile_name}",
                source_file=Path("snapshot") / "SKILL.md",
                allowed_tools=(),
                resources=(SkillResource("references/note.md", profile_name),),
                source="user",
            ),
        ))
        snapshot = ModelSnapshot(
            profile_name,
            f"profiles-{profile_name}",
            1,
            self.model,
            self.profile,
        )

        def restore_model(**kwargs: object) -> ModelSnapshot:
            return ModelSnapshot(
                cast(ModelProfile, kwargs["profile"]).name,
                cast(str, kwargs["profile_revision"]),
                cast(int, kwargs["selection_revision"]),
                self.model,
                cast(ModelProfile, kwargs["profile"]),
            )

        self.helper = RunStreamService(
            InMemorySaver(),
            model_snapshot_factory=lambda: snapshot,
            model_snapshot_restorer=restore_model,
            skill_catalog_factory=lambda: self.catalog,
        )
        self.observed_profile_names: list[str | None] = []
        self.observed_skill_names: list[tuple[str, ...]] = []

    def create_context_snapshot(self) -> RunContextSnapshot:
        return self.helper.create_context_snapshot()

    def serialize_context_snapshot(self, snapshot: RunContextSnapshot) -> str:
        return self.helper.serialize_context_snapshot(snapshot)

    def restore_context_snapshot(self, serialized: str) -> RunContextSnapshot:
        return self.helper.restore_context_snapshot(serialized)

    def create_run_budget_tracker(self, _run_id: str) -> None:
        return None

    async def astream_run_events(
        self,
        _message: str,
        thread_id: str,
        run_id: str,
        _attachments: tuple[TextAttachment, ...] = (),
        **options: object,
    ) -> AsyncIterator[RunEvent]:
        model = cast(ModelSnapshot | None, options.get("model_snapshot"))
        catalog = cast(BuiltInSkillCatalog | None, options.get("skill_catalog"))
        self.observed_profile_names.append(
            model.profile_name if model is not None else None
        )
        self.observed_skill_names.append(
            tuple(skill.name for skill in catalog.skills) if catalog is not None else ()
        )
        yield RunEvent("run_started", run_id, thread_id, 1, None, {})
        yield RunEvent(
            "run_completed",
            run_id,
            thread_id,
            2,
            None,
            {"finish_reason": "stop"},
        )


class ActiveGoalEvaluationService:
    async def current_revision(self, _thread_id: str) -> str:
        return "goal-revision"

    async def resume_for_user_run(
        self,
        _thread_id: str,
        *,
        is_human_input_response: bool,
    ) -> str:
        del is_human_input_response
        return "goal-revision"

    async def evaluate_run(self, **_kwargs: object) -> dict[str, object]:
        return {"satisfied": False}

    async def prepare_continuation(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(continue_run=False, message=None)


def test_run_started_persists_context_snapshot_metadata(tmp_path: Path) -> None:
    async def scenario() -> None:
        with open_sqlite_conversation_repository(
            tmp_path / "application.sqlite"
        ) as repository:
            manager = RunExecutionManager(
                cast(RunStreamService, SnapshotRunStreamService()), repository
            )
            started = await manager.start_run("快照", THREAD_ID, MESSAGE_ID)
            assert [event.event async for event in started.events] == [
                "run_started",
                "run_completed",
            ]
            stored = repository.list_run_events(
                THREAD_ID, started.run_id, after_sequence=0, limit=10
            )
            assert stored[0].payload["skill_catalog_hash"] == "catalog-hash"
            run = repository.get_run(started.run_id)
            assert run is not None
            assert run.skill_catalog_hash == "catalog-hash"

    asyncio.run(scenario())


def test_run_binds_hidden_skill_authorization_to_exact_created_run(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        with open_sqlite_conversation_repository(
            tmp_path / "application.sqlite"
        ) as repository:
            stream = AuthorizedCompletedRunStreamService()
            manager = RunExecutionManager(cast(RunStreamService, stream), repository)
            started = await manager.start_run(
                "创建天气 Skill",
                THREAD_ID,
                MESSAGE_ID,
                skill_install_authorization_token="a" * 32,
            )
            assert [event.event async for event in started.events][-1] == "run_completed"
            assert stream.bindings == [("a" * 32, THREAD_ID, started.run_id)]

    asyncio.run(scenario())


def test_rejected_skill_authorization_interrupts_persisted_run(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        with open_sqlite_conversation_repository(
            tmp_path / "application.sqlite"
        ) as repository:
            stream = AuthorizedCompletedRunStreamService(reject=True)
            manager = RunExecutionManager(cast(RunStreamService, stream), repository)
            try:
                await manager.start_run(
                    "创建天气 Skill",
                    THREAD_ID,
                    MESSAGE_ID,
                    skill_install_authorization_token="b" * 32,
                )
            except SkillCatalogError as exc:
                assert str(exc) == "authorization rejected"
            else:
                raise AssertionError("预期授权绑定失败")
            run_id = stream.bindings[0][2]
            run = repository.get_run(run_id)
            assert run is not None
            assert run.status == "interrupted"
            assert run.error_code == "skill_install_authorization_failed"

    asyncio.run(scenario())


def test_goal_context_snapshot_survives_manager_restart_and_default_change(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = tmp_path / "application.sqlite"
        with open_sqlite_conversation_repository(database) as repository:
            old_stream = PersistentSnapshotRunStreamService("old")
            first_manager = RunExecutionManager(
                cast(RunStreamService, old_stream),
                repository,
                goal_evaluation_service=cast(object, ActiveGoalEvaluationService()),
            )
            first = await first_manager.start_run("first", THREAD_ID, MESSAGE_ID)
            assert [item.event async for item in first.events][-1] == "run_completed"
            stored = repository.get_goal_context_snapshot(THREAD_ID)
            assert stored is not None
            assert '"profile_name": "old"' in stored[1]

            new_stream = PersistentSnapshotRunStreamService("new")
            second_manager = RunExecutionManager(
                cast(RunStreamService, new_stream),
                repository,
                goal_evaluation_service=cast(object, ActiveGoalEvaluationService()),
            )
            second = await second_manager.start_run(
                "continue",
                THREAD_ID,
                OTHER_MESSAGE_ID,
                internal_continuation=True,
            )
            events = [item async for item in second.events]
            assert events[0].payload["model_profile"] == "old"
            persisted_run = repository.get_run(second.run_id)
            assert persisted_run is not None
            assert persisted_run.model_profile == "old"
            assert new_stream.observed_profile_names == ["old"]
            assert new_stream.observed_skill_names == [("skill-old",)]

    asyncio.run(scenario())


def test_context_snapshot_freezes_and_restores_agent_skill_creation_setting(
    tmp_path: Path,
) -> None:
    management = SkillManagementService(
        UserSkillManager(
            tmp_path / "managed-skills",
            builtin_root=tmp_path / "builtin-skills",
        )
    )
    service = RunStreamService(
        InMemorySaver(),
        skill_management_service=management,
    )

    snapshot = service.create_context_snapshot()
    assert snapshot.skill_creation_enabled is True
    assert snapshot.metadata["skill_agent_creation_enabled"] == 1

    management.update_agent_settings(
        creation_enabled=False,
        expected_revision=0,
    )
    restored = service.restore_context_snapshot(
        service.serialize_context_snapshot(snapshot)
    )

    assert restored.skill_creation_enabled is True
    assert service.create_context_snapshot().skill_creation_enabled is False


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
