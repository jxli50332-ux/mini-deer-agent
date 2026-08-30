"""公开 Mini Deer Agent 的 FastAPI 应用工厂与默认 ASGI 应用。"""

from mini_deer_agent.server.app import app, create_app


__all__ = ["app", "create_app"]
