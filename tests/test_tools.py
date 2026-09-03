"""验证真实天气工具的模型契约、HTTP 流程和输入校验。"""

import asyncio

import httpx
import pytest

from mini_deer_agent.tools import get_agent_tools, get_skill_tools, get_weather


def test_weather_is_registered_only_as_a_skill_specialized_tool() -> None:
    """被动主 Agent 不暴露天气能力，专用注册表则只包含天气工具。"""
    assert "get_weather" not in tuple(tool.name for tool in get_agent_tools())
    assert tuple(tool.name for tool in get_skill_tools()) == ("get_weather",)


def test_get_weather_exposes_model_visible_contract() -> None:
    """工具应向模型公开稳定名称、用途说明和 city 字符串参数。"""
    schema = get_weather.args_schema.model_json_schema()

    assert get_weather.name == "get_weather"
    assert get_weather.description.startswith("查询城市当前天气")
    assert schema["required"] == ["city"]
    assert schema["properties"]["city"] == {
        "description": "要查询的城市名称",
        "title": "City",
        "type": "string",
    }


def test_get_weather_requests_location_then_current_weather(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """工具应先解析城市坐标，再用坐标请求当前天气。"""
    requested_hosts: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        """返回可重复的 API 响应，并记录工具实际访问的服务。"""
        requested_hosts.append(request.url.host)
        if request.url.host == "geocoding-api.open-meteo.com":
            assert request.url.params["name"] == "北京"
            assert request.url.params["language"] == "zh"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "北京",
                            "latitude": 39.9042,
                            "longitude": 116.4074,
                            "country": "中国",
                            "timezone": "Asia/Shanghai",
                        }
                    ]
                },
            )

        assert request.url.host == "api.open-meteo.com"
        assert request.url.params["latitude"] == "39.9042"
        assert request.url.params["longitude"] == "116.4074"
        assert request.url.params["timezone"] == "auto"
        return httpx.Response(
            200,
            json={
                "current": {
                    "time": "2026-08-24T15:00",
                    "temperature_2m": 30.2,
                    "apparent_temperature": 31.1,
                    "weather_code": 2,
                    "wind_speed_10m": 11.5,
                },
                "current_units": {
                    "temperature_2m": "°C",
                    "apparent_temperature": "°C",
                    "wind_speed_10m": "km/h",
                },
            },
        )

    # MockTransport 保留完整 HTTP 请求流程，但不访问外网或依赖服务状态。
    transport = httpx.MockTransport(handle_request)
    monkeypatch.setattr(
        "mini_deer_agent.tools.weather._create_http_client",
        lambda: httpx.Client(transport=transport),
    )

    result = get_weather.invoke({"city": "  北京  "})

    assert requested_hosts == [
        "geocoding-api.open-meteo.com",
        "api.open-meteo.com",
    ]
    assert result == (
        "北京（中国）当前天气：多云；温度 30.2°C，体感 31.1°C，"
        "10 米风速 11.5 km/h；数据时间 2026-08-24T15:00"
        "（Asia/Shanghai）；来源 Open-Meteo。"
    )


def test_get_weather_rejects_unknown_city(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """地理编码没有结果时，应返回用户可以理解的城市错误。"""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"results": []})
    )
    monkeypatch.setattr(
        "mini_deer_agent.tools.weather._create_http_client",
        lambda: httpx.Client(transport=transport),
    )

    with pytest.raises(ValueError, match="未找到城市：不存在的地方"):
        get_weather.invoke({"city": "不存在的地方"})


def test_get_weather_rejects_blank_city() -> None:
    """空城市没有查询语义，应在工具内部立即拒绝。"""
    with pytest.raises(ValueError, match="city 不能为空"):
        get_weather.invoke({"city": "   "})


def test_async_weather_request_is_actually_cancellable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Web Run 取消必须抵达正在等待的异步天气 HTTP，而不是只取消外层等待。"""

    async def scenario() -> None:
        """在 MockTransport 等待点取消工具任务并观察 CancelledError。"""
        request_started = asyncio.Event()
        cancel_observed = asyncio.Event()

        async def handle_request(_request: httpx.Request) -> httpx.Response:
            """保持首个请求在可取消 await 中。"""
            request_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancel_observed.set()
                raise
            raise AssertionError("无限等待不应正常结束")

        transport = httpx.MockTransport(handle_request)
        monkeypatch.setattr(
            "mini_deer_agent.tools.weather._create_async_http_client",
            lambda: httpx.AsyncClient(transport=transport),
        )

        task = asyncio.create_task(get_weather.ainvoke({"city": "北京"}))
        await request_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancel_observed.is_set()

    asyncio.run(scenario())
