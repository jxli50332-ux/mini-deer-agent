"""使用固定 Agent 消息离线演示 Mini Deer 的 SSE 帧协议。"""

import sys

from langchain_core.messages import AIMessageChunk, ToolMessage

from mini_deer_agent.streaming import AgentMessageEvent, iter_sse_frames


def main() -> None:
    """把正文增量、工具参数和工具结果编码后逐帧打印。"""
    # 显式使用 UTF-8，避免 Windows 管道或命令捕获器按本地代码页误解中文。
    sys.stdout.reconfigure(encoding="utf-8")
    # 固定事件只用于观察协议格式，不会访问模型或天气服务。
    events: list[AgentMessageEvent] = [
        (
            AIMessageChunk(
                content="正在查询北京天气。",
                id="message-demo-model-1",
                tool_call_chunks=[
                    {
                        "name": "get_weather",
                        "args": '{"city":"北京"}',
                        "id": "call-demo-weather-1",
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            ),
            {"langgraph_node": "model"},
        ),
        (
            ToolMessage(
                content="北京当前天气：雷暴，温度 24°C。",
                name="get_weather",
                tool_call_id="call-demo-weather-1",
                id="message-demo-tool-1",
            ),
            {"langgraph_node": "tools"},
        ),
    ]

    for frame in iter_sse_frames(events):
        # frame 已自带协议空行，end="" 可避免额外插入无意义换行。
        print(frame, end="")


if __name__ == "__main__":
    # 直接运行本文件时输出演示帧，导入模块不会执行任何操作。
    main()
