"""把 Runtime 可信日期时间投影到单次模型请求。"""

import html
from collections.abc import Callable
from datetime import datetime

from langchain_core.messages import SystemMessage


type DynamicContextClock = Callable[[], datetime]

_WEEKDAYS = (
    "星期一 / Monday",
    "星期二 / Tuesday",
    "星期三 / Wednesday",
    "星期四 / Thursday",
    "星期五 / Friday",
    "星期六 / Saturday",
    "星期日 / Sunday",
)


def current_local_datetime() -> datetime:
    """返回带宿主本地时区和 UTC 偏移的当前时间。"""
    return datetime.now().astimezone()


def _format_utc_offset(value: datetime) -> str:
    """把 aware datetime 的 UTC 偏移渲染成稳定的 `UTC±HH:MM`。"""
    offset = value.utcoffset()
    if offset is None:
        raise ValueError("Dynamic context clock must return a timezone-aware datetime")
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    absolute_seconds = abs(total_seconds)
    hours, remainder = divmod(absolute_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    suffix = (
        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        if seconds
        else f"{hours:02d}:{minutes:02d}"
    )
    return f"UTC{sign}{suffix}"


def project_dynamic_context(
    system_message: SystemMessage,
    *,
    clock: DynamicContextClock = current_local_datetime,
) -> SystemMessage:
    """追加一次调用时刻的可信上下文，不修改原系统消息或对话状态。"""
    content = system_message.content
    if not isinstance(content, str):
        raise TypeError("Mini Deer system prompt must be text")
    current = clock()
    if not isinstance(current, datetime):
        raise TypeError("Dynamic context clock must return datetime")
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Dynamic context clock must return a timezone-aware datetime")

    # 秒足以回答交互式问题；去掉微秒可避免没有产品价值的 Prompt 抖动。
    rendered = current.replace(microsecond=0)
    timezone_name = html.escape(rendered.tzname() or "未命名本地时区", quote=False)
    context_block = "\n".join(
        [
            '<dynamic_context source="runtime">',
            "以下事实由 Runtime 根据宿主时钟生成，属于可信上下文。",
            f"<current_datetime>{rendered.isoformat()}</current_datetime>",
            f"<current_date>{rendered.date().isoformat()}</current_date>",
            f"<current_time>{rendered.time().isoformat()}</current_time>",
            f"<current_weekday>{_WEEKDAYS[rendered.weekday()]}</current_weekday>",
            f"<timezone_name>{timezone_name}</timezone_name>",
            f"<utc_offset>{_format_utc_offset(rendered)}</utc_offset>",
            "</dynamic_context>",
        ]
    )
    return system_message.model_copy(
        update={"content": f"{content}\n\n{context_block}"}
    )
