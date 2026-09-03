"""定义本地单用户长期 Memory 的应用端口与稳定错误。"""

from typing import Protocol

from mini_deer_agent.domain import MemoryCategory, MemoryFact


class DuplicateMemoryFactError(ValueError):
    """表示规范化后的 Memory 内容已经存在。"""


class MemoryFactNotFoundError(KeyError):
    """表示写操作引用了不存在的 Memory fact_id。"""


class MemoryStore(Protocol):
    """定义模型工具所需的最小跨 Thread Memory 存储契约。"""

    def search_memory_facts(
        self,
        query: str,
        *,
        category: str | None = None,
        limit: int = 10,
    ) -> tuple[MemoryFact, ...]:
        """按字面文字查询事实；空查询返回最近事实。"""

    def create_memory_fact(
        self,
        content: str,
        *,
        category: str = "context",
        confidence: float = 1.0,
    ) -> MemoryFact:
        """创建一条由用户明确授权的事实。"""

    def update_memory_fact(
        self,
        fact_id: str,
        *,
        content: str | None = None,
        category: str | None = None,
        confidence: float | None = None,
    ) -> MemoryFact:
        """局部更新事实，未提供的字段保持不变。"""

    def delete_memory_fact(self, fact_id: str) -> None:
        """物理删除一条事实。"""
