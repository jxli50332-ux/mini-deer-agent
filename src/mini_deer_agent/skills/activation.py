"""把显式 slash 技能选择投影为当前 Run 的模型专用上下文。"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from mini_deer_agent.skills.catalog import BuiltInSkillCatalog
from mini_deer_agent.skills.automatic import find_automatic_skill_name
from mini_deer_agent.skills.contracts import (
    SkillActivationProjection,
    SlashSkillReference,
)


RESERVED_SLASH_SKILL_NAMES = frozenset(
    {"bootstrap", "goal", "help", "memory", "models", "new", "status"}
)
_SLASH_SKILL_PATTERN = re.compile(
    r"^/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\s+|$)"
)


def parse_slash_skill_reference(text: str) -> SlashSkillReference | None:
    """解析严格的 `/skill-name task`，保留命令不会被当成技能。"""
    match = _SLASH_SKILL_PATTERN.match(text)
    if match is None:
        return None
    name = match.group(1)
    if name in RESERVED_SLASH_SKILL_NAMES:
        return None
    return SlashSkillReference(
        name=name,
        task_text=text[match.end() :].lstrip(),
    )


def _activated_system_message(
    base: SystemMessage,
    *,
    skill_name: str,
    instructions: str,
    source: Literal["explicit", "automatic", "durable"],
) -> SystemMessage:
    """把只读内置指令追加到当前可信 SystemMessage，不写入状态历史。"""
    base_content = base.content
    if not isinstance(base_content, str):
        raise TypeError("Mini Deer system prompt must be text")
    escaped_instructions = html.escape(instructions, quote=False)
    source_messages = {
        "explicit": "用户已为当前 Run 显式激活此只读内置技能。",
        "automatic": "模型已在当前 Run 通过可见工具调用激活此只读内置技能。",
        "durable": "Runtime 已从当前用户回合的可信 Durable Context 恢复此前激活的只读内置技能。",
    }
    source_message = source_messages[source]
    activation = "\n".join(
        [
            f'<activated_skill name="{skill_name}">',
            source_message,
            "优先遵循技能工作流，但仍须服从基础系统规则和用户明确约束。",
            '<skill_instructions encoding="xml-escaped">',
            escaped_instructions,
            "</skill_instructions>",
            "</activated_skill>",
        ]
    )
    return SystemMessage(content=f"{base_content}\n\n{activation}")


def _plain_projection(
    system_message: SystemMessage,
    messages: Sequence[BaseMessage],
) -> SkillActivationProjection:
    """返回没有技能激活时的零修改模型投影。"""
    return SkillActivationProjection(
        system_message=system_message,
        messages=tuple(messages),
    )


def project_skill_activation(
    system_message: SystemMessage,
    messages: Sequence[BaseMessage],
    catalog: BuiltInSkillCatalog | None,
    *,
    durable_skill_name: str | None = None,
) -> SkillActivationProjection:
    """只根据最新用户消息激活技能，并把结果限制在当前模型调用视图。

    同一产品 Run 的每次模型调用都会重新从原始 checkpoint 消息投影，因此工具循环
    持续携带技能；下一 Run 追加普通 HumanMessage 后，旧 slash 不会再次激活。
    """
    if catalog is None:
        return _plain_projection(system_message, messages)

    target_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if isinstance(messages[index], HumanMessage)
        ),
        None,
    )
    if target_index is None:
        return _plain_projection(system_message, messages)
    target = messages[target_index]
    if not isinstance(target, HumanMessage):
        return _plain_projection(system_message, messages)
    # 澄清卡片的隐藏回答不是 Composer slash 命令，但仍允许模型在本 Run 后续自主激活。
    is_hidden_response = (target.additional_kwargs or {}).get("hide_from_ui") is True
    reference = (
        parse_slash_skill_reference(target.content)
        if not is_hidden_response and isinstance(target.content, str)
        else None
    )
    if reference is not None:
        skill = catalog.get(reference.name)
        if skill is None:
            available = "、".join(f"`/{item.name}`" for item in catalog.skills)
            suffix = (
                f"当前可用技能：{available}。"
                if available
                else "当前没有可用内置技能。"
            )
            return SkillActivationProjection(
                system_message=system_message,
                messages=tuple(messages),
                failure_message=(
                    f"未找到内置技能 `/{reference.name}`。{suffix}"
                ),
            )
        if not reference.task_text:
            return SkillActivationProjection(
                system_message=system_message,
                messages=tuple(messages),
                failure_message=(
                    f"请在 `/{reference.name}` 后提供任务内容，例如："
                    f"`/{reference.name} 解释要处理的问题`。"
                ),
            )

        projected_messages = list(messages)
        projected_messages[target_index] = target.model_copy(
            update={"content": reference.task_text}
        )
        return SkillActivationProjection(
            system_message=_activated_system_message(
                system_message,
                skill_name=skill.name,
                instructions=skill.instructions,
                source="explicit",
            ),
            messages=tuple(projected_messages),
            skill_name=skill.name,
        )

    automatic_name = find_automatic_skill_name(messages, catalog)
    automatic_skill = catalog.get(automatic_name) if automatic_name else None
    if automatic_skill is None:
        durable_skill = (
            catalog.get(durable_skill_name) if durable_skill_name else None
        )
        if durable_skill is None:
            return _plain_projection(system_message, messages)
        return SkillActivationProjection(
            system_message=_activated_system_message(
                system_message,
                skill_name=durable_skill.name,
                instructions=durable_skill.instructions,
                source="durable",
            ),
            messages=tuple(messages),
            skill_name=durable_skill.name,
        )
    return SkillActivationProjection(
        system_message=_activated_system_message(
            system_message,
            skill_name=automatic_skill.name,
            instructions=automatic_skill.instructions,
            source="automatic",
        ),
        messages=tuple(messages),
        skill_name=automatic_skill.name,
    )
