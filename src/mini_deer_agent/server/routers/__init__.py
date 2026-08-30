"""集中暴露 FastAPI router，供应用工厂统一注册。"""

from . import health, runs, threads


__all__ = ["health", "runs", "threads"]
