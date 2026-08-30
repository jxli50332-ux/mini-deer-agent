"""使用真实 DeepSeek 和天气工具演示 LangGraph 节点级流式更新。"""

from langchain_core.messages import HumanMessage

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.streaming import stream_agent_updates


def main() -> None:
    """按节点完成顺序打印工具请求、工具结果和最终回答。"""
    # 创建使用当前环境配置、真实 DeepSeek 模型和真实天气工具的图。
    graph = build_agent_graph()
    # 示例文件由 Python 直接读取，不再经过 PowerShell 的管道或 -c 引号转换。
    prompt = "请必须调用 get_weather 工具查询北京当前天气，再根据工具结果用中文回答。"

    # 每次循环只处理当前刚完成节点产生的消息，不预先收集完整执行结果。
    for update in stream_agent_updates(
        graph,
        [HumanMessage(content=prompt)],
    ):
        node_name, node_update = next(iter(update.items()))
        message = node_update["messages"][-1]

        print(f"\n节点: {node_name}")
        print(f"消息类型: {type(message).__name__}")

        # 模型请求工具时单独显示结构化调用参数。
        if getattr(message, "tool_calls", None):
            print("工具请求:", message.tool_calls)

        # AI 最终回答和 ToolMessage 工具结果都保留原始文本。
        if message.text:
            print("消息内容:", message.text)


if __name__ == "__main__":
    # 直接运行本文件时才访问真实模型和天气接口，导入模块不会产生网络请求。
    main()
