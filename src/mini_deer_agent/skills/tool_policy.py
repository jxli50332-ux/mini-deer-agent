"""把已激活技能的 allowed-tools 投影为模型与执行端共享的权限决策。"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import SystemMessage

from mini_deer_agent.skills.automatic import SKILL_ACTIVATION_TOOL_NAME
from mini_deer_agent.skills.catalog import BuiltInSkillCatalog, SkillCatalogError


# 这些工具只维护 Agent 自身的受控流程，不向技能开放新的外部数据或委派能力。
ALWAYS_AVAILABLE_SKILL_TOOL_NAMES = frozenset(
    {"ask_clarification", "write_todos", SKILL_ACTIVATION_TOOL_NAME}
)


@dataclass(frozen=True, slots=True)
class SkillToolPolicyDecision:
    """保存一次模型或执行步骤使用的稳定工具权限集合。"""

    active_skill_name: str | None
    allowed_tool_names: tuple[str, ...]
    restricted: bool


def validate_skill_tool_policies(
    catalog: BuiltInSkillCatalog,
    execution_tool_names: tuple[str, ...],
) -> None:
    """拒绝引用运行时未注册工具的受信任内置技能资产。"""
    registered_names = set(execution_tool_names)
    for skill in catalog.skills:
        if skill.allowed_tools is None:
            continue
        unknown_names = tuple(
            name for name in skill.allowed_tools if name not in registered_names
        )
        # 内置技能是随应用发布的可信资产，引用不存在工具属于发布错误；
        # 用户技能按当前 Run 能力做最小交集，普通 Thread 不因项目专用工具缺席而失败。
        if unknown_names and skill.source == "builtin":
            rendered = ", ".join(unknown_names)
            raise SkillCatalogError(
                f"Skill {skill.name!r} declares unknown allowed tool(s): {rendered}"
            )


def resolve_skill_tool_policy(
    *,
    active_skill_name: str | None,
    catalog: BuiltInSkillCatalog,
    passive_tool_names: tuple[str, ...],
    execution_tool_names: tuple[str, ...],
) -> SkillToolPolicyDecision:
    """按执行注册表顺序返回当前技能实际允许的工具名。"""
    active_skill = (
        catalog.get(active_skill_name) if active_skill_name is not None else None
    )
    if active_skill is None or active_skill.allowed_tools is None:
        return SkillToolPolicyDecision(
            active_skill_name=active_skill_name,
            allowed_tool_names=passive_tool_names,
            restricted=False,
        )

    allowed_name_set = set(active_skill.allowed_tools)
    allowed_name_set.update(ALWAYS_AVAILABLE_SKILL_TOOL_NAMES)
    return SkillToolPolicyDecision(
        active_skill_name=active_skill.name,
        allowed_tool_names=tuple(
            name for name in execution_tool_names if name in allowed_name_set
        ),
        restricted=True,
    )


def project_skill_tool_policy(
    system_message: SystemMessage,
    decision: SkillToolPolicyDecision,
) -> SystemMessage:
    """把受限技能的实际能力清单追加到本次可信模型视图。"""
    if not decision.restricted or decision.active_skill_name is None:
        return system_message
    content = system_message.content
    if not isinstance(content, str):
        raise TypeError("Mini Deer system prompt must be text")
    rendered_tools = (
        "、".join(f"`{name}`" for name in decision.allowed_tool_names)
        if decision.allowed_tool_names
        else "无"
    )
    policy_block = "\n".join(
        [
            (
                '<active_skill_tool_policy name="'
                f'{decision.active_skill_name}">'
            ),
            f"当前模型调用的实际可用工具清单：{rendered_tools}。",
            "此清单覆盖基础 Prompt 中的通用工具目录；不要调用未列出的工具。",
            "</active_skill_tool_policy>",
        ]
    )
    return SystemMessage(content=f"{content}\n\n{policy_block}")
