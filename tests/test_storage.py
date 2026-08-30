"""验证 SQLite Checkpointer 的连接生命周期和跨实例状态恢复。"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Self

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.persistence import open_sqlite_checkpointer


class BindableFakeModel(FakeMessagesListChatModel):
    """支持工具绑定并返回预设消息，避免持久化测试访问 DeepSeek。"""

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Self:
        """接受工具契约但不改变预设响应行为。"""
        return self


def test_sqlite_checkpointer_restores_thread_after_reopen(tmp_path: Path) -> None:
    """关闭并重开数据库和 graph 后，相同 thread_id 应恢复原消息。"""
    database_path = tmp_path / "nested" / "checkpoints.sqlite"
    config = {"configurable": {"thread_id": "sqlite-thread"}}

    first_model = BindableFakeModel(
        responses=[AIMessage(content="第一轮已保存。")]
    )
    with open_sqlite_checkpointer(database_path) as checkpointer:
        first_graph = build_agent_graph(first_model, checkpointer=checkpointer)
        first_graph.invoke(
            {"messages": [HumanMessage(content="第一轮消息。")]},
            config,
        )

    # 离开 with 后原连接已关闭；重新打开同一文件模拟应用重启后的恢复。
    assert database_path.is_file()
    second_model = BindableFakeModel(
        responses=[AIMessage(content="第二轮已恢复。")]
    )
    with open_sqlite_checkpointer(database_path) as checkpointer:
        second_graph = build_agent_graph(second_model, checkpointer=checkpointer)
        second_result = second_graph.invoke(
            {"messages": [HumanMessage(content="第二轮消息。")]},
            config,
        )
        snapshot = second_graph.get_state(config)

    expected_texts = [
        "第一轮消息。",
        "第一轮已保存。",
        "第二轮消息。",
        "第二轮已恢复。",
    ]
    assert [message.text for message in second_result["messages"]] == expected_texts
    assert [message.text for message in snapshot.values["messages"]] == expected_texts
