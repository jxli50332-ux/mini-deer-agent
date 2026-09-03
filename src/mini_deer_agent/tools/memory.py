"""提供由应用注入存储的显式长期 Memory CRUD 工具。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from mini_deer_agent.domain import (
    MAX_MEMORY_CONTENT_LENGTH,
    MAX_MEMORY_QUERY_LENGTH,
    MAX_MEMORY_SEARCH_LIMIT,
    MemoryFact,
)

if TYPE_CHECKING:
    from mini_deer_agent.application.memory import MemoryStore


type MemoryCategoryInput = Literal[
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


class MemorySearchInput(BaseModel):
    """按需读取长期事实的模型参数。"""

    query: str = Field(
        default="",
        max_length=MAX_MEMORY_QUERY_LENGTH,
        description="要匹配的字面文字；传空字符串可列出最近 Memory",
    )
    category: MemoryCategoryInput | None = Field(
        default=None,
        description="可选的精确分类过滤",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=MAX_MEMORY_SEARCH_LIMIT,
        description="最多返回的事实数",
    )


class MemoryAddInput(BaseModel):
    """新增一条用户明确要求保存的事实。"""

    content: str = Field(
        min_length=1,
        max_length=MAX_MEMORY_CONTENT_LENGTH,
        description="用户明确要求跨对话记住的稳定事实",
    )
    category: MemoryCategoryInput = Field(
        default="context",
        description="事实分类",
    )
    confidence: float = Field(
        default=1.0,
        ge=0,
        le=1,
        description="事实置信度；用户明确陈述通常使用 1.0",
    )


class MemoryUpdateInput(BaseModel):
    """局部修改一条已经查到的事实。"""

    fact_id: str = Field(min_length=1, description="memory_search 返回的事实 ID")
    content: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MEMORY_CONTENT_LENGTH,
        description="新事实正文；省略则不修改",
    )
    category: MemoryCategoryInput | None = Field(
        default=None,
        description="新分类；省略则不修改",
    )
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="新置信度；省略则不修改",
    )


class MemoryDeleteInput(BaseModel):
    """删除一条已经查到的事实。"""

    fact_id: str = Field(min_length=1, description="memory_search 返回的事实 ID")


def _fact_payload(fact: MemoryFact) -> dict[str, object]:
    """把领域对象转换为与 DeerFlow 工具模式相近的稳定 JSON。"""
    return {
        "id": fact.fact_id,
        "content": fact.content,
        "category": fact.category,
        "confidence": fact.confidence,
        "source": fact.source,
        "createdAt": fact.created_at,
        "updatedAt": fact.updated_at,
    }


def _json(payload: dict[str, object]) -> str:
    """避免工具结果受 Python repr 和本机字符转义影响。"""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _memory_error(exc: Exception) -> str:
    """把预期领域错误转换为可供模型修正调用的窄错误。"""
    if isinstance(exc, KeyError):
        fact_id = exc.args[0] if exc.args else ""
        return _json({"error": f"Fact not found: {fact_id}"})
    if isinstance(exc, ValueError):
        return _json({"error": str(exc)})
    return _json({"error": "Memory operation failed"})


def create_memory_tools(store: MemoryStore) -> tuple[BaseTool, ...]:
    """为一个应用级存储端口创建同步/异步一致的四个模型工具。"""

    def memory_search(
        query: str = "",
        category: MemoryCategoryInput | None = None,
        limit: int = 10,
    ) -> str:
        """查询跨 Thread 长期 Memory；相关历史偏好或约束可能有用时调用。"""
        try:
            facts = store.search_memory_facts(
                query,
                category=category,
                limit=limit,
            )
            return _json(
                {
                    "results": [_fact_payload(fact) for fact in facts],
                    "count": len(facts),
                }
            )
        except Exception as exc:
            return _memory_error(exc)

    async def memory_search_async(
        query: str = "",
        category: MemoryCategoryInput | None = None,
        limit: int = 10,
    ) -> str:
        """在线程池执行 SQLite 查询，避免阻塞异步 Run。"""
        return await asyncio.to_thread(memory_search, query, category, limit)

    def memory_add(
        content: str,
        category: MemoryCategoryInput = "context",
        confidence: float = 1.0,
    ) -> str:
        """仅在用户明确要求记住时，新增一条跨 Thread 长期事实。"""
        try:
            fact = store.create_memory_fact(
                content,
                category=category,
                confidence=confidence,
            )
            return _json({"fact_id": fact.fact_id, "status": "added"})
        except Exception as exc:
            return _memory_error(exc)

    async def memory_add_async(
        content: str,
        category: MemoryCategoryInput = "context",
        confidence: float = 1.0,
    ) -> str:
        """在线程池执行显式新增。"""
        return await asyncio.to_thread(memory_add, content, category, confidence)

    def memory_update(
        fact_id: str,
        content: str | None = None,
        category: MemoryCategoryInput | None = None,
        confidence: float | None = None,
    ) -> str:
        """仅在用户明确要求修改时，局部更新已由搜索确认的 Memory。"""
        try:
            fact = store.update_memory_fact(
                fact_id,
                content=content,
                category=category,
                confidence=confidence,
            )
            return _json({"fact_id": fact.fact_id, "status": "updated"})
        except Exception as exc:
            return _memory_error(exc)

    async def memory_update_async(
        fact_id: str,
        content: str | None = None,
        category: MemoryCategoryInput | None = None,
        confidence: float | None = None,
    ) -> str:
        """在线程池执行显式更新。"""
        return await asyncio.to_thread(
            memory_update,
            fact_id,
            content,
            category,
            confidence,
        )

    def memory_delete(fact_id: str) -> str:
        """仅在用户明确要求忘记时，删除已由搜索确认的 Memory。"""
        try:
            store.delete_memory_fact(fact_id)
            return _json({"fact_id": fact_id, "status": "deleted"})
        except Exception as exc:
            return _memory_error(exc)

    async def memory_delete_async(fact_id: str) -> str:
        """在线程池执行显式删除。"""
        return await asyncio.to_thread(memory_delete, fact_id)

    return (
        StructuredTool.from_function(
            func=memory_search,
            coroutine=memory_search_async,
            name="memory_search",
            description=(
                "查询跨 Thread 的长期 Memory。涉及过去偏好、纠正、约束或持久背景时，"
                "先搜索再回答；空 query 可列出最近事实。"
            ),
            args_schema=MemorySearchInput,
        ),
        StructuredTool.from_function(
            func=memory_add,
            coroutine=memory_add_async,
            name="memory_add",
            description=(
                "新增跨 Thread 长期 Memory。只有用户明确要求记住稳定事实时才能调用，"
                "不能根据普通对话自行保存。"
            ),
            args_schema=MemoryAddInput,
        ),
        StructuredTool.from_function(
            func=memory_update,
            coroutine=memory_update_async,
            name="memory_update",
            description=(
                "局部更新长期 Memory。用户明确要求修改时，先用 memory_search 取得 fact_id。"
            ),
            args_schema=MemoryUpdateInput,
        ),
        StructuredTool.from_function(
            func=memory_delete,
            coroutine=memory_delete_async,
            name="memory_delete",
            description=(
                "删除长期 Memory。用户明确要求忘记时，先用 memory_search 取得 fact_id。"
            ),
            args_schema=MemoryDeleteInput,
        ),
    )
