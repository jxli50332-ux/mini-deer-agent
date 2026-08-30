"""使用真实 DeepSeek 演示模型消息增量和工具结果流。"""

from langchain_core.messages import AIMessageChunk, HumanMessage, ToolMessage

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.streaming import stream_agent_messages


def main() -> None:
    """实时打印消息 chunk，并按消息 ID 累积最终文本。"""
    # 创建使用当前环境配置、真实 DeepSeek 模型和真实天气工具的图。
    graph = build_agent_graph()
    prompt = "请必须调用 get_weather 工具查询北京当前天气，再根据工具结果用中文回答。"
    text_by_message_id: dict[str, str] = {}
    current_node: str | None = None

    # messages 模式返回 (消息增量, metadata)，模型生成期间会多次进入循环。
    for message, metadata in stream_agent_messages(
        graph,
        [HumanMessage(content=prompt)],
    ):
        node_name = str(metadata.get("langgraph_node", "unknown"))
        if node_name != current_node:
            # 节点切换时换行，清楚区分模型生成和工具执行阶段。
            print(f"\n\n节点: {node_name}")
            current_node = node_name

        if isinstance(message, AIMessageChunk):
            if message.text:
                # end="" 和 flush=True 让每个文本增量抵达后立即显示。
                print(message.text, end="", flush=True)
                if message.id:
                    text_by_message_id[message.id] = (
                        text_by_message_id.get(message.id, "") + message.text
                    )

            if message.tool_call_chunks:
                # 工具名和 JSON 参数可能分成多个 chunk，因此先展示原始增量。
                print("\n工具调用增量:", message.tool_call_chunks, flush=True)
            continue

        if isinstance(message, ToolMessage):
            # ToolMessage 是完整工具结果，不是模型 token；保留关联 tool_call_id。
            print(f"工具结果({message.tool_call_id}): {message.text}", flush=True)

    print("\n\n按消息 ID 累积的完整模型文本:")
    for message_id, text in text_by_message_id.items():
        # 同一次模型调用的所有正文 chunk 应被拼回一段完整文本。
        print(f"- {message_id}: {text}")


if __name__ == "__main__":
    # 直接运行本文件时才访问真实服务，导入模块不会产生网络请求。
    main()
