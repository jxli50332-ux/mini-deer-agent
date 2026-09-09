"""定义内置技能目录与激活链路使用的不可变数据契约。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from langchain_core.messages import BaseMessage, SystemMessage


@dataclass(frozen=True, slots=True)
class SkillSummary:
    """保存允许进入基础 Prompt 的技能发现元数据。"""

    name: str
    description: str


@dataclass(frozen=True, slots=True)
class SkillResource:
    """表示只在技能激活后加载的有界只读文本资源。"""

    path: str
    content: str


@dataclass(frozen=True, slots=True)
class BuiltInSkill:
    """表示一个已经从受管包目录解析完成的只读技能。"""

    name: str
    description: str
    instructions: str
    source_file: Path
    # None 保留旧技能的主 Agent 工具集合；显式元组会启用最小权限策略。
    allowed_tools: tuple[str, ...] | None = None
    resources: tuple[SkillResource, ...] = ()
    source: Literal["builtin", "user", "market"] = "builtin"

    @property
    def summary(self) -> SkillSummary:
        """返回不含正文和主机路径的模型发现信息。"""
        return SkillSummary(name=self.name, description=self.description)


@dataclass(frozen=True, slots=True)
class SlashSkillReference:
    """保存从严格 slash 命令中解析出的技能名与任务正文。"""

    name: str
    task_text: str


@dataclass(frozen=True, slots=True)
class SkillActivationProjection:
    """保存只供一次模型调用使用、不会写回 checkpoint 的技能投影。"""

    system_message: SystemMessage
    messages: tuple[BaseMessage, ...]
    skill_name: str | None = None
    failure_message: str | None = None
