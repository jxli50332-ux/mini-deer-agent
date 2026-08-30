"""集中组装主 Agent 可见的工具集合。"""

from langchain_core.tools import BaseTool

from mini_deer_agent.tools.web_fetch import web_fetch
from mini_deer_agent.tools.web_search import web_search


def get_agent_tools() -> tuple[BaseTool, ...]:
    """返回同一轮 Agent 构建使用的不可变工具集合。"""
    # 模型绑定与 ToolNode 必须复用这个集合，避免模型请求了执行器未注册的工具。
    return (web_search, web_fetch)
