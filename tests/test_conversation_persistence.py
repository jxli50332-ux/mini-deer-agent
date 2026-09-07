"""验证产品历史业务库、分页、恢复和 HTTP 查询完整链路。"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
import sqlite3
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from langgraph.graph.state import CompiledStateGraph

from mini_deer_agent.application import (
    ActiveRunConflictError,
    RunEventSequenceError,
    RunExecutionManager,
    RunStreamService,
)
from mini_deer_agent.core import Settings
from mini_deer_agent.domain import MessageHistoryItem, validate_text_attachment_batch
from mini_deer_agent.persistence import open_sqlite_conversation_repository
from mini_deer_agent.server import create_app
from mini_deer_agent.streaming import RunEvent


THREAD_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
ASSISTANT_ID = "44444444-4444-4444-8444-444444444444"
FINAL_ASSISTANT_ID = "55555555-5555-4555-8555-555555555555"


def test_user_message_and_text_attachments_are_persisted_atomically(
    tmp_path: Path,
) -> None:
    """附件内容跟随所属用户消息落库，历史查询公开完整附件内容供前端查看。"""
    database_path = tmp_path / "attachments.sqlite"
    attachments = validate_text_attachment_batch(
        [("brief.md", "代号：云杉"), ("facts.json", '{"year": 2026}')]
    )

    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="读取附件",
            attachments=attachments,
        )
        history = repository.list_history(
            THREAD_ID,
            limit=10,
            before_sequence=None,
        )

    assert len(history.items) == 1
    message = history.items[0]
    assert isinstance(message, MessageHistoryItem)
    assert [
        (item.filename, item.media_type, item.size_bytes, item.content)
        for item in message.attachments
    ] == [
        ("brief.md", "text/markdown", len("代号：云杉".encode("utf-8")), "代号：云杉"),
        ("facts.json", "application/json", len('{"year": 2026}'.encode("utf-8")), '{"year": 2026}'),
    ]

    with sqlite3.connect(database_path) as connection:
        stored = connection.execute(
            """
            SELECT filename, content
            FROM text_attachments
            WHERE message_id = ?
            ORDER BY position
            """,
            (MESSAGE_ID,),
        ).fetchall()
    assert stored == [("brief.md", "代号：云杉"), ("facts.json", '{"year": 2026}')]


def event(
    event_name: str,
    sequence: int,
    *,
    message_id: str | None = None,
    payload: dict[str, object],
) -> RunEvent:
    """构造仓储测试使用的稳定 RunEvent。"""
    return RunEvent(
        event=cast(Any, event_name),
        run_id=RUN_ID,
        thread_id=THREAD_ID,
        sequence=sequence,
        message_id=message_id,
        payload=payload,
    )


def test_sqlite_repository_materializes_runs_messages_tools_and_pages(
    tmp_path: Path,
) -> None:
    """一个完成 Run 应形成可分页且严格排序的产品时间线。"""
    database_path = tmp_path / "application.sqlite"
    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="查询北京天气",
        )
        repository.apply_run_event(
            event(
                "run_started",
                1,
                payload={"created_at": "2026-08-26T08:00:00+00:00"},
            )
        )
        repository.apply_run_event(
            event(
                "ai_delta",
                2,
                message_id=ASSISTANT_ID,
                payload={"text": "正在"},
            )
        )
        repository.apply_run_event(
            event(
                "ai_delta",
                3,
                message_id=ASSISTANT_ID,
                payload={"text": "查询"},
            )
        )
        repository.apply_run_event(
            event(
                "tool_call_delta",
                4,
                message_id=ASSISTANT_ID,
                payload={
                    "tool_call_id": "call-weather-1",
                    "name": "get_weather",
                    "arguments_delta": '{"city":',
                    "index": 0,
                },
            )
        )
        repository.apply_run_event(
            event(
                "tool_call_delta",
                5,
                message_id=ASSISTANT_ID,
                payload={
                    "tool_call_id": "call-weather-1",
                    "name": None,
                    "arguments_delta": '"北京"}',
                    "index": 0,
                },
            )
        )
        repository.apply_run_event(
            event(
                "tool_result",
                6,
                payload={
                    "tool_call_id": "call-weather-1",
                    "name": "get_weather",
                    "content": "北京 24°C",
                },
            )
        )
        repository.apply_run_event(
            event(
                "ai_delta",
                7,
                message_id=FINAL_ASSISTANT_ID,
                payload={"text": "北京当前 24°C。"},
            )
        )
        repository.apply_run_event(
            event(
                "run_completed",
                8,
                payload={"finish_reason": "stop"},
            )
        )

        thread = repository.get_thread(THREAD_ID)
        assert thread is not None
        assert thread.status == "idle"
        assert thread.title == "查询北京天气"
        runs = repository.list_runs(THREAD_ID, limit=10)
        assert [(run.run_id, run.status) for run in runs] == [
            (RUN_ID, "completed")
        ]

        newest_page = repository.list_history(
            THREAD_ID,
            limit=2,
            before_sequence=None,
        )
        assert [item.thread_sequence for item in newest_page.items] == [3, 4]
        assert newest_page.has_more is True
        assert newest_page.next_before_sequence == 3
        tool = newest_page.items[0]
        assert tool.kind == "tool"
        assert tool.input == '{"city":"北京"}'
        assert tool.result == "北京 24°C"

        older_page = repository.list_history(
            THREAD_ID,
            limit=2,
            before_sequence=newest_page.next_before_sequence,
        )
        assert [item.thread_sequence for item in older_page.items] == [1, 2]
        assert older_page.has_more is False
        assert older_page.items[1].kind == "message"
        assert older_page.items[1].content == "正在查询"

    with sqlite3.connect(database_path) as connection:
        query_plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT item_id FROM timeline_items
            WHERE thread_id = ? AND thread_sequence < ?
            ORDER BY thread_sequence DESC LIMIT ?
            """,
            (THREAD_ID, 100, 20),
        ).fetchall()
    assert any(
        "idx_timeline_items_thread_sequence" in str(row)
        for row in query_plan
    )


def test_reasoning_delta_is_persisted_and_restored_in_history(
    tmp_path: Path,
) -> None:
    """思考过程应持久化到消息 reasoning 字段，并在历史恢复时返回。"""
    database_path = tmp_path / "reasoning.sqlite"
    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="分析架构",
        )
        repository.apply_run_event(
            event(
                "run_started",
                1,
                payload={"created_at": "2026-08-30T08:00:00+00:00"},
            )
        )
        repository.apply_run_event(
            event(
                "reasoning_delta",
                2,
                message_id=ASSISTANT_ID,
                payload={"text": "先拆解"},
            )
        )
        repository.apply_run_event(
            event(
                "reasoning_delta",
                3,
                message_id=ASSISTANT_ID,
                payload={"text": "再综合"},
            )
        )
        repository.apply_run_event(
            event(
                "ai_delta",
                4,
                message_id=ASSISTANT_ID,
                payload={"text": "结论如下。"},
            )
        )
        repository.apply_run_event(
            event("run_completed", 5, payload={"finish_reason": "stop"})
        )

        page = repository.list_history(
            THREAD_ID,
            limit=10,
            before_sequence=None,
        )
        assistant = next(
            item
            for item in page.items
            if item.kind == "message" and item.role == "assistant"
        )
        assert assistant.reasoning == "先拆解再综合"
        assert assistant.content == "结论如下。"


def test_delete_thread_cascades_through_complete_business_history(
    tmp_path: Path,
) -> None:
    """删除 Thread 应由外键级联清除 Run、时间线、消息、工具与原始事件。"""
    database_path = tmp_path / "delete-thread.sqlite"
    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="删除完整历史",
        )
        for run_event in (
            event(
                "run_started",
                1,
                payload={"created_at": "2026-08-30T08:00:00+00:00"},
            ),
            event(
                "tool_call_delta",
                2,
                message_id=ASSISTANT_ID,
                payload={
                    "tool_call_id": "call-delete-1",
                    "name": "example_tool",
                    "arguments_delta": "{}",
                    "index": 0,
                },
            ),
            event(
                "tool_result",
                3,
                payload={
                    "tool_call_id": "call-delete-1",
                    "name": "example_tool",
                    "content": "done",
                },
            ),
            event(
                "run_completed",
                4,
                payload={"finish_reason": "stop"},
            ),
        ):
            assert repository.apply_run_event(run_event)

        assert repository.delete_thread(THREAD_ID) is True
        assert repository.get_thread(THREAD_ID) is None

    with sqlite3.connect(database_path) as connection:
        for table in (
            "threads",
            "runs",
            "timeline_items",
            "messages",
            "text_attachments",
            "tool_executions",
            "run_events",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (
                0,
            )


def test_sqlite_repository_persists_and_pages_original_run_events(
    tmp_path: Path,
) -> None:
    """原始 RunEvent 应按 Run 内 sequence 持久化，并在重开数据库后仍可游标查询。"""
    database_path = tmp_path / "run-events.sqlite"
    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="保存原始事件",
        )
        source_events = (
            event(
                "run_started",
                1,
                payload={"created_at": "2026-08-26T08:00:00+00:00"},
            ),
            event(
                "ai_delta",
                2,
                message_id=ASSISTANT_ID,
                payload={"text": "第一段"},
            ),
            event(
                "run_completed",
                3,
                payload={"finish_reason": "stop"},
            ),
        )
        for run_event in source_events:
            assert repository.apply_run_event(run_event)

        first_page = repository.list_run_events(
            THREAD_ID,
            RUN_ID,
            after_sequence=0,
            limit=2,
        )
        second_page = repository.list_run_events(
            THREAD_ID,
            RUN_ID,
            after_sequence=2,
            limit=2,
        )

        assert [item.sequence for item in first_page] == [1, 2]
        assert [item.sequence for item in second_page] == [3]
        assert first_page[1].event == "ai_delta"
        assert first_page[1].message_id == ASSISTANT_ID
        assert first_page[1].payload == {"text": "第一段"}
        assert all(item.version == "1" for item in (*first_page, *second_page))
        assert all(
            item.created_at.endswith("+00:00")
            for item in (*first_page, *second_page)
        )

    with open_sqlite_conversation_repository(database_path) as repository:
        restored = repository.list_run_events(
            THREAD_ID,
            RUN_ID,
            after_sequence=0,
            limit=100,
        )

    assert [item.sequence for item in restored] == [1, 2, 3]
    assert [item.event for item in restored] == [
        "run_started",
        "ai_delta",
        "run_completed",
    ]

    with sqlite3.connect(database_path) as connection:
        query_plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT version, event, payload_json FROM run_events
            WHERE thread_id = ? AND run_id = ? AND sequence > ?
            ORDER BY sequence ASC LIMIT ?
            """,
            (THREAD_ID, RUN_ID, 0, 200),
        ).fetchall()
    assert any(
        "idx_run_events_thread_run_sequence" in str(row)
        for row in query_plan
    )


def test_search_result_and_citation_markdown_survive_repository_restart(
    tmp_path: Path,
) -> None:
    """搜索原始来源和回答中的引用格式应沿既有历史链共同跨进程恢复。"""
    database_path = tmp_path / "search-citations.sqlite"
    search_result = (
        '{"query":"Mini Deer","total_results":1,"results":['
        '{"title":"示例研究","url":"https://example.com/research",'
        '"content":"结构化搜索摘要"}]}'
    )
    citation_answer = (
        "搜索结论 [citation:示例研究](https://example.com/research)"
    )
    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="查询并引用来源",
        )
        for run_event in (
            event(
                "run_started",
                1,
                payload={"created_at": "2026-08-30T08:00:00+00:00"},
            ),
            event(
                "tool_call_delta",
                2,
                message_id=ASSISTANT_ID,
                payload={
                    "tool_call_id": "call-search-1",
                    "name": "web_search",
                    "arguments_delta": '{"query":"Mini Deer"}',
                    "index": 0,
                },
            ),
            event(
                "tool_result",
                3,
                payload={
                    "tool_call_id": "call-search-1",
                    "name": "web_search",
                    "content": search_result,
                },
            ),
            event(
                "ai_delta",
                4,
                message_id=FINAL_ASSISTANT_ID,
                payload={"text": citation_answer},
            ),
            event(
                "run_completed",
                5,
                payload={"finish_reason": "stop"},
            ),
        ):
            assert repository.apply_run_event(run_event)

    with open_sqlite_conversation_repository(database_path) as repository:
        restored = repository.list_history(
            THREAD_ID,
            limit=100,
            before_sequence=None,
        )

    restored_tool = next(item for item in restored.items if item.kind == "tool")
    restored_answer = next(
        item
        for item in restored.items
        if item.kind == "message" and item.role == "assistant"
    )
    assert restored_tool.name == "web_search"
    assert restored_tool.result == search_result
    assert restored_answer.content == citation_answer


def test_run_event_sequence_gap_rolls_back_event_and_product_projection(
    tmp_path: Path,
) -> None:
    """重复、倒序或跳号事件必须整体失败，不能只更新消息投影。"""
    with open_sqlite_conversation_repository(
        tmp_path / "run-event-sequence.sqlite"
    ) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="校验序号",
        )
        assert repository.apply_run_event(
            event(
                "run_started",
                1,
                payload={"created_at": "2026-08-26T08:00:00+00:00"},
            )
        )

        with pytest.raises(RunEventSequenceError):
            repository.apply_run_event(
                event(
                    "ai_delta",
                    3,
                    message_id=ASSISTANT_ID,
                    payload={"text": "不应写入"},
                )
            )

        stored = repository.list_run_events(
            THREAD_ID,
            RUN_ID,
            after_sequence=0,
            limit=100,
        )
        history = repository.list_history(
            THREAD_ID,
            limit=100,
            before_sequence=None,
        )

    assert [item.sequence for item in stored] == [1]
    assert [item.role for item in history.items if item.kind == "message"] == [
        "user"
    ]


def test_repository_lists_recent_threads_with_stable_order_and_limit(
    tmp_path: Path,
) -> None:
    """最近 Thread 查询必须按活动时间和 ID 稳定倒序，并应用数量上限。"""
    database_path = tmp_path / "thread-list.sqlite"
    thread_ids = (
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )
    with open_sqlite_conversation_repository(database_path) as repository:
        for index, thread_id in enumerate(thread_ids, start=1):
            run_id = f"{index}0000000-0000-4000-8000-000000000001"
            message_id = f"{index}0000000-0000-4000-8000-000000000002"
            repository.create_run(
                thread_id=thread_id,
                run_id=run_id,
                user_message_id=message_id,
                user_message=f"Thread {index}",
            )
            repository.interrupt_run(
                thread_id=thread_id,
                run_id=run_id,
                error_code="test_finished",
            )

    # 移除 v2/v3/v4 痕迹来模拟已有 v1 数据库，重开时必须保留数据并自动升级。
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX idx_threads_recent")
        connection.execute("DROP TABLE run_events")
        connection.execute("ALTER TABLE threads DROP COLUMN title")
        connection.execute(
            "DELETE FROM schema_migrations WHERE version IN (2, 3, 4)"
        )
        # 固定时间使测试不依赖机器时钟，并验证相同时间下的 ID 次级排序。
        connection.execute(
            "UPDATE threads SET updated_at = ? WHERE thread_id = ?",
            ("2026-08-25T00:00:00+00:00", thread_ids[0]),
        )
        connection.execute(
            "UPDATE threads SET updated_at = ? WHERE thread_id IN (?, ?)",
            (
                "2026-08-26T00:00:00+00:00",
                thread_ids[1],
                thread_ids[2],
            ),
        )

    with open_sqlite_conversation_repository(database_path) as repository:
        recent = repository.list_threads(limit=2)

    assert [thread.thread_id for thread in recent] == [
        thread_ids[2],
        thread_ids[1],
    ]
    assert [thread.title for thread in recent] == [None, None]

    with sqlite3.connect(database_path) as connection:
        migration_versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        query_plan = connection.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT thread_id FROM threads
            ORDER BY updated_at DESC, thread_id DESC
            LIMIT ?
            """,
            (20,),
        ).fetchall()
    assert migration_versions == [
        (1,),
        (2,),
        (3,),
        (4,),
        (5,),
        (6,),
        (7,),
        (8,),
        (9,),
        (10,),
        (11,),
    ]
    assert any("idx_threads_recent" in str(row) for row in query_plan)


def test_thread_title_is_generated_once_and_manual_rename_is_persistent(
    tmp_path: Path,
) -> None:
    """首条用户消息生成标题；手动改名后，后续 Run 不能把它覆盖。"""
    database_path = tmp_path / "thread-title.sqlite"
    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="  查询\n北京   明天天气  ",
        )
        assert repository.get_thread(THREAD_ID).title == "查询 北京 明天天气"  # type: ignore[union-attr]
        repository.interrupt_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            error_code="test_finished",
        )

        renamed = repository.update_thread_title(THREAD_ID, "北京出行计划")
        assert renamed is not None
        assert renamed.title == "北京出行计划"

        repository.create_run(
            thread_id=THREAD_ID,
            run_id="66666666-6666-4666-8666-666666666666",
            user_message_id="77777777-7777-4777-8777-777777777777",
            user_message="这条后续消息不能成为新标题",
        )
        assert repository.get_thread(THREAD_ID).title == "北京出行计划"  # type: ignore[union-attr]

    with open_sqlite_conversation_repository(database_path) as repository:
        restored = repository.get_thread(THREAD_ID)
        assert restored is not None
        assert restored.title == "北京出行计划"


def test_repository_rejects_parallel_run_and_recovers_after_restart(
    tmp_path: Path,
) -> None:
    """活动 Run 必须互斥，异常退出后则标记 interrupted 并允许后续恢复。"""
    database_path = tmp_path / "application.sqlite"
    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="第一轮",
        )
        with pytest.raises(ActiveRunConflictError):
            repository.create_run(
                thread_id=THREAD_ID,
                run_id="66666666-6666-4666-8666-666666666666",
                user_message_id="77777777-7777-4777-8777-777777777777",
                user_message="并发消息",
            )

        repository.interrupt_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            error_code="stream_interrupted",
        )
        interrupted = repository.list_runs(THREAD_ID, limit=1)[0]
        assert interrupted.status == "interrupted"
        assert interrupted.error_code == "stream_interrupted"

        # 再创建一个未终止 Run，模拟进程在生成期间直接退出。
        repository.create_run(
            thread_id=THREAD_ID,
            run_id="66666666-6666-4666-8666-666666666666",
            user_message_id="77777777-7777-4777-8777-777777777777",
            user_message="等待重启恢复",
        )

    with open_sqlite_conversation_repository(database_path) as repository:
        recovered_run = repository.list_runs(THREAD_ID, limit=1)[0]
        assert recovered_run.status == "interrupted"
        assert recovered_run.error_code == "server_restarted"
        thread = repository.get_thread(THREAD_ID)
        assert thread is not None
        assert thread.status == "idle"


def test_first_terminal_event_wins_cancel_completion_race(tmp_path: Path) -> None:
    """Repository 必须原子拒绝迟到终态，不能在 completed 与 interrupted 间翻转。"""
    with open_sqlite_conversation_repository(
        tmp_path / "terminal-race.sqlite"
    ) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="终态竞争",
        )
        assert repository.apply_run_event(
            event(
                "run_started",
                1,
                payload={"created_at": "2026-08-26T00:00:00+00:00"},
            )
        )
        assert repository.apply_run_event(
            event(
                "run_interrupted",
                2,
                payload={"reason": "user_cancelled"},
            )
        )
        assert not repository.apply_run_event(
            event(
                "run_completed",
                3,
                payload={"finish_reason": "stop"},
            )
        )

        record = repository.get_run(RUN_ID)
        assert record is not None
        assert record.status == "interrupted"
        assert record.finish_reason == "user_cancelled"


class StaticMessageGraph:
    """为 HTTP 集成测试产生一个稳定模型消息，不访问外部模型。"""

    def stream(
        self,
        _input_state: dict[str, object],
        *,
        config: dict[str, object] | None,
        stream_mode: str,
    ) -> Iterator[tuple[AIMessageChunk, dict[str, str]]]:
        """确认正式 messages 模式后返回单个模型增量。"""
        assert config is not None
        assert stream_mode == "messages"
        yield (
            AIMessageChunk(content="持久化回答", id=ASSISTANT_ID),
            {"langgraph_node": "model"},
        )

    async def astream(
        self,
        _input_state: dict[str, object],
        *,
        config: dict[str, object] | None,
        stream_mode: str,
    ) -> AsyncIterator[tuple[AIMessageChunk, dict[str, str]]]:
        """异步产生同一模型消息，供正式 Web Run 使用。"""
        assert config is not None
        assert stream_mode == "messages"
        yield (
            AIMessageChunk(content="持久化回答", id=ASSISTANT_ID),
            {"langgraph_node": "model"},
        )


def test_v1_stream_can_be_queried_after_run_completion(tmp_path: Path) -> None:
    """正式 POST SSE 完成后，Thread、Run 和 Message API 应读取同一业务事实。"""
    settings = Settings(
        checkpoint_database_path=tmp_path / "checkpoints.sqlite",
        application_database_path=tmp_path / "application.sqlite",
        _env_file=None,
    )

    def create_service(checkpointer: Any, repository: Any) -> RunStreamService:
        """注入静态图，同时保留真实业务仓储和应用服务。"""
        return RunStreamService(
            checkpointer,
            graph_factory=lambda _saver, _file_access: cast(
                CompiledStateGraph,
                StaticMessageGraph(),
            ),
        )

    application = create_app(
        settings_factory=lambda: settings,
        run_stream_service_factory=create_service,
    )
    with TestClient(application) as client:
        with client.stream(
            "POST",
            f"/api/v1/threads/{THREAD_ID}/runs/stream",
            json={"message_id": MESSAGE_ID, "message": "保存这一轮"},
        ) as response:
            assert response.status_code == 200
            _ = b"".join(response.iter_bytes())

        thread_response = client.get(f"/api/v1/threads/{THREAD_ID}")
        thread_list_response = client.get("/api/v1/threads?limit=20")
        runs_response = client.get(f"/api/v1/threads/{THREAD_ID}/runs")
        run_id = runs_response.json()[0]["run_id"]
        run_response = client.get(
            f"/api/v1/threads/{THREAD_ID}/runs/{run_id}"
        )
        events_response = client.get(
            f"/api/v1/threads/{THREAD_ID}/runs/{run_id}/events",
            params={"after_sequence": 1, "limit": 1},
        )
        missing_run_response = client.get(
            f"/api/v1/threads/{THREAD_ID}/runs/33333333-3333-4333-8333-333333333333"
        )
        mismatched_run_response = client.get(
            f"/api/v1/threads/44444444-4444-4444-8444-444444444444/runs/{run_id}"
        )
        mismatched_events_response = client.get(
            f"/api/v1/threads/44444444-4444-4444-8444-444444444444/runs/{run_id}/events"
        )
        history_response = client.get(
            f"/api/v1/threads/{THREAD_ID}/messages"
        )
        rename_response = client.patch(
            f"/api/v1/threads/{THREAD_ID}",
            json={"title": "  持久化   会话标题  "},
        )
        renamed_list_response = client.get("/api/v1/threads?limit=20")
        blank_title_response = client.patch(
            f"/api/v1/threads/{THREAD_ID}",
            json={"title": "   "},
        )
        extra_field_response = client.patch(
            f"/api/v1/threads/{THREAD_ID}",
            json={"title": "合法标题", "status": "error"},
        )
        missing_thread_response = client.patch(
            "/api/v1/threads/44444444-4444-4444-8444-444444444444",
            json={"title": "不存在"},
        )

    assert thread_response.json()["status"] == "idle"
    assert thread_response.json()["title"] == "保存这一轮"
    assert thread_list_response.status_code == 200
    assert thread_list_response.json() == [thread_response.json()]
    assert rename_response.status_code == 200
    assert rename_response.json()["title"] == "持久化 会话标题"
    assert renamed_list_response.json()[0]["title"] == "持久化 会话标题"
    assert blank_title_response.status_code == 422
    assert extra_field_response.status_code == 422
    assert missing_thread_response.status_code == 404
    assert missing_thread_response.json()["detail"]["code"] == "thread_not_found"
    assert runs_response.json()[0]["status"] == "completed"
    # 单条详情与列表必须来自同一 RunRecord 投影；缺失和跨 Thread 枚举统一隐藏。
    assert run_response.status_code == 200
    assert run_response.json() == runs_response.json()[0]
    assert events_response.status_code == 200
    assert [item["sequence"] for item in events_response.json()] == [2]
    assert events_response.json()[0]["event"] == "ai_delta"
    assert events_response.json()[0]["payload"] == {"text": "持久化回答"}
    assert missing_run_response.status_code == 404
    assert missing_run_response.json()["detail"]["code"] == "run_not_found"
    assert mismatched_run_response.status_code == 404
    assert mismatched_run_response.json()["detail"] == (
        missing_run_response.json()["detail"]
    )
    assert mismatched_events_response.status_code == 404
    assert mismatched_events_response.json()["detail"] == (
        missing_run_response.json()["detail"]
    )
    history = history_response.json()
    assert history["thread_exists"] is True
    assert [item["role"] for item in history["items"]] == [
        "user",
        "assistant",
    ]
    assert history["items"][1]["content"] == "持久化回答"

    # 新应用实例会重新打开同一个 SQLite；事件查询不依赖上一进程的内存队列。
    restarted_application = create_app(
        settings_factory=lambda: settings,
        run_stream_service_factory=create_service,
    )
    with TestClient(restarted_application) as restarted_client:
        restored_events_response = restarted_client.get(
            f"/api/v1/threads/{THREAD_ID}/runs/{run_id}/events"
        )
        restored_thread_response = restarted_client.get(
            f"/api/v1/threads/{THREAD_ID}"
        )

    assert restored_events_response.status_code == 200
    assert [item["sequence"] for item in restored_events_response.json()] == [
        1,
        2,
        3,
    ]
    assert [item["event"] for item in restored_events_response.json()] == [
        "run_started",
        "ai_delta",
        "run_completed",
    ]
    assert restored_thread_response.json()["title"] == "持久化 会话标题"


def test_closing_stream_marks_run_interrupted_and_releases_thread(
    tmp_path: Path,
) -> None:
    """浏览器停止消费 SSE 时不能让活动 Run 永久锁住当前 Thread。"""
    async def scenario() -> None:
        """关闭异步订阅，并等待同一个服务端取消状态机完成。"""

        class BlockingGraph:
            """在 run_started 后保持等待，确保测试主动触发断连。"""

            async def astream(
                self,
                _input_state: dict[str, object],
                *,
                config: dict[str, object] | None,
                stream_mode: str,
            ) -> AsyncIterator[tuple[AIMessageChunk, dict[str, str]]]:
                """等待到 Task 被取消，不产生模型消息。"""
                assert config is not None
                assert stream_mode == "messages"
                await asyncio.Event().wait()
                if False:
                    yield (
                        AIMessageChunk(content="不会到达"),
                        {"langgraph_node": "model"},
                    )

        with open_sqlite_conversation_repository(
            tmp_path / "application.sqlite"
        ) as repository:
            service = RunStreamService(
                cast(Any, object()),
                graph_factory=lambda _saver, _file_access: cast(
                    CompiledStateGraph,
                    BlockingGraph(),
                ),
            )
            manager = RunExecutionManager(service, repository)
            started = await manager.start_run(
                "准备停止",
                THREAD_ID,
                MESSAGE_ID,
            )
            assert (await anext(started.events)).event == "run_started"
            await started.events.aclose()

            run = repository.list_runs(THREAD_ID, limit=1)[0]
            thread = repository.get_thread(THREAD_ID)
            assert run.status == "interrupted"
            assert run.finish_reason == "client_disconnected"
            assert run.error_code is None
            assert thread is not None
            assert thread.status == "idle"

    asyncio.run(scenario())
