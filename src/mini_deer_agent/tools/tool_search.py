"""提供只发现、不执行的延迟工具搜索入口。"""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import StructuredTool
from pydantic import Field, StringConstraints

from mini_deer_agent.deferred_tools import DeferredToolCatalog


type ToolSearchQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    Field(description="准确工具名称，或描述任务能力的简短关键词"),
]
type ToolSearchLimit = Annotated[
    int,
    Field(ge=1, le=5, description="最多返回的完整工具 Schema 数量"),
]


def create_tool_search_tool(catalog: DeferredToolCatalog) -> StructuredTool:
    """为一个冻结目录创建确定性的 Schema 发现工具。"""

    def search_tools(
        query: ToolSearchQuery,
        max_results: ToolSearchLimit = 3,
    ) -> str:
        matches = catalog.search(query, limit=max_results)
        return json.dumps(
            {
                "version": 1,
                "kind": "tool_search_results",
                "catalog_hash": catalog.catalog_hash,
                "query": query,
                "matches": [catalog.schema_payload(tool) for tool in matches],
            },
            ensure_ascii=False,
            indent=2,
        )

    return StructuredTool.from_function(
        func=search_tools,
        name="tool_search",
        description=(
            "按准确名称或关键词发现当前 MCP 延迟目录中的少量工具；"
            "返回完整参数 Schema，但不执行目标工具。"
        ),
    )


__all__ = ["create_tool_search_tool"]
