"""公开 Agent 工具与工具注册入口，调用方不依赖具体工具文件。"""

from mini_deer_agent.tools.registry import get_agent_tools
from mini_deer_agent.tools.web_fetch import web_fetch
from mini_deer_agent.tools.web_search import web_search
from mini_deer_agent.tools.weather import get_weather


__all__ = ["get_agent_tools", "get_weather", "web_fetch", "web_search"]
