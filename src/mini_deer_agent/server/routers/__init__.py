"""集中暴露 FastAPI router，供应用工厂统一注册。"""

from . import benchmarks, health, mcp, runs, skills, threads


__all__ = ["benchmarks", "health", "mcp", "runs", "skills", "threads"]
