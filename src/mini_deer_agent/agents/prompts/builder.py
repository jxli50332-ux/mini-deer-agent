"""构建版本化、与具体模型供应商解耦的 SystemMessage。"""

import html
import re

from langchain_core.messages import SystemMessage

from mini_deer_agent.agents.prompts.contracts import (
    AgentPromptContext,
    BuiltAgentPrompt,
)
from mini_deer_agent.agents.prompts.templates import (
    DEFAULT_PROMPT_VERSION,
    DEFAULT_SYSTEM_PROMPT_TEMPLATE,
)


_MAX_AGENT_NAME_LENGTH = 80
_MAX_TOOL_NAME_LENGTH = 128
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def _normalize_agent_name(value: str) -> str:
    """校验并转义进入结构化提示标签的产品名称。"""
    normalized = value.strip()
    if not normalized:
        raise ValueError("agent_name must not be blank")
    if len(normalized) > _MAX_AGENT_NAME_LENGTH:
        raise ValueError("agent_name is too long")
    # 即使名称来自服务端配置，也不能让特殊字符破坏 Prompt 的结构标签。
    return html.escape(normalized, quote=False)


def _normalize_tool_names(values: tuple[str, ...]) -> tuple[str, ...]:
    """返回稳定排序且去重的工具名称，拒绝不能安全展示的标识符。"""
    normalized_names: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool name must not be blank")
        if len(normalized) > _MAX_TOOL_NAME_LENGTH:
            raise ValueError("tool name is too long")
        if _TOOL_NAME_PATTERN.fullmatch(normalized) is None:
            raise ValueError(f"invalid tool name: {normalized}")
        normalized_names.add(normalized)
    return tuple(sorted(normalized_names))


def _render_tool_catalog(tool_names: tuple[str, ...]) -> str:
    """把运行时注册表投影为简洁、确定的模型能力清单。"""
    if not tool_names:
        return "当前没有注册可调用工具。"
    rendered_names = "、".join(f"`{name}`" for name in tool_names)
    return f"当前注册的可调用工具：{rendered_names}。"


class DefaultAgentPromptBuilder:
    """构建 Mini Deer Agent v1 静态系统提示。"""

    @property
    def version(self) -> str:
        """返回当前默认 Prompt 的稳定版本标识。"""
        return DEFAULT_PROMPT_VERSION

    def build(self, context: AgentPromptContext) -> BuiltAgentPrompt:
        """使用产品身份和真实工具注册表生成单一 SystemMessage。"""
        agent_name = _normalize_agent_name(context.agent_name)
        tool_names = _normalize_tool_names(context.available_tool_names)
        content = DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(
            agent_name=agent_name,
            tool_catalog=_render_tool_catalog(tool_names),
        )
        return BuiltAgentPrompt(
            version=self.version,
            system_message=SystemMessage(content=content),
        )
