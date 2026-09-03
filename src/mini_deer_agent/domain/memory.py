"""定义跨 Thread 持久化的本地单用户 Memory 事实。"""

from dataclasses import dataclass
from typing import Literal


type MemoryCategory = Literal[
    "preference",
    "correction",
    "context",
    "goal",
    "behavior",
    "identity",
    "constraint",
    "decision",
    "other",
]


MEMORY_CATEGORIES: tuple[MemoryCategory, ...] = (
    "preference",
    "correction",
    "context",
    "goal",
    "behavior",
    "identity",
    "constraint",
    "decision",
    "other",
)
MAX_MEMORY_CONTENT_LENGTH = 2_000
MAX_MEMORY_QUERY_LENGTH = 500
MAX_MEMORY_SEARCH_LIMIT = 50


@dataclass(frozen=True, slots=True)
class MemoryFact:
    """表示一条由用户明确授权、可跨 Thread 复用的事实。"""

    fact_id: str
    content: str
    category: MemoryCategory
    confidence: float
    source: Literal["manual"]
    created_at: str
    updated_at: str
