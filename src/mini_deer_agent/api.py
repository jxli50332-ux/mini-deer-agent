"""保留稳定 ASGI 导入路径，具体组装逻辑位于 server 包。"""

from mini_deer_agent.server import app, create_app


__all__ = ["app", "create_app"]
