"""验证联网搜索工具的契约、结果边界和异步取消行为。"""

import asyncio
import json
import threading
from importlib import import_module
from typing import Any

import pytest

from mini_deer_agent.tools import get_agent_tools, web_search


web_search_module = import_module("mini_deer_agent.tools.web_search")


class FakeSearchClient:
    """返回固定结果并记录 DDGS 调用参数。"""

    def __init__(self, results: object) -> None:
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def text(self, query: str, **kwargs: Any) -> object:
        """模拟 DDGS 文本搜索。"""
        self.calls.append((query, kwargs))
        return self.results


def test_web_search_exposes_model_visible_contract() -> None:
    """工具应公开稳定名称、用途和有界的可选结果数参数。"""
    schema = web_search.args_schema.model_json_schema()

    assert web_search.name == "web_search"
    assert web_search.description.startswith("搜索互联网中的当前信息")
    assert schema["required"] == ["query"]
    assert schema["properties"]["query"]["description"] == (
        "具体、完整的联网搜索关键词"
    )
    assert schema["properties"]["max_results"]["default"] == 5


def test_agent_registry_exposes_search_before_fetch() -> None:
    """模型和 ToolNode 应复用同一组搜索、正文读取工具，并保持稳定顺序。"""
    assert tuple(tool.name for tool in get_agent_tools()) == (
        "web_search",
        "web_fetch",
        "write_todos",
        "ask_clarification",
    )


def test_web_search_normalizes_ddgs_results_and_chinese_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """中文搜索应使用中文区域，并把供应商字段转换为固定 JSON。"""
    client = FakeSearchClient(
        [
            {
                "title": "示例标题",
                "href": "https://example.com/news",
                "body": "示例摘要",
            },
            {"title": "空摘要也可保留", "url": "https://example.com/second"},
        ]
    )
    monkeypatch.setattr(web_search_module, "_create_search_client", lambda: client)

    result = json.loads(
        web_search.invoke({"query": "  今天的人工智能新闻  ", "max_results": 99})
    )

    assert client.calls == [
        (
            "今天的人工智能新闻",
            {
                "region": "cn-zh",
                "safesearch": "moderate",
                "max_results": 10,
                "backend": "auto",
            },
        )
    ]
    assert result == {
        "query": "今天的人工智能新闻",
        "total_results": 2,
        "results": [
            {
                "title": "示例标题",
                "url": "https://example.com/news",
                "content": "示例摘要",
            },
            {
                "title": "空摘要也可保留",
                "url": "https://example.com/second",
                "content": "",
            },
        ],
    }


def test_web_search_uses_english_region_and_truncates_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非中文搜索应使用英文区域，且不能返回无限长摘要。"""
    client = FakeSearchClient(
        [{"title": "Python", "href": "https://python.org", "body": "x" * 1_200}]
    )
    monkeypatch.setattr(web_search_module, "_create_search_client", lambda: client)

    result = json.loads(web_search.invoke({"query": "Python release"}))

    assert client.calls[0][1]["region"] == "us-en"
    assert client.calls[0][1]["max_results"] == 5
    assert len(result["results"][0]["content"]) == 1_000


def test_web_search_returns_recoverable_error_for_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有结果时应把错误交回模型，而不是让整个 Agent Run 失败。"""
    monkeypatch.setattr(
        web_search_module,
        "_create_search_client",
        lambda: FakeSearchClient([]),
    )

    result = json.loads(web_search.invoke({"query": "没有结果的搜索"}))

    assert result == {
        "query": "没有结果的搜索",
        "total_results": 0,
        "results": [],
        "error": "未找到相关搜索结果。",
    }


def test_web_search_returns_recoverable_error_for_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """供应商异常不应泄露异常正文或中断工具循环。"""
    class FailingSearchClient:
        """模拟外部搜索服务失败。"""

        def text(self, query: str, **kwargs: Any) -> object:
            raise RuntimeError("包含不应返回给模型的内部信息")

    monkeypatch.setattr(
        web_search_module,
        "_create_search_client",
        FailingSearchClient,
    )

    rendered = web_search.invoke({"query": "服务异常"})
    result = json.loads(rendered)

    assert result["error"] == "搜索服务暂时不可用，请稍后重试。"
    assert "内部信息" not in rendered


def test_web_search_rejects_blank_query() -> None:
    """空查询应在启动网络请求前立即拒绝。"""
    with pytest.raises(ValueError, match="query 不能为空"):
        web_search.invoke({"query": "   "})


def test_async_web_search_wait_is_cancellable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取消 Web Run 时不应继续等待同步 DDGS 线程返回。"""
    async def scenario() -> None:
        search_started = threading.Event()
        allow_search_to_finish = threading.Event()

        class BlockingSearchClient:
            """模拟会运行到网络超时的同步 DDGS 调用。"""

            def text(self, query: str, **kwargs: Any) -> object:
                search_started.set()
                allow_search_to_finish.wait(timeout=2)
                return []

        monkeypatch.setattr(
            web_search_module,
            "_create_search_client",
            BlockingSearchClient,
        )
        task = asyncio.create_task(web_search.ainvoke({"query": "可取消搜索"}))
        assert await asyncio.to_thread(search_started.wait, 1)

        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            # asyncio.to_thread 无法杀死线程；放行它以保持测试进程干净。
            allow_search_to_finish.set()

    asyncio.run(scenario())
