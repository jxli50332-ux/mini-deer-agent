"""验证应用 Run 身份进入 LangGraph 配置而不暴露给模型参数。"""

import asyncio
from typing import Any, cast
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from mini_deer_agent.application import run_stream as run_stream_module
from mini_deer_agent.application.run_stream import (
    RunStreamService,
    build_default_agent_graph,
)
from mini_deer_agent.llms import ModelProfile, ModelSnapshot


def test_default_graph_projects_the_frozen_model_id_into_prompt_context(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    graph = object()

    def capture_graph(**kwargs):
        captured.update(kwargs)
        return graph

    monkeypatch.setattr(run_stream_module, "build_agent_graph", capture_graph)
    snapshot = ModelSnapshot(
        "glm-flash",
        "profile-revision",
        2,
        FakeMessagesListChatModel(responses=[AIMessage(content="OK")]),
        ModelProfile(
            name="glm-flash",
            display_name="GLM Flash",
            provider="openai-compatible",
            model="glm-4.7-flash",
            api_key_env="GLM_API_KEY",
        ),
    )

    result = build_default_agent_graph(
        cast(BaseCheckpointSaver, object()),
        model_snapshot=snapshot,
    )

    assert result is graph
    assert cast(Any, captured["prompt_context"]).current_model_name == (
        "glm-4.7-flash"
    )


def test_async_product_run_projects_run_id_into_tool_runtime_config(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def capture(
        graph: object,
        messages: list[object],
        config: dict[str, object],
    ):
        captured.update(graph=graph, messages=messages, config=config)
        if False:
            yield None

    graph = object()
    monkeypatch.setattr(run_stream_module, "astream_agent_messages", capture)
    service = RunStreamService(
        cast(BaseCheckpointSaver, object()),
        graph_factory=lambda checkpointer, file_access: graph,
    )
    run_id = str(uuid4())

    async def collect() -> None:
        events = service.astream_messages(
            "hello",
            "thread-a",
            run_id=run_id,
        )
        assert [event async for event in events] == []

    asyncio.run(collect())

    assert captured["graph"] is graph
    assert cast(Any, captured["config"])["configurable"] == {
        "thread_id": "thread-a",
        "run_id": run_id,
    }


def test_goal_continuation_enters_checkpoint_as_hidden_runtime_message(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def capture(
        graph: object,
        messages: list[object],
        config: dict[str, object],
    ):
        captured.update(messages=messages, config=config)
        if False:
            yield None

    monkeypatch.setattr(run_stream_module, "astream_agent_messages", capture)
    service = RunStreamService(
        cast(BaseCheckpointSaver, object()),
        graph_factory=lambda checkpointer, file_access: object(),
    )

    async def collect() -> None:
        assert [
            event
            async for event in service.astream_messages(
                "[Goal continuation] 继续目标",
                "thread-goal",
                run_id="run-goal",
                internal_continuation=True,
            )
        ] == []

    asyncio.run(collect())
    message = cast(Any, captured["messages"])[0]
    assert message.text == "[Goal continuation] 继续目标"
    assert message.additional_kwargs == {
        "hide_from_ui": True,
        "kind": "goal_continuation",
    }
