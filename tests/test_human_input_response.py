"""验证结构化澄清回答从 HTTP 边界到历史与 checkpoint 的稳定链路。"""

from pathlib import Path

from mini_deer_agent.application.run_stream import _human_message
from mini_deer_agent.domain import MessageHistoryItem
from mini_deer_agent.persistence import open_sqlite_conversation_repository
from mini_deer_agent.server.schemas.runs import RunStreamRequest


THREAD_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
RESPONSE = {
    "version": 1,
    "kind": "human_input_response",
    "request_id": "clarification:call-1",
    "response_kind": "option",
    "option_id": "option-1",
    "value": "Markdown",
}


def test_run_request_validates_versioned_human_input_response() -> None:
    """HTTP 请求只接收可按 request_id 精确关联的 v1 文本或选项回答。"""
    request = RunStreamRequest.model_validate(
        {
            "message_id": MESSAGE_ID,
            "message": "我选择 Markdown",
            "human_input_response": RESPONSE,
        }
    )

    assert request.to_domain_human_input_response() == RESPONSE


def test_human_input_response_survives_repository_restart(tmp_path: Path) -> None:
    """隐藏回答必须在重开业务库后仍携带完整响应元数据。"""
    database_path = tmp_path / "human-input.sqlite"
    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="我选择 Markdown",
            human_input_response=RESPONSE,
        )

    with open_sqlite_conversation_repository(database_path) as repository:
        history = repository.list_history(
            THREAD_ID,
            limit=10,
            before_sequence=None,
        )

    message = history.items[0]
    assert isinstance(message, MessageHistoryItem)
    assert message.hidden_from_ui is True
    assert message.human_input_response == RESPONSE


def test_human_input_response_reaches_langgraph_additional_kwargs() -> None:
    """模型正文保持可读，同时 checkpoint 消息携带机器可判定的精确关联。"""
    message = _human_message(
        "针对澄清问题，我选择 Markdown",
        (),
        RESPONSE,
    )

    assert message.content == "针对澄清问题，我选择 Markdown"
    assert message.additional_kwargs == {
        "hide_from_ui": True,
        "human_input_response": RESPONSE,
    }
