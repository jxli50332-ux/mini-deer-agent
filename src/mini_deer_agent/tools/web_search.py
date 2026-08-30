"""提供基于 DDGS 的联网文本搜索工具。"""

import asyncio
import json
import logging
from typing import Annotated, Any

from ddgs import DDGS
from langchain_core.tools import StructuredTool


logger = logging.getLogger(__name__)

_DEFAULT_MAX_RESULTS = 5
_MAX_RESULTS = 10
_MAX_CONTENT_LENGTH = 1_000
_SEARCH_TIMEOUT_SECONDS = 10
_CJK_RANGE = (0x3400, 0x9FFF)


def _create_search_client() -> DDGS:
    """创建具有有限网络超时的搜索客户端。"""
    return DDGS(timeout=_SEARCH_TIMEOUT_SECONDS)


def _normalize_query(query: str) -> str:
    """清理模型生成的查询，并拒绝没有搜索语义的空文本。"""
    normalized = query.strip()
    if not normalized:
        raise ValueError("query 不能为空")
    return normalized


def _normalize_max_results(max_results: int) -> int:
    """限制模型可请求的结果数量，避免工具结果无限占用上下文。"""
    return min(max(max_results, 1), _MAX_RESULTS)


def _resolve_region(query: str) -> str:
    """为中文查询选择中文区域，其余查询使用稳定的英文区域。"""
    if any(_CJK_RANGE[0] <= ord(character) <= _CJK_RANGE[1] for character in query):
        return "cn-zh"
    return "us-en"


def _normalize_text(value: object) -> str:
    """只接受搜索供应商返回的文本字段。"""
    return value.strip() if isinstance(value, str) else ""


def _normalize_results(results: object) -> list[dict[str, str]]:
    """把不同搜索后端的字段归一化为稳定、有限长度的结果。"""
    if not isinstance(results, list):
        return []

    normalized_results: list[dict[str, str]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        title = _normalize_text(result.get("title"))
        url = _normalize_text(result.get("href") or result.get("url"))
        content = _normalize_text(result.get("body") or result.get("content"))
        if not any((title, url, content)):
            continue
        normalized_results.append(
            {
                "title": title,
                "url": url,
                "content": content[:_MAX_CONTENT_LENGTH],
            }
        )
    return normalized_results


def _render_search_result(
    query: str,
    normalized_results: list[dict[str, str]],
    *,
    error: str | None = None,
) -> str:
    """生成模型容易读取、也便于测试的确定 JSON 工具结果。"""
    payload: dict[str, object] = {
        "query": query,
        "total_results": len(normalized_results),
        "results": normalized_results,
    }
    if error is not None:
        payload["error"] = error
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _execute_search(query: str, max_results: int) -> str:
    """执行一次同步搜索，并把供应商异常收敛为可恢复的工具结果。"""
    try:
        client = _create_search_client()
        results = client.text(
            query,
            region=_resolve_region(query),
            safesearch="moderate",
            max_results=max_results,
            backend="auto",
        )
    except Exception as exc:
        # 不记录用户查询或完整异常文本，避免日志意外保存敏感搜索内容。
        logger.warning("联网搜索失败：%s", type(exc).__name__)
        return _render_search_result(
            query,
            [],
            error="搜索服务暂时不可用，请稍后重试。",
        )

    normalized_results = _normalize_results(results)
    if not normalized_results:
        return _render_search_result(query, [], error="未找到相关搜索结果。")
    return _render_search_result(query, normalized_results)


def _web_search(
    query: Annotated[str, "具体、完整的联网搜索关键词"],
    max_results: Annotated[int, "最多返回多少条结果，范围 1 到 10"] = (
        _DEFAULT_MAX_RESULTS
    ),
) -> str:
    """搜索互联网中的当前信息、新闻、文章和事实，并返回来源链接。"""
    normalized_query = _normalize_query(query)
    normalized_max_results = _normalize_max_results(max_results)
    return _execute_search(normalized_query, normalized_max_results)


async def _web_search_async(
    query: Annotated[str, "具体、完整的联网搜索关键词"],
    max_results: Annotated[int, "最多返回多少条结果，范围 1 到 10"] = (
        _DEFAULT_MAX_RESULTS
    ),
) -> str:
    """在线程中搜索，使异步 Agent 可取消等待且不阻塞事件循环。"""
    normalized_query = _normalize_query(query)
    normalized_max_results = _normalize_max_results(max_results)
    # DDGS 目前只公开同步搜索 API；取消 await 后底层线程会在网络超时内自然退出。
    return await asyncio.to_thread(
        _execute_search,
        normalized_query,
        normalized_max_results,
    )


web_search = StructuredTool.from_function(
    func=_web_search,
    coroutine=_web_search_async,
    name="web_search",
    description="搜索互联网中的当前信息、新闻、文章和事实，并返回来源链接。",
)
