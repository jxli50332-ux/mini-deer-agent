"""验证 17.1 Goal 状态、接口、替换清除与跨进程 checkpoint 恢复。"""

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Self, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import Field

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.application import (
    ActiveRunConflictError,
    GoalCompletionEvaluator,
    GoalEvaluationService,
    GoalStateService,
    RunExecutionManager,
    StartedRun,
    GoalContinuationDecision,
    CancelOutcome,
)
from mini_deer_agent.agents.middleware import RunBudgetTracker
from mini_deer_agent.domain import ThreadRecord
from mini_deer_agent.llms import ModelSnapshot
from mini_deer_agent.persistence import (
    open_async_sqlite_checkpointer,
    open_sqlite_conversation_repository,
)
from mini_deer_agent.server.routers import runs, threads
from mini_deer_agent.streaming.events import RunEvent


THREAD_ID = "33333333-3333-4333-8333-333333333333"


class _BindableModel(FakeMessagesListChatModel):
    histories: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Self:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        self.histories.append(list(messages))
        return super()._generate(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        )


def test_goal_evaluation_records_actual_model_snapshot() -> None:
    async def scenario() -> None:
        model = _BindableModel(
            responses=[
                AIMessage(
                    content=(
                        '{"satisfied":true,"blocker":"none",'
                        '"reason":"已完成","evidence_summary":"已有完成证据"}'
                    )
                )
            ]
        )
        evaluator = GoalCompletionEvaluator(
            lambda: ModelSnapshot(
                "goal-profile",
                "profile-revision",
                7,
                model,
            )
        )
        result = await evaluator.evaluate(
            objective="完成任务",
            evidence=({"kind": "assistant", "content": "任务完成。"},),
        )
        assert result["model_profile"] == "goal-profile"
        assert result["model_profile_revision"] == "profile-revision"
        assert result["model_selection_revision"] == 7

    asyncio.run(scenario())


class _ThreadRepository:
    def __init__(self, status: str = "idle") -> None:
        self.record = ThreadRecord(
            thread_id=THREAD_ID,
            title="Goal 测试",
            status=cast(Any, status),
            created_at="2026-09-08T00:00:00Z",
            updated_at="2026-09-08T00:00:00Z",
        )

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        return self.record if thread_id == self.record.thread_id else None

    def ensure_thread(self, *, thread_id: str) -> ThreadRecord:
        if thread_id != self.record.thread_id:
            self.record = replace(
                self.record,
                thread_id=thread_id,
                title="新对话",
                status="idle",
            )
        return self.record

    def touch_thread(self, thread_id: str) -> ThreadRecord | None:
        return self.get_thread(thread_id)


def test_goal_set_replace_query_and_clear_use_checkpoint_state() -> None:
    async def scenario() -> None:
        service = GoalStateService(
            cast(Any, _ThreadRepository()),
            InMemorySaver(),
        )
        assert await service.get_goal(THREAD_ID) is None

        first = await service.set_goal(
            THREAD_ID,
            objective="  完成项目测试并修复失败  ",
            max_continuations=4,
        )
        assert first["objective"] == "完成项目测试并修复失败"
        assert first["continuation_count"] == 0
        assert first["no_progress_count"] == 0
        assert first["last_evaluation"] is None
        assert first["status"] == "active"
        assert (await service.get_goal(THREAD_ID))["revision"] == first["revision"]

        replaced = await service.set_goal(
            THREAD_ID,
            objective="只运行聚焦测试",
            max_continuations=2,
            expected_revision=first["revision"],
        )
        assert replaced["revision"] != first["revision"]
        assert replaced["max_continuations"] == 2
        assert await service.clear_goal(THREAD_ID) is True
        assert await service.clear_goal(THREAD_ID) is False
        assert await service.get_goal(THREAD_ID) is None

    asyncio.run(scenario())


def test_goal_survives_async_sqlite_reopen(tmp_path: Path) -> None:
    async def scenario() -> None:
        database_path = tmp_path / "goals.sqlite"
        repository = cast(Any, _ThreadRepository())
        async with open_async_sqlite_checkpointer(database_path) as checkpointer:
            service = GoalStateService(repository, checkpointer)
            created = await service.set_goal(
                THREAD_ID,
                objective="跨重启完成目标",
                max_continuations=5,
            )

        async with open_async_sqlite_checkpointer(database_path) as checkpointer:
            restored = await GoalStateService(repository, checkpointer).get_goal(
                THREAD_ID
            )

        assert restored is not None
        assert restored["revision"] == created["revision"]
        assert restored["objective"] == "跨重启完成目标"

    asyncio.run(scenario())


def test_goal_channel_survives_a_normal_agent_run() -> None:
    async def scenario() -> None:
        saver = InMemorySaver()
        repository = cast(Any, _ThreadRepository())
        service = GoalStateService(repository, saver)
        created = await service.set_goal(THREAD_ID, objective="保持目标状态")
        model = _BindableModel(responses=[AIMessage(content="普通 Run 完成。")])
        graph = build_agent_graph(model, checkpointer=saver)
        config = {"configurable": {"thread_id": THREAD_ID}}

        await graph.ainvoke(
            {"messages": [HumanMessage(content="执行一次普通请求。")]},
            config,
        )
        restored = await service.get_goal(THREAD_ID)

        assert restored is not None
        assert restored["revision"] == created["revision"]
        assert restored["continuation_count"] == 0

    asyncio.run(scenario())


def test_active_goal_is_projected_to_model_without_becoming_user_history() -> None:
    async def scenario() -> None:
        saver = InMemorySaver()
        service = GoalStateService(cast(Any, _ThreadRepository()), saver)
        objective = '准确回答 17 < 25，并明确写出“17 + 25 = 42”。'
        await service.set_goal(THREAD_ID, objective=objective)
        model = _BindableModel(responses=[AIMessage(content="17 + 25 = 42")])
        graph = build_agent_graph(model, checkpointer=saver)
        config = {"configurable": {"thread_id": THREAD_ID}}

        await graph.ainvoke(
            {"messages": [HumanMessage(content="请完成当前 Goal。")]},
            config,
        )

        assert len(model.histories) == 1
        projected_system = model.histories[0][0]
        assert isinstance(projected_system, SystemMessage)
        assert "<active_thread_goal>" in projected_system.text
        assert "准确回答 17 &lt; 25" in projected_system.text
        assert "17 + 25 = 42" in projected_system.text
        assert "不要声称需要或存在可调用的 goal 工具" in projected_system.text
        assert "它替换对话历史或累计摘要中出现的旧 Goal" in projected_system.text

        snapshot = await graph.aget_state(config)
        persisted_messages = snapshot.values["messages"]
        assert not any(
            isinstance(message, SystemMessage) for message in persisted_messages
        )
        assert [
            message.text
            for message in persisted_messages
            if isinstance(message, HumanMessage)
        ] == ["请完成当前 Goal。"]

    asyncio.run(scenario())


def test_replaced_goal_excludes_old_goal_conversation_from_model_request() -> None:
    async def scenario() -> None:
        saver = InMemorySaver()
        repository = cast(Any, _ThreadRepository())
        model = _BindableModel(
            responses=[
                AIMessage(content="旧任务回答：继续规划南京旅行"),
                AIMessage(content="松鼠"),
            ]
        )
        graph = build_agent_graph(model, checkpointer=saver)
        config = {"configurable": {"thread_id": THREAD_ID}}
        await graph.ainvoke(
            {"messages": [HumanMessage(content="旧目标是规划南京旅行")]},
            config,
        )

        state = GoalStateService(repository, saver)
        await state.set_goal(THREAD_ID, objective="只回答松鼠")
        await graph.ainvoke(
            {"messages": [HumanMessage(content="现在的目标是什么？")]},
            config,
        )

        latest = model.histories[-1]
        assert any(
            isinstance(message, SystemMessage) and "只回答松鼠" in message.text
            for message in latest
        )
        non_system_text = "\n".join(
            message.text
            for message in latest
            if not isinstance(message, SystemMessage)
        )
        assert "现在的目标是什么" in non_system_text
        assert "规划南京旅行" not in non_system_text

    asyncio.run(scenario())


def test_user_run_resumes_paused_goal_but_not_explicitly_stopped_goal() -> None:
    async def scenario() -> None:
        state = GoalStateService(cast(Any, _ThreadRepository()), InMemorySaver())
        goal = await state.set_goal(THREAD_ID, objective="等待用户澄清后继续")
        needs_input = {
            "satisfied": False,
            "blocker": "needs_user_input",
            "reason": "需要日期和预算",
            "evidence_summary": "已向用户提出澄清问题",
            "evaluated_at": "2026-09-08T01:00:00Z",
        }
        assert await state.apply_evaluation(
            THREAD_ID,
            expected_revision=goal["revision"],
            evaluation=cast(Any, needs_input),
        )
        paused = await state.get_goal(THREAD_ID)
        assert paused is not None
        assert paused["status"] == "paused"
        assert paused["stop_reason"] == "needs_user_input"

        unchanged = await state.resume_for_user_run(
            THREAD_ID,
            is_human_input_response=False,
        )
        assert unchanged == paused

        resumed = await state.resume_for_user_run(
            THREAD_ID,
            is_human_input_response=True,
        )
        assert resumed is not None
        assert resumed["revision"] == goal["revision"]
        assert resumed["status"] == "active"
        assert resumed["stop_reason"] is None
        assert resumed["last_evaluation"] == needs_input

        stopped = await state.stop_goal(THREAD_ID)
        assert stopped is not None
        assert (
            await state.resume_for_user_run(
                THREAD_ID,
                is_human_input_response=True,
            )
        ) == stopped

    asyncio.run(scenario())


def test_goal_mutation_allows_busy_replacement_creates_draft_and_rejects_invalid() -> None:
    async def scenario() -> None:
        busy = GoalStateService(
            cast(Any, _ThreadRepository(status="busy")),
            InMemorySaver(),
        )
        replaced = await busy.set_goal(THREAD_ID, objective="用户的新目标优先")
        assert replaced["objective"] == "用户的新目标优先"

        missing = GoalStateService(cast(Any, _ThreadRepository()), InMemorySaver())
        draft = await missing.set_goal("missing", objective="首次 Run 前保存")
        assert draft["objective"] == "首次 Run 前保存"
        assert missing.get_thread("missing") is not None
        with pytest.raises(ValueError, match="objective"):
            await missing.set_goal(THREAD_ID, objective="   ")
        with pytest.raises(ValueError, match="max_continuations"):
            await missing.set_goal(THREAD_ID, objective="目标", max_continuations=21)

    asyncio.run(scenario())


def test_goal_saved_before_first_run_creates_real_idle_thread(tmp_path: Path) -> None:
    async def scenario() -> None:
        with open_sqlite_conversation_repository(
            tmp_path / "goal-before-run.sqlite"
        ) as repository:
            state = GoalStateService(cast(Any, repository), InMemorySaver())
            saved = await state.set_goal(
                THREAD_ID,
                objective="首次 Run 前也要持久保存",
            )
            thread = repository.get_thread(THREAD_ID)
            listed = repository.list_threads(limit=10)

        assert thread is not None
        assert thread.status == "idle"
        assert thread.title == "新对话"
        assert [item.thread_id for item in listed] == [THREAD_ID]
        assert (await state.get_goal(THREAD_ID))["revision"] == saved["revision"]

    asyncio.run(scenario())


def test_goal_http_contract_supports_replace_query_and_clear() -> None:
    app = FastAPI()
    app.state.goal_state_service = GoalStateService(
        cast(Any, _ThreadRepository()),
        InMemorySaver(),
    )
    app.state.run_execution_manager = object()
    app.include_router(threads.router)

    with TestClient(app) as client:
        created = client.put(
            f"/api/v1/threads/{THREAD_ID}/goal",
            json={"objective": "完成 17 阶段", "max_continuations": 3},
        )
        assert created.status_code == 200
        assert created.json()["objective"] == "完成 17 阶段"
        first_revision = created.json()["revision"]

        unconditional = client.put(
            f"/api/v1/threads/{THREAD_ID}/goal",
            json={"objective": "不能无条件覆盖"},
        )
        assert unconditional.status_code == 409
        assert unconditional.json()["detail"]["code"] == "goal_conflict"

        queried = client.get(f"/api/v1/threads/{THREAD_ID}/goal")
        assert queried.status_code == 200
        assert queried.json()["revision"] == first_revision

        replaced = client.put(
            f"/api/v1/threads/{THREAD_ID}/goal",
            json={
                "objective": "替换后的目标",
                "expected_revision": first_revision,
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["revision"] != first_revision
        assert replaced.json()["max_continuations"] == 6

        stopped = client.post(
            f"/api/v1/threads/{THREAD_ID}/goal/stop",
            json={"revision": replaced.json()["revision"]},
        )
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"
        assert stopped.json()["stop_reason"] == "user_stopped"
        assert stopped.json()["revision"] != replaced.json()["revision"]

        assert client.delete(
            f"/api/v1/threads/{THREAD_ID}/goal",
            params={"revision": stopped.json()["revision"]},
        ).status_code == 204
        missing = client.get(f"/api/v1/threads/{THREAD_ID}/goal")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "goal_not_found"
        missing_stop = client.post(
            f"/api/v1/threads/{THREAD_ID}/goal/stop",
            json={"revision": stopped.json()["revision"]},
        )
        assert missing_stop.status_code == 404
        assert missing_stop.json()["detail"]["code"] == "goal_not_found"


def test_stopped_goal_can_resume_into_hidden_run_with_revision_guard() -> None:
    async def empty_events():
        if False:  # pragma: no cover - 保持 AsyncIterator 形状
            yield None

    repository = _ThreadRepository()
    state = GoalStateService(cast(Any, repository), InMemorySaver())

    class _Manager:
        calls: list[dict[str, object]] = []

        async def start_run(self, message, thread_id, user_message_id, **kwargs):
            self.calls.append(
                {
                    "message": message,
                    "thread_id": thread_id,
                    "user_message_id": user_message_id,
                    **kwargs,
                }
            )
            return StartedRun(
                run_id="99999999-9999-4999-8999-999999999999",
                events=empty_events(),
            )

    manager = _Manager()
    app = FastAPI()
    app.state.goal_state_service = state
    app.state.run_execution_manager = manager
    app.include_router(threads.router)
    app.include_router(runs.router)

    with TestClient(app) as client:
        original = client.put(
            f"/api/v1/threads/{THREAD_ID}/goal",
            json={"objective": "继续完成全部修复"},
        ).json()
        stopped_response = client.post(
            f"/api/v1/threads/{THREAD_ID}/goal/stop",
            json={"revision": original["revision"]},
        )
        assert stopped_response.status_code == 200
        stopped = stopped_response.json()
        stale = client.post(
            f"/api/v1/threads/{THREAD_ID}/goal/resume",
            json={
                "revision": original["revision"],
                "message_id": "88888888-8888-4888-8888-888888888888",
            },
        )
        assert stale.status_code == 409

        with client.stream(
            "POST",
            f"/api/v1/threads/{THREAD_ID}/goal/resume",
            json={
                "revision": stopped["revision"],
                "message_id": "88888888-8888-4888-8888-888888888888",
            },
        ) as response:
            _ = b"".join(response.iter_bytes())

        resumed = client.get(f"/api/v1/threads/{THREAD_ID}/goal").json()

    assert response.status_code == 200
    assert response.headers["x-run-id"] == "99999999-9999-4999-8999-999999999999"
    assert manager.calls[0]["internal_continuation"] is True
    assert "继续完成全部修复" in str(manager.calls[0]["message"])
    assert resumed["status"] == "active"
    assert resumed["continuation_count"] == 0
    assert resumed["revision"] != stopped["revision"]


def test_stale_goal_stop_does_not_cancel_current_run() -> None:
    repository = _ThreadRepository()

    class _Manager:
        calls: list[tuple[str, str]] = []

        async def cancel_active_run(self, thread_id: str, *, reason: str):
            self.calls.append((thread_id, reason))
            return CancelOutcome.cancelled

    manager = _Manager()
    state = GoalStateService(cast(Any, repository), InMemorySaver())
    app = FastAPI()
    app.state.goal_state_service = state
    app.state.run_execution_manager = manager
    app.include_router(threads.router)

    with TestClient(app) as client:
        current = client.put(
            f"/api/v1/threads/{THREAD_ID}/goal",
            json={"objective": "当前目标"},
        ).json()
        repository.record = replace(repository.record, status="busy")
        response = client.post(
            f"/api/v1/threads/{THREAD_ID}/goal/stop",
            json={"revision": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
        )

    assert response.status_code == 409
    assert manager.calls == []
    assert current["status"] == "active"


def test_resume_start_failure_restores_previous_goal_state() -> None:
    repository = _ThreadRepository()
    state = GoalStateService(cast(Any, repository), InMemorySaver())

    class _Manager:
        async def start_run(self, *args: object, **kwargs: object):
            del args, kwargs
            raise RuntimeError("run store unavailable")

    app = FastAPI()
    app.state.goal_state_service = state
    app.state.run_execution_manager = _Manager()
    app.include_router(threads.router)
    app.include_router(runs.router)

    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.put(
            f"/api/v1/threads/{THREAD_ID}/goal",
            json={"objective": "失败后仍可重试"},
        ).json()
        stopped = client.post(
            f"/api/v1/threads/{THREAD_ID}/goal/stop",
            json={"revision": created["revision"]},
        ).json()
        response = client.post(
            f"/api/v1/threads/{THREAD_ID}/goal/resume",
            json={
                "revision": stopped["revision"],
                "message_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            },
        )
        restored = client.get(f"/api/v1/threads/{THREAD_ID}/goal").json()

    assert response.status_code == 500
    assert restored["revision"] == stopped["revision"]
    assert restored["status"] == "stopped"
    assert restored["stop_reason"] == "user_stopped"


def test_resume_run_conflict_restores_previous_goal_state() -> None:
    repository = _ThreadRepository()
    state = GoalStateService(cast(Any, repository), InMemorySaver())

    class _Manager:
        async def start_run(self, *args: object, **kwargs: object):
            del args, kwargs
            repository.record = replace(repository.record, status="busy")
            raise ActiveRunConflictError("already running")

    app = FastAPI()
    app.state.goal_state_service = state
    app.state.run_execution_manager = _Manager()
    app.include_router(threads.router)
    app.include_router(runs.router)

    with TestClient(app) as client:
        created = client.put(
            f"/api/v1/threads/{THREAD_ID}/goal",
            json={"objective": "冲突后保留停止态"},
        ).json()
        stopped = client.post(
            f"/api/v1/threads/{THREAD_ID}/goal/stop",
            json={"revision": created["revision"]},
        ).json()
        response = client.post(
            f"/api/v1/threads/{THREAD_ID}/goal/resume",
            json={
                "revision": stopped["revision"],
                "message_id": "cdcdcdcd-cdcd-4dcd-8dcd-cdcdcdcdcdcd",
            },
        )
        restored = client.get(f"/api/v1/threads/{THREAD_ID}/goal").json()

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "run_conflict"
    assert restored["revision"] == stopped["revision"]
    assert restored["status"] == "stopped"


def test_goal_mutation_cancels_busy_run_before_replacing_goal() -> None:
    repository = _ThreadRepository(status="busy")

    class _Manager:
        calls: list[tuple[str, str]] = []

        async def cancel_active_run(self, thread_id: str, *, reason: str):
            self.calls.append((thread_id, reason))
            repository.record = replace(repository.record, status="idle")
            return CancelOutcome.cancelled

    manager = _Manager()
    app = FastAPI()
    app.state.goal_state_service = GoalStateService(
        cast(Any, repository),
        InMemorySaver(),
    )
    app.state.run_execution_manager = manager
    app.include_router(threads.router)

    with TestClient(app) as client:
        response = client.put(
            f"/api/v1/threads/{THREAD_ID}/goal",
            json={"objective": "替换后继续"},
        )

    assert response.status_code == 200
    assert response.json()["objective"] == "替换后继续"
    assert manager.calls == [(THREAD_ID, "goal_replaced")]


def test_independent_evaluator_clears_satisfied_goal_and_fails_closed(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        saver = InMemorySaver()
        with open_sqlite_conversation_repository(
            tmp_path / "evaluation.sqlite"
        ) as repository:
            repository.create_run(
                thread_id=THREAD_ID,
                run_id="44444444-4444-4444-8444-444444444444",
                user_message_id="55555555-5555-4555-8555-555555555555",
                user_message="完成目标",
            )
            for event in (
                RunEvent(
                    event="run_started",
                    run_id="44444444-4444-4444-8444-444444444444",
                    thread_id=THREAD_ID,
                    sequence=1,
                    message_id=None,
                    payload={},
                ),
                RunEvent(
                    event="ai_delta",
                    run_id="44444444-4444-4444-8444-444444444444",
                    thread_id=THREAD_ID,
                    sequence=2,
                    message_id="66666666-6666-4666-8666-666666666666",
                    payload={"text": "测试已全部通过。"},
                ),
                RunEvent(
                    event="run_completed",
                    run_id="44444444-4444-4444-8444-444444444444",
                    thread_id=THREAD_ID,
                    sequence=3,
                    message_id=None,
                    payload={"finish_reason": "stop"},
                ),
            ):
                repository.apply_run_event(event)

            state = GoalStateService(cast(Any, repository), saver)
            await state.set_goal(THREAD_ID, objective="让测试全部通过")
            model = _BindableModel(
                responses=[
                    AIMessage(
                        content=(
                            '{"satisfied":true,"blocker":"none",'
                            '"reason":"可见结果明确完成",'
                            '"evidence_summary":"Assistant 报告测试全部通过"}'
                        )
                    )
                ]
            )
            service = GoalEvaluationService(
                cast(Any, repository),
                state,
                GoalCompletionEvaluator(model),
            )
            evaluation = await service.evaluate_run(
                thread_id=THREAD_ID,
                run_id="44444444-4444-4444-8444-444444444444",
                terminal_event="run_completed",
            )
            assert evaluation is not None and evaluation["satisfied"] is True
            completed = await state.get_goal(THREAD_ID)
            assert completed is not None
            assert completed["status"] == "completed"
            assert completed["last_evaluation"] == evaluation
            assert "测试已全部通过" in model.histories[0][1].text

            await state.set_goal(
                THREAD_ID,
                objective="再次完成",
                expected_revision=completed["revision"],
            )
            invalid = GoalEvaluationService(
                cast(Any, repository),
                state,
                GoalCompletionEvaluator(
                    _BindableModel(responses=[AIMessage(content="不是 JSON")])
                ),
            )
            fallback = await invalid.evaluate_run(
                thread_id=THREAD_ID,
                run_id="44444444-4444-4444-8444-444444444444",
                terminal_event="run_completed",
            )
            restored = await state.get_goal(THREAD_ID)
            assert fallback is not None
            assert fallback["blocker"] == "missing_evidence"
            assert restored is not None
            assert restored["last_evaluation"]["blocker"] == "missing_evidence"

    asyncio.run(scenario())


def test_goal_evidence_keeps_latest_answer_after_large_tool_history(
    tmp_path: Path,
) -> None:
    """长工具轨迹不能再次把最终 Assistant 回答从评估输入头部截掉。"""

    async def scenario() -> None:
        run_id = "12121212-1212-4212-8212-121212121212"
        with open_sqlite_conversation_repository(
            tmp_path / "goal-evidence-window.sqlite"
        ) as repository:
            repository.create_run(
                thread_id=THREAD_ID,
                run_id=run_id,
                user_message_id="13131313-1313-4313-8313-131313131313",
                user_message="完成一份长任务",
            )
            repository.apply_run_event(
                RunEvent(
                    event="run_started",
                    run_id=run_id,
                    thread_id=THREAD_ID,
                    sequence=1,
                    message_id=None,
                    payload={},
                )
            )
            sequence = 2
            for index in range(30):
                tool_call_id = f"large-tool-{index}"
                repository.apply_run_event(
                    RunEvent(
                        event="tool_call_delta",
                        run_id=run_id,
                        thread_id=THREAD_ID,
                        sequence=sequence,
                        message_id=f"tool-request-{index}",
                        payload={
                            "tool_call_id": tool_call_id,
                            "name": "reader",
                            "arguments_delta": "{}",
                            "index": 0,
                        },
                    )
                )
                sequence += 1
                repository.apply_run_event(
                    RunEvent(
                        event="tool_result",
                        run_id=run_id,
                        thread_id=THREAD_ID,
                        sequence=sequence,
                        message_id=f"tool-result-{index}",
                        payload={
                            "tool_call_id": tool_call_id,
                            "name": "reader",
                            "content": "x" * 8_000,
                        },
                    )
                )
                sequence += 1
            repository.apply_run_event(
                RunEvent(
                    event="ai_delta",
                    run_id=run_id,
                    thread_id=THREAD_ID,
                    sequence=sequence,
                    message_id="14141414-1414-4414-8414-141414141414",
                    payload={"text": "最终结论：三项要求已经全部完成。"},
                )
            )
            sequence += 1
            repository.apply_run_event(
                RunEvent(
                    event="run_completed",
                    run_id=run_id,
                    thread_id=THREAD_ID,
                    sequence=sequence,
                    message_id=None,
                    payload={"finish_reason": "stop"},
                )
            )
            state = GoalStateService(cast(Any, repository), InMemorySaver())
            await state.set_goal(THREAD_ID, objective="完成全部三项要求")
            model = _BindableModel(
                responses=[
                    AIMessage(
                        content=(
                            '{"satisfied":true,"blocker":"none",'
                            '"reason":"最终回答确认完成",'
                            '"evidence_summary":"三项要求全部完成"}'
                        )
                    )
                ]
            )
            evaluation = GoalEvaluationService(
                cast(Any, repository),
                state,
                GoalCompletionEvaluator(model),
            )

            result = await evaluation.evaluate_run(
                thread_id=THREAD_ID,
                run_id=run_id,
                terminal_event="run_completed",
            )

            payload = model.histories[0][1].text
            assert len(payload) <= 24_000
            assert json.loads(payload)["visible_evidence"][-1]["content"] == (
                "最终结论：三项要求已经全部完成。"
            )
            assert result is not None and result["satisfied"] is True
            completed = await state.get_goal(THREAD_ID)
            assert completed is not None
            assert completed["status"] == "completed"

    import json

    asyncio.run(scenario())


def test_run_manager_evaluates_every_terminal_goal_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        calls: list[tuple[str, str, str]] = []

        class _StreamService:
            def create_run_budget_tracker(self, run_id: str) -> RunBudgetTracker:
                tracker = RunBudgetTracker()
                tracker.pin_run(run_id)
                return tracker

            async def astream_run_events(
                self,
                message: str,
                thread_id: str,
                run_id: str,
                *args: object,
                **kwargs: object,
            ):
                del message, args, kwargs
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

        class _EvaluationService:
            async def current_revision(self, thread_id: str) -> str:
                assert thread_id == THREAD_ID
                return "test-goal-revision"

            async def resume_for_user_run(
                self,
                thread_id: str,
                *,
                is_human_input_response: bool,
            ) -> str:
                del is_human_input_response
                return await self.current_revision(thread_id)

            async def evaluate_run(
                self,
                *,
                thread_id: str,
                run_id: str,
                terminal_event: str,
                expected_revision: str | None = None,
            ) -> None:
                assert expected_revision == "test-goal-revision"
                calls.append((thread_id, run_id, terminal_event))

            async def prepare_continuation(
                self,
                **kwargs: object,
            ) -> GoalContinuationDecision:
                return GoalContinuationDecision(False, "done")

        with open_sqlite_conversation_repository(
            tmp_path / "manager-evaluation.sqlite"
        ) as repository:
            manager = RunExecutionManager(
                cast(Any, _StreamService()),
                repository,
                goal_evaluation_service=cast(Any, _EvaluationService()),
            )
            started = await manager.start_run(
                "执行目标",
                THREAD_ID,
                "77777777-7777-4777-8777-777777777777",
            )
            events = [event async for event in started.events]
            assert [event.event for event in events] == [
                "run_started",
                "goal_status",
                "goal_status",
                "run_completed",
            ]
            assert calls == [(THREAD_ID, started.run_id, "run_completed")]

    asyncio.run(scenario())


def test_goal_evaluator_failure_does_not_swallow_completed_run(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        class _CompletedStream:
            def create_run_budget_tracker(self, run_id: str) -> RunBudgetTracker:
                tracker = RunBudgetTracker()
                tracker.pin_run(run_id)
                return tracker

            async def astream_run_events(
                self,
                _message: str,
                thread_id: str,
                run_id: str,
                *args: object,
                **kwargs: object,
            ):
                del args, kwargs
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

        class _BrokenEvaluation:
            async def resume_for_user_run(
                self,
                _thread_id: str,
                *,
                is_human_input_response: bool,
            ) -> str:
                del is_human_input_response
                return "goal-revision"

            async def evaluate_run(self, **_kwargs: object):
                raise RuntimeError("checkpoint unavailable")

        with open_sqlite_conversation_repository(
            tmp_path / "goal-evaluator-failure.sqlite"
        ) as repository:
            manager = RunExecutionManager(
                cast(Any, _CompletedStream()),
                repository,
                goal_evaluation_service=cast(Any, _BrokenEvaluation()),
            )
            started = await manager.start_run(
                "完成正常工作",
                THREAD_ID,
                "15151515-1515-4515-8515-151515151515",
            )
            events = [event async for event in started.events]
            record = repository.get_run(started.run_id)

            assert [event.event for event in events] == [
                "run_started",
                "goal_status",
                "goal_status",
                "run_completed",
            ]
            assert record is not None and record.status == "completed"

    asyncio.run(scenario())


def test_goal_continuation_enforces_max_no_progress_budget_and_revision_race() -> None:
    async def scenario() -> None:
        state = GoalStateService(cast(Any, _ThreadRepository()), InMemorySaver())
        first = await state.set_goal(
            THREAD_ID,
            objective="有界目标",
            max_continuations=1,
        )
        evaluation = {
            "satisfied": False,
            "blocker": "goal_not_met_yet",
            "reason": "仍需一步",
            "evidence_summary": "已完成第一步",
            "evaluated_at": "2026-09-08T01:00:00Z",
        }
        assert await state.apply_evaluation(
            THREAD_ID,
            expected_revision=first["revision"],
            evaluation=cast(Any, evaluation),
        )
        allowed = await state.prepare_continuation(
            THREAD_ID,
            evaluation=cast(Any, evaluation),
            expected_revision=first["revision"],
        )
        assert allowed.continue_run is True

        evaluation2 = {
            **evaluation,
            "evaluated_at": "2026-09-08T01:01:00Z",
        }
        assert await state.apply_evaluation(
            THREAD_ID,
            expected_revision=first["revision"],
            evaluation=cast(Any, evaluation2),
        )
        capped = await state.prepare_continuation(
            THREAD_ID,
            evaluation=cast(Any, evaluation2),
            expected_revision=first["revision"],
        )
        assert capped == GoalContinuationDecision(
            False, "max_continuations_reached"
        )

        replacement = await state.set_goal(
            THREAD_ID,
            objective="替换目标",
            expected_revision=first["revision"],
        )
        assert not await state.apply_evaluation(
            THREAD_ID,
            expected_revision=first["revision"],
            evaluation=cast(Any, evaluation2),
        )
        current = await state.get_goal(THREAD_ID)
        assert current is not None
        assert current["revision"] == replacement["revision"]

        budget_eval = {
            **evaluation,
            "evaluated_at": "2026-09-08T01:02:00Z",
        }
        assert await state.apply_evaluation(
            THREAD_ID,
            expected_revision=replacement["revision"],
            evaluation=cast(Any, budget_eval),
        )
        budget = await state.prepare_continuation(
            THREAD_ID,
            evaluation=cast(Any, budget_eval),
            expected_revision=replacement["revision"],
            budget_stop_reason="token_capped",
        )
        assert budget.stop_reason == "token_capped"

        stop_race = await state.set_goal(
            THREAD_ID,
            objective="停止必须赢得续跑竞争",
            expected_revision=replacement["revision"],
        )
        assert await state.apply_evaluation(
            THREAD_ID,
            expected_revision=stop_race["revision"],
            evaluation=cast(Any, evaluation),
        )
        stopped = await state.stop_goal(THREAD_ID)
        assert stopped is not None
        rejected = await state.prepare_continuation(
            THREAD_ID,
            evaluation=cast(Any, evaluation),
            expected_revision=stop_race["revision"],
        )
        assert rejected == GoalContinuationDecision(False, "goal_changed")
        current = await state.get_goal(THREAD_ID)
        assert current is not None
        assert current["status"] == "stopped"
        assert current["stop_reason"] == "user_stopped"

    asyncio.run(scenario())


def test_near_duplicate_evidence_triggers_no_progress_fuse() -> None:
    async def scenario() -> None:
        state = GoalStateService(cast(Any, _ThreadRepository()), InMemorySaver())
        goal = await state.set_goal(
            THREAD_ID,
            objective="避免重复无效工作",
            max_continuations=6,
        )
        summaries = (
            "扫描源码后仍未找到目标定义，下一步需要继续搜索。",
            "扫描源码后，仍未找到目标定义；下一步需要继续搜索",
            "扫描源码后仍未找到目标定义，下一步仍需继续搜索。",
        )
        decision = None
        for index, summary in enumerate(summaries):
            evaluation = {
                "satisfied": False,
                "blocker": "goal_not_met_yet",
                "reason": "没有新增证据",
                "evidence_summary": summary,
                "evaluated_at": f"2026-09-08T01:0{index}:00Z",
            }
            assert await state.apply_evaluation(
                THREAD_ID,
                expected_revision=goal["revision"],
                evaluation=cast(Any, evaluation),
            )
            decision = await state.prepare_continuation(
                THREAD_ID,
                evaluation=cast(Any, evaluation),
                expected_revision=goal["revision"],
            )

        assert decision == GoalContinuationDecision(False, "no_progress")
        stopped = await state.get_goal(THREAD_ID)
        assert stopped is not None
        assert stopped["no_progress_count"] == 2

    asyncio.run(scenario())


def test_failed_run_records_run_failed_without_calling_evaluator_model() -> None:
    async def scenario() -> None:
        state = GoalStateService(
            cast(Any, _ThreadRepository()),
            InMemorySaver(),
        )
        await state.set_goal(THREAD_ID, objective="不能误判完成")
        model = _BindableModel(
            responses=[AIMessage(content='{"satisfied":true,"blocker":"none"}')]
        )
        service = GoalEvaluationService(
            cast(Any, _ThreadRepository()),
            state,
            GoalCompletionEvaluator(model),
        )

        evaluation = await service.evaluate_run(
            thread_id=THREAD_ID,
            run_id="failed-run",
            terminal_event="run_error",
        )
        goal = await state.get_goal(THREAD_ID)

        assert evaluation is not None
        assert evaluation["satisfied"] is False
        assert evaluation["blocker"] == "run_failed"
        assert evaluation["evidence_summary"] == (
            "当前 Run 没有可用于证明 Goal 已完成的用户可见证据。"
        )
        assert model.histories == []
        assert goal is not None
        assert goal["last_evaluation"] == evaluation

    asyncio.run(scenario())


def test_goal_read_repairs_legacy_empty_evidence_summary() -> None:
    async def scenario() -> None:
        state = GoalStateService(cast(Any, _ThreadRepository()), InMemorySaver())
        goal = await state.set_goal(THREAD_ID, objective="保留停止后的目标")
        legacy_evaluation = {
            "satisfied": False,
            "blocker": "run_failed",
            "reason": "当前 Run 已停止",
            "evidence_summary": "",
            "evaluated_at": "2026-09-08T01:00:00Z",
        }
        assert await state.apply_evaluation(
            THREAD_ID,
            expected_revision=goal["revision"],
            evaluation=cast(Any, legacy_evaluation),
        )

        restored = await state.get_goal(THREAD_ID)

        assert restored is not None
        assert restored["objective"] == "保留停止后的目标"
        assert restored["last_evaluation"]["evidence_summary"] == (
            "当前 Run 没有可用于证明 Goal 已完成的用户可见证据。"
        )

    asyncio.run(scenario())


def test_goal_not_met_runs_hidden_round_then_satisfied_without_fake_user_history(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        calls: list[tuple[str, bool]] = []

        class _TwoRoundStream:
            def create_run_budget_tracker(self, run_id: str) -> RunBudgetTracker:
                tracker = RunBudgetTracker()
                tracker.pin_run(run_id)
                return tracker

            async def astream_run_events(
                self,
                message: str,
                thread_id: str,
                run_id: str,
                _attachments: tuple = (),
                _human_response: object | None = None,
                *,
                run_budget_tracker: RunBudgetTracker | None = None,
                internal_continuation: bool = False,
            ):
                assert run_budget_tracker is not None
                calls.append((message, internal_continuation))
                round_number = len(calls)
                yield RunEvent(
                    event="run_started",
                    run_id=run_id,
                    thread_id=thread_id,
                    sequence=1,
                    message_id=None,
                    payload={},
                )
                yield RunEvent(
                    event="ai_delta",
                    run_id=run_id,
                    thread_id=thread_id,
                    sequence=2,
                    message_id=(
                        f"88888888-8888-4888-8888-88888888888{round_number}"
                    ),
                    payload={"text": f"第 {round_number} 轮结果"},
                )
                yield RunEvent(
                    event="run_completed",
                    run_id=run_id,
                    thread_id=thread_id,
                    sequence=3,
                    message_id=None,
                    payload={"finish_reason": "stop"},
                )

        with open_sqlite_conversation_repository(
            tmp_path / "hidden-continuation.sqlite"
        ) as repository:
            # 先形成一个空闲 Thread，Goal API 不需要伪造尚不存在的业务对象。
            repository.create_run(
                thread_id=THREAD_ID,
                run_id="99999999-9999-4999-8999-999999999999",
                user_message_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                user_message="初始化",
            )
            repository.interrupt_run(
                thread_id=THREAD_ID,
                run_id="99999999-9999-4999-8999-999999999999",
                error_code="seed",
            )
            state = GoalStateService(cast(Any, repository), InMemorySaver())
            await state.set_goal(THREAD_ID, objective="完成两轮工作")
            evaluator_model = _BindableModel(
                responses=[
                    AIMessage(
                        content=(
                            '{"satisfied":false,"blocker":"goal_not_met_yet",'
                            '"reason":"还差第二步","evidence_summary":"完成第一步"}'
                        )
                    ),
                    AIMessage(
                        content=(
                            '{"satisfied":true,"blocker":"none",'
                            '"reason":"两步均完成","evidence_summary":"完成全部步骤"}'
                        )
                    ),
                ]
            )
            evaluation = GoalEvaluationService(
                cast(Any, repository),
                state,
                GoalCompletionEvaluator(evaluator_model),
            )
            manager = RunExecutionManager(
                cast(Any, _TwoRoundStream()),
                repository,
                goal_evaluation_service=evaluation,
            )
            started = await manager.start_run(
                "开始目标",
                THREAD_ID,
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            )
            events = [event async for event in started.events]
            history = repository.list_history(
                THREAD_ID,
                limit=20,
                before_sequence=None,
            )

        assert [event.event for event in events] == [
            "run_started",
            "ai_delta",
            "goal_status",
            "goal_status",
            "ai_delta",
            "goal_status",
            "goal_status",
            "run_completed",
        ]
        assert [event.sequence for event in events] == list(range(1, 9))
        assert calls[0] == ("开始目标", False)
        assert calls[1][1] is True
        assert calls[1][0].startswith("[Goal continuation]")
        run_items = [item for item in history.items if item.run_id == started.run_id]
        assert [item.kind for item in run_items] == ["message", "message", "message"]
        assert [item.role for item in run_items] == ["user", "assistant", "assistant"]
        completed = await state.get_goal(THREAD_ID)
        assert completed is not None
        assert completed["status"] == "completed"

    asyncio.run(scenario())


def test_clarification_reply_resumes_paused_goal_and_marks_completed(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        calls: list[tuple[str, object | None, bool]] = []

        class _ClarificationStream:
            def create_run_budget_tracker(self, run_id: str) -> RunBudgetTracker:
                tracker = RunBudgetTracker()
                tracker.pin_run(run_id)
                return tracker

            async def astream_run_events(
                self,
                message: str,
                thread_id: str,
                run_id: str,
                _attachments: tuple = (),
                human_response: object | None = None,
                *,
                run_budget_tracker: RunBudgetTracker | None = None,
                internal_continuation: bool = False,
            ):
                assert run_budget_tracker is not None
                calls.append((message, human_response, internal_continuation))
                call_number = len(calls)
                assistant_text = (
                    "请提供出发城市、目的地、日期和预算。"
                    if call_number == 1
                    else "北京三日游行程与 3000 元预算规划已全部完成。"
                )
                yield RunEvent(
                    event="run_started",
                    run_id=run_id,
                    thread_id=thread_id,
                    sequence=1,
                    message_id=None,
                    payload={},
                )
                yield RunEvent(
                    event="ai_delta",
                    run_id=run_id,
                    thread_id=thread_id,
                    sequence=2,
                    message_id=(
                        f"cccccccc-cccc-4ccc-8ccc-ccccccccccc{call_number}"
                    ),
                    payload={"text": assistant_text},
                )
                yield RunEvent(
                    event="run_completed",
                    run_id=run_id,
                    thread_id=thread_id,
                    sequence=3,
                    message_id=None,
                    payload={
                        "finish_reason": (
                            "clarification_requested"
                            if call_number == 1
                            else "stop"
                        )
                    },
                )

        with open_sqlite_conversation_repository(
            tmp_path / "clarification-resume.sqlite"
        ) as repository:
            repository.create_run(
                thread_id=THREAD_ID,
                run_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                user_message_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
                user_message="初始化",
            )
            repository.interrupt_run(
                thread_id=THREAD_ID,
                run_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                error_code="seed",
            )
            state = GoalStateService(cast(Any, repository), InMemorySaver())
            await state.set_goal(THREAD_ID, objective="制定北京三日游计划")
            evaluator = _BindableModel(
                responses=[
                    AIMessage(
                        content=(
                            '{"satisfied":false,"blocker":"needs_user_input",'
                            '"reason":"等待行程参数",'
                            '"evidence_summary":"已请求日期和预算"}'
                        )
                    ),
                    AIMessage(
                        content=(
                            '{"satisfied":true,"blocker":"none",'
                            '"reason":"规划已经完整输出",'
                            '"evidence_summary":"行程和预算均已完成"}'
                        )
                    ),
                ]
            )
            manager = RunExecutionManager(
                cast(Any, _ClarificationStream()),
                repository,
                goal_evaluation_service=GoalEvaluationService(
                    cast(Any, repository),
                    state,
                    GoalCompletionEvaluator(evaluator),
                ),
            )

            first = await manager.start_run(
                "开始制定",
                THREAD_ID,
                "ffffffff-ffff-4fff-8fff-ffffffffffff",
            )
            _ = [event async for event in first.events]
            paused = await state.get_goal(THREAD_ID)
            assert paused is not None
            assert paused["status"] == "paused"
            assert paused["stop_reason"] == "needs_user_input"

            human_response = {
                "version": 1,
                "kind": "human_input_response",
                "request_id": "clarification:travel",
                "response_kind": "text",
                "value": "北京出发，北京三日游，预算 3000 元",
            }
            second = await manager.start_run(
                "北京出发，北京三日游，预算 3000 元",
                THREAD_ID,
                "11111111-1111-4111-8111-111111111111",
                human_input_response=human_response,
            )
            second_events = [event async for event in second.events]

        assert [event.event for event in second_events] == [
            "run_started",
            "goal_status",
            "ai_delta",
            "goal_status",
            "goal_status",
            "run_completed",
        ]
        assert calls[1] == (
            "北京出发，北京三日游，预算 3000 元",
            human_response,
            False,
        )
        completed = await state.get_goal(THREAD_ID)
        assert completed is not None
        assert completed["status"] == "completed"

    asyncio.run(scenario())


def test_user_cancel_updates_goal_before_run_terminal_event(tmp_path: Path) -> None:
    async def scenario() -> None:
        ready = asyncio.Event()

        class _BlockingGoalStream:
            def create_run_budget_tracker(self, run_id: str) -> RunBudgetTracker:
                tracker = RunBudgetTracker()
                tracker.pin_run(run_id)
                return tracker

            async def astream_run_events(
                self,
                _message: str,
                thread_id: str,
                run_id: str,
                _attachments: tuple = (),
                _human_response: object | None = None,
                *,
                run_budget_tracker: RunBudgetTracker | None = None,
                internal_continuation: bool = False,
            ):
                del internal_continuation
                assert run_budget_tracker is not None
                ready.set()
                yield RunEvent(
                    event="run_started",
                    run_id=run_id,
                    thread_id=thread_id,
                    sequence=1,
                    message_id=None,
                    payload={},
                )
                await asyncio.Event().wait()

        with open_sqlite_conversation_repository(
            tmp_path / "goal-cancel-order.sqlite"
        ) as repository:
            state = GoalStateService(cast(Any, repository), InMemorySaver())
            await state.set_goal(THREAD_ID, objective="取消后暂停目标")
            evaluation = GoalEvaluationService(
                cast(Any, repository),
                state,
                GoalCompletionEvaluator(_BindableModel(responses=[])),
            )
            manager = RunExecutionManager(
                cast(Any, _BlockingGoalStream()),
                repository,
                goal_evaluation_service=evaluation,
            )
            started = await manager.start_run(
                "开始后取消",
                THREAD_ID,
                "abababab-abab-4bab-8bab-abababababab",
            )
            await ready.wait()
            assert (
                await manager.cancel_run(THREAD_ID, started.run_id)
                is CancelOutcome.cancelled
            )
            events = [event async for event in started.events]
            current = await state.get_goal(THREAD_ID)

        assert [event.event for event in events] == [
            "run_started",
            "goal_status",
            "goal_status",
            "run_interrupted",
        ]
        assert current is not None
        assert current["status"] == "paused"
        assert current["stop_reason"] == "run_failed"

    asyncio.run(scenario())
