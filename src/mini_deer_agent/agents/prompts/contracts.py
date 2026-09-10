"""定义 Prompt Builder 与 Agent Runtime 之间的稳定契约。"""

from dataclasses import dataclass
from typing import Literal, Protocol

from langchain_core.messages import SystemMessage

from mini_deer_agent.skills import SkillSummary
from mini_deer_agent.deferred_tools import DeferredToolSummary


@dataclass(frozen=True, slots=True)
class AgentPromptContext:
    """保存构建系统提示所需的可信产品上下文。"""

    agent_name: str = "Mini Deer Agent"
    current_model_name: str | None = None
    available_tool_names: tuple[str, ...] = ()
    available_skills: tuple[SkillSummary, ...] = ()
    deferred_tools: tuple[DeferredToolSummary, ...] = ()
    readonly_project_id: str | None = None
    readonly_file_access_source: (
        Literal["project", "explicit", "workspace"] | None
    ) = None
    readonly_file_target_kind: (
        Literal["directory", "file", "roots"] | None
    ) = None
    readonly_project_root_entries: (
        tuple[tuple[str, Literal["directory", "file"]], ...] | None
    ) = None
    readonly_project_root_truncated: bool = False
    run_output_access_enabled: bool = False


@dataclass(frozen=True, slots=True)
class BuiltAgentPrompt:
    """返回版本号和模型调用使用的 SystemMessage。"""

    version: str
    system_message: SystemMessage


class AgentPromptBuilder(Protocol):
    """允许不同 Agent 或 Prompt 版本替换默认构建器。"""

    def build(self, context: AgentPromptContext) -> BuiltAgentPrompt:
        """根据可信上下文构建一个完整、确定的系统提示。"""
        ...
