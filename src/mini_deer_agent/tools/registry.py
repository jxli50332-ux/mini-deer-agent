"""集中组装主 Agent 可见的工具集合。"""

from langchain_core.tools import BaseTool

from mini_deer_agent.tools.clarification import ask_clarification
from mini_deer_agent.tools.todos import write_todos
from mini_deer_agent.tools.weather import get_weather
from mini_deer_agent.tools.web_fetch import web_fetch
from mini_deer_agent.tools.web_search import web_search


# 动态工具同样占用全局函数名；MCP 发现阶段要在模型首次绑定前拒绝覆盖。
_DYNAMIC_AGENT_TOOL_NAMES = (
    "activate_skill",
    "task",
    "memory_search",
    "memory_add",
    "memory_update",
    "memory_delete",
)


def get_agent_tools(
    task_tool: BaseTool | None = None,
    skill_activation_tool: BaseTool | None = None,
    *,
    extra_tools: tuple[BaseTool, ...] = (),
) -> tuple[BaseTool, ...]:
    """返回主图工具，并按当前 Run 能力追加技能激活与一次性 task。"""
    # 模型绑定与 ToolNode 必须复用这个集合，避免模型请求了执行器未注册的工具。
    base_tools = (web_search, web_fetch, write_todos, ask_clarification)
    optional_tools = tuple(
        tool
        for tool in (skill_activation_tool, task_tool)
        if tool is not None
    )
    return (*base_tools, *optional_tools, *extra_tools)


def get_skill_tools() -> tuple[BaseTool, ...]:
    """返回只有匹配技能激活后才能进入模型契约的专用工具。"""
    return (get_weather,)


def get_reserved_agent_tool_names() -> tuple[str, ...]:
    """返回内置、技能专用和按 Run 创建工具共同占用的名称。"""
    static_tools = (*get_agent_tools(), *get_skill_tools())
    return (
        *(tool.name for tool in static_tools),
        *_DYNAMIC_AGENT_TOOL_NAMES,
    )
