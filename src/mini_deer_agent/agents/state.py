"""定义主 Agent 与子 Agent 共享的可持久化状态。"""

from typing import Annotated, NotRequired

from langgraph.graph import MessagesState

from mini_deer_agent.agents.durable_state import (
    DelegationEntry,
    SkillContextEntry,
    TodoSnapshot,
    PromotedToolState,
    GoalState,
    merge_delegations,
    merge_skill_context,
    merge_todos,
)


class MiniDeerAgentState(MessagesState):
    """保存消息、累计摘要以及不能依赖有损摘要的结构化状态。"""

    summary_text: NotRequired[str]
    delegations: NotRequired[
        Annotated[list[DelegationEntry], merge_delegations]
    ]
    skill_context: NotRequired[
        Annotated[list[SkillContextEntry], merge_skill_context]
    ]
    todos: NotRequired[Annotated[TodoSnapshot | None, merge_todos]]
    promoted_tools: NotRequired[PromotedToolState]
    goal: NotRequired[GoalState | None]
