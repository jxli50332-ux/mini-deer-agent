"""保存启动时冻结、默认不绑定模型的延迟工具目录。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from langchain_core.tools import BaseTool


_SAFE_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_MAX_SUMMARY_CHARS = 200
_MAX_ROUTING_KEYWORDS = 8
_MAX_ROUTING_KEYWORD_CHARS = 64


@dataclass(frozen=True, slots=True)
class DeferredToolSummary:
    """可进入基础 Prompt 的有界、无 Schema 工具摘要。"""

    name: str
    description: str


def _summary_description(tool: BaseTool) -> str:
    description = " ".join(str(tool.description or "").split())
    if not description:
        return "未提供描述"
    return description[:_MAX_SUMMARY_CHARS]


def _schema_fingerprint(tool: BaseTool) -> dict[str, object]:
    """提取会影响模型调用契约的字段，供提升状态隔离目录版本。"""
    schema = tool.tool_call_schema
    if isinstance(schema, dict):
        schema_payload = schema
    else:
        model_json_schema = getattr(schema, "model_json_schema", None)
        if callable(model_json_schema):
            schema_payload = model_json_schema()
        else:
            legacy_schema = getattr(schema, "schema", None)
            if not callable(legacy_schema):
                raise TypeError("unsupported deferred tool schema")
            schema_payload = legacy_schema()
    return {
        "name": tool.name,
        "description": str(tool.description or ""),
        "schema": schema_payload,
    }


class DeferredToolCatalog:
    """不可变延迟工具快照；工具只在显式提升后才能绑定和执行。"""

    def __init__(
        self,
        tools: tuple[BaseTool, ...] = (),
        *,
        reserved_names: tuple[str, ...] = (),
        routing_keywords: Mapping[str, Collection[str]] | None = None,
    ) -> None:
        reserved = set(reserved_names)
        entries: dict[str, BaseTool] = {}
        for tool in tools:
            name = tool.name.strip()
            if _SAFE_TOOL_NAME.fullmatch(name) is None:
                raise ValueError(f"invalid deferred tool name: {name}")
            if name in reserved:
                raise ValueError(f"deferred tool conflicts with eager tool: {name}")
            if name in entries:
                raise ValueError(f"duplicate deferred tool name: {name}")
            entries[name] = tool
        normalized_routing: dict[str, tuple[str, ...]] = {}
        for name, keywords in (routing_keywords or {}).items():
            if name not in entries:
                raise ValueError(
                    f"routing keywords reference unknown deferred tool: {name}"
                )
            cleaned = tuple(" ".join(keyword.split()) for keyword in keywords)
            if not 1 <= len(cleaned) <= _MAX_ROUTING_KEYWORDS:
                raise ValueError(
                    f"routing keywords for {name} must contain 1-{_MAX_ROUTING_KEYWORDS} items"
                )
            if any(
                not keyword or len(keyword) > _MAX_ROUTING_KEYWORD_CHARS
                for keyword in cleaned
            ):
                raise ValueError(f"invalid routing keyword for deferred tool: {name}")
            if len({keyword.casefold() for keyword in cleaned}) != len(cleaned):
                raise ValueError(f"duplicate routing keyword for deferred tool: {name}")
            normalized_routing[name] = cleaned
        self._entries: Mapping[str, BaseTool] = MappingProxyType(entries)
        self._routing_keywords: Mapping[str, tuple[str, ...]] = MappingProxyType(
            normalized_routing
        )
        fingerprint = [
            _schema_fingerprint(entries[name]) for name in sorted(entries)
        ]
        canonical = json.dumps(
            {
                "tools": fingerprint,
                "routing_keywords": {
                    name: list(normalized_routing[name])
                    for name in sorted(normalized_routing)
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._catalog_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    @property
    def summaries(self) -> tuple[DeferredToolSummary, ...]:
        return tuple(
            DeferredToolSummary(
                name=name,
                description=_summary_description(self._entries[name]),
            )
            for name in self.names
        )

    @property
    def catalog_hash(self) -> str:
        return self._catalog_hash

    def get(self, name: str) -> BaseTool | None:
        return self._entries.get(name)

    @property
    def routing_keywords(self) -> Mapping[str, tuple[str, ...]]:
        """返回由本地服务配置提供的只读路由提示。"""
        return self._routing_keywords

    def search(self, query: str, *, limit: int = 3) -> tuple[BaseTool, ...]:
        """按准确名称和普通关键词返回少量稳定候选，不执行外部工具。"""
        normalized = " ".join(query.split()).casefold()
        if not normalized or not 1 <= limit <= 5:
            return ()
        terms = tuple(
            term for term in re.findall(r"[\w.-]+", normalized) if term
        )
        ranked: list[tuple[int, str, BaseTool]] = []
        for name, tool in self._entries.items():
            folded_name = name.casefold()
            description = _summary_description(tool).casefold()
            score = 0
            if normalized == folded_name:
                score += 10_000
            elif normalized in folded_name:
                score += 1_000
            for keyword in self._routing_keywords.get(name, ()):
                folded_keyword = keyword.casefold()
                if normalized == folded_keyword:
                    score += 9_000
                elif normalized in folded_keyword or folded_keyword in normalized:
                    score += 3_000
                for term in terms:
                    if term in folded_keyword:
                        score += 300
            for term in terms:
                if term == folded_name:
                    score += 500
                elif term in folded_name:
                    score += 100
                if term in description:
                    score += 10
            if score > 0:
                ranked.append((score, name, tool))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[2] for item in ranked[:limit])

    def schema_payload(self, tool: BaseTool) -> dict[str, object]:
        """返回模型发现结果所需的完整调用契约。"""
        registered = self._entries.get(tool.name)
        if registered is not tool:
            raise ValueError("tool does not belong to deferred catalog")
        return _schema_fingerprint(tool)


__all__ = ["DeferredToolCatalog", "DeferredToolSummary"]
