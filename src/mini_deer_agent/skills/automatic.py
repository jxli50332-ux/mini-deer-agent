"""提供可审计的模型自主技能激活工具与消息留痕解析。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Annotated

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from pydantic import StringConstraints

from mini_deer_agent.skills.catalog import BuiltInSkillCatalog


SKILL_ACTIVATION_METADATA_KEY = "skill_activation"
SKILL_ACTIVATION_TOOL_NAME = "activate_skill"
type SkillName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]


def _activation_payload(
    *,
    name: str,
    status: str,
    message: str,
) -> str:
    """渲染前端通用工具卡和模型都能稳定读取的有界结果。"""
    return json.dumps(
        {
            "version": 1,
            "kind": "skill_activation",
            "status": status,
            "name": name,
            "message": message,
        },
        ensure_ascii=False,
        indent=2,
    )


def create_skill_activation_tool(catalog: BuiltInSkillCatalog) -> BaseTool:
    """构造绑定当前 Run 目录快照的自主激活工具。"""

    @tool(SKILL_ACTIVATION_TOOL_NAME)
    def activate_skill(
        name: SkillName,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> ToolMessage:
        """为当前 Run 激活一个明确匹配任务的只读受管技能。

        仅当技能描述与用户任务高度匹配、专用工作流会带来明确收益时调用。
        简单问题或仅有主题词相似时不要调用。调用必须独占一次模型响应，且每个
        Run 最多自动激活一个技能；显式 slash 技能具有更高优先级。
        """
        skill = catalog.get(name)
        if skill is None:
            return ToolMessage(
                content=_activation_payload(
                    name=name,
                    status="error",
                    message="当前 Run 的受管技能目录中不存在该技能。",
                ),
                tool_call_id=tool_call_id,
                name=SKILL_ACTIVATION_TOOL_NAME,
                status="error",
            )
        # 正文不通过 ToolMessage 返回；Runtime 只凭这份受控元数据再从可信快照投影。
        return ToolMessage(
            id=f"skill-activation:{tool_call_id}",
            content=_activation_payload(
                name=skill.name,
                status="activated",
                message="技能已为当前 Run 激活。",
            ),
            tool_call_id=tool_call_id,
            name=SKILL_ACTIVATION_TOOL_NAME,
            additional_kwargs={
                SKILL_ACTIVATION_METADATA_KEY: {
                    "version": 1,
                    "name": skill.name,
                }
            },
        )

    return activate_skill


def _current_run_messages(messages: Sequence[BaseMessage]) -> tuple[BaseMessage, ...]:
    """只保留最新用户消息开始的窗口，使旧 Run 的激活自然失效。"""
    latest_human_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        None,
    )
    if latest_human_index is None:
        return ()
    return tuple(messages[latest_human_index:])


def _tool_call_identity(tool_call: Mapping[str, object]) -> tuple[str, str] | None:
    """读取可参与可信配对的激活调用 ID 和技能名。"""
    if tool_call.get("name") != SKILL_ACTIVATION_TOOL_NAME:
        return None
    tool_call_id = tool_call.get("id")
    args = tool_call.get("args")
    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
        return None
    if not isinstance(args, Mapping):
        return None
    name = args.get("name")
    if not isinstance(name, str) or not name:
        return None
    return tool_call_id, name


def _result_skill_name(
    message: ToolMessage,
    *,
    expected_name: str,
    catalog: BuiltInSkillCatalog,
) -> str | None:
    """校验工具结果生产者元数据，拒绝正文伪造、错配和未知技能。"""
    if message.name != SKILL_ACTIVATION_TOOL_NAME:
        return None
    if getattr(message, "status", "success") == "error":
        return None
    metadata = (message.additional_kwargs or {}).get(
        SKILL_ACTIVATION_METADATA_KEY
    )
    if not isinstance(metadata, Mapping):
        return None
    if type(metadata.get("version")) is not int or metadata["version"] != 1:
        return None
    name = metadata.get("name")
    if not isinstance(name, str) or name != expected_name:
        return None
    return name if catalog.get(name) is not None else None


def find_automatic_skill_name(
    messages: Sequence[BaseMessage],
    catalog: BuiltInSkillCatalog,
) -> str | None:
    """从当前 Run 的调用和成功结果配对中解析唯一自动激活技能。"""
    pending_calls: dict[str, str] = {}
    activated_names: set[str] = set()
    for message in _current_run_messages(messages):
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls or []:
                identity = _tool_call_identity(tool_call)
                if identity is not None:
                    pending_calls[identity[0]] = identity[1]
            continue
        if not isinstance(message, ToolMessage) or not message.tool_call_id:
            continue
        tool_call_id = str(message.tool_call_id)
        expected_name = pending_calls.get(tool_call_id)
        if expected_name is None:
            continue
        name = _result_skill_name(
            message,
            expected_name=expected_name,
            catalog=catalog,
        )
        if name is not None:
            activated_names.add(name)

    # 专用节点正常情况下只会产生一个名字；异常历史出现多个名字时失败关闭。
    if len(activated_names) != 1:
        return None
    return next(iter(activated_names))
