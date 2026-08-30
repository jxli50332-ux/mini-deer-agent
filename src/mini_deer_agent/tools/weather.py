"""提供查询真实当前天气的 Open-Meteo 工具。"""

from typing import Annotated, Any

import httpx
from langchain_core.tools import StructuredTool


_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_CURRENT_WEATHER_FIELDS = (
    "temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
)


def _create_http_client() -> httpx.Client:
    """创建带超时和调用方标识的天气 API 客户端。"""
    # 有限超时避免外部服务异常时让 Agent 永久卡在工具节点。
    return httpx.Client(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "mini-deer-agent/0.1"},
    )


def _create_async_http_client() -> httpx.AsyncClient:
    """创建可响应 asyncio 取消的异步天气 API 客户端。"""
    return httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "mini-deer-agent/0.1"},
    )


def _request_json(
    client: httpx.Client,
    url: str,
    params: dict[str, object],
) -> dict[str, Any]:
    """发送 GET 请求，并把成功响应校验为 JSON 对象。"""
    response = client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("天气服务返回了无效的 JSON 结构")
    return payload


async def _request_json_async(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, object],
) -> dict[str, Any]:
    """异步发送 GET 请求，使 Run 取消可以中断外部天气调用。"""
    response = await client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("天气服务返回了无效的 JSON 结构")
    return payload


def _weather_code_to_text(weather_code: object) -> str:
    """把 Open-Meteo 使用的 WMO 天气代码转换为简短中文。"""
    code = int(weather_code)
    if code == 0:
        return "晴"
    if code == 1:
        return "晴间多云"
    if code == 2:
        return "多云"
    if code == 3:
        return "阴"
    if code in {45, 48}:
        return "雾"
    if code in {51, 53, 55}:
        return "毛毛雨"
    if code in {56, 57}:
        return "冻毛毛雨"
    if code in {61, 63, 65}:
        return "雨"
    if code in {66, 67}:
        return "冻雨"
    if code in {71, 73, 75, 77}:
        return "降雪"
    if code in {80, 81, 82}:
        return "阵雨"
    if code in {85, 86}:
        return "阵雪"
    if code in {95, 96, 99}:
        return "雷暴"
    return f"未知天气代码（{code}）"


def _extract_location(location_payload: dict[str, Any], city: str) -> dict[str, Any]:
    """校验地理编码结果，并返回第一条可用城市记录。"""
    locations = location_payload.get("results")
    if not isinstance(locations, list) or not locations:
        raise ValueError(f"未找到城市：{city}")

    location = locations[0]
    if not isinstance(location, dict):
        raise RuntimeError("地理编码服务返回了无效的城市数据")
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if not isinstance(latitude, int | float) or not isinstance(
        longitude, int | float
    ):
        raise RuntimeError("地理编码结果缺少有效经纬度")
    return location


def _format_current_weather(
    city: str,
    location: dict[str, Any],
    weather_payload: dict[str, Any],
) -> str:
    """把已经校验的城市和天气响应格式化为模型易读文本。"""
    current = weather_payload.get("current")
    if not isinstance(current, dict):
        raise RuntimeError("天气服务响应缺少 current 数据")
    required_fields = {
        "time",
        "temperature_2m",
        "apparent_temperature",
        "weather_code",
        "wind_speed_10m",
    }
    missing_fields = sorted(required_fields.difference(current))
    if missing_fields:
        raise RuntimeError(f"天气服务响应缺少字段：{', '.join(missing_fields)}")

    units = weather_payload.get("current_units")
    units = units if isinstance(units, dict) else {}
    place_name = str(location.get("name") or city)
    country = str(location.get("country") or "").strip()
    place = f"{place_name}（{country}）" if country else place_name
    timezone = str(
        location.get("timezone") or weather_payload.get("timezone") or "当地时区"
    )

    return (
        f"{place}当前天气：{_weather_code_to_text(current['weather_code'])}；"
        f"温度 {current['temperature_2m']}"
        f"{units.get('temperature_2m', '°C')}，"
        f"体感 {current['apparent_temperature']}"
        f"{units.get('apparent_temperature', '°C')}，"
        f"10 米风速 {current['wind_speed_10m']}"
        f" {units.get('wind_speed_10m', 'km/h')}；"
        f"数据时间 {current['time']}（{timezone}）；来源 Open-Meteo。"
    )


def _fetch_current_weather(city: str, client: httpx.Client) -> str:
    """同步解析城市坐标并查询天气，供 CLI 与源码学习示例使用。"""
    location_payload = _request_json(
        client,
        _GEOCODING_URL,
        {"name": city, "count": 1, "language": "zh", "format": "json"},
    )
    location = _extract_location(location_payload, city)
    latitude = location["latitude"]
    longitude = location["longitude"]

    weather_payload = _request_json(
        client,
        _FORECAST_URL,
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": _CURRENT_WEATHER_FIELDS,
            "timezone": "auto",
        },
    )
    return _format_current_weather(city, location, weather_payload)


async def _fetch_current_weather_async(
    city: str,
    client: httpx.AsyncClient,
) -> str:
    """异步解析城市坐标并查询天气，供可取消的 Web Run 使用。"""
    location_payload = await _request_json_async(
        client,
        _GEOCODING_URL,
        {"name": city, "count": 1, "language": "zh", "format": "json"},
    )
    location = _extract_location(location_payload, city)
    weather_payload = await _request_json_async(
        client,
        _FORECAST_URL,
        {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": _CURRENT_WEATHER_FIELDS,
            "timezone": "auto",
        },
    )
    return _format_current_weather(city, location, weather_payload)


def _get_weather(city: Annotated[str, "要查询的城市名称"]) -> str:
    """查询城市当前天气，实时请求 Open-Meteo 数据。"""
    # 清理模型可能附带的首尾空格，避免相同城市因格式差异查询失败。
    normalized_city = city.strip()
    if not normalized_city:
        raise ValueError("city 不能为空")

    # 每次工具调用独立管理客户端，结束后立即关闭网络连接相关资源。
    with _create_http_client() as client:
        return _fetch_current_weather(normalized_city, client)


async def _get_weather_async(city: Annotated[str, "要查询的城市名称"]) -> str:
    """异步查询城市当前天气，支持服务端 Run 主动取消。"""
    normalized_city = city.strip()
    if not normalized_city:
        raise ValueError("city 不能为空")

    # AsyncClient 的等待点会接收 CancelledError，不让取消停留在数据库表面。
    async with _create_async_http_client() as client:
        return await _fetch_current_weather_async(normalized_city, client)


# StructuredTool 同时保留 func 和 coroutine，兼容同步课程示例与异步生产链路。
get_weather = StructuredTool.from_function(
    func=_get_weather,
    coroutine=_get_weather_async,
    name="get_weather",
    description="查询城市当前天气，实时请求 Open-Meteo 数据。",
)
