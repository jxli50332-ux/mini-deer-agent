"""构建 Mini Deer 主 Agent 的 LangGraph 状态图。"""

from dataclasses import replace
from functools import partial

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from mini_deer_agent.agents.middleware import prepare_model_messages
from mini_deer_agent.agents.prompts import (
    AgentPromptBuilder,
    AgentPromptContext,
    DefaultAgentPromptBuilder,
)
from mini_deer_agent.llms import create_chat_model
from mini_deer_agent.tools import get_agent_tools


def model_node(
    state: MessagesState,
    model: Runnable[LanguageModelInput, BaseMessage],
    system_message: SystemMessage,
) -> dict[str, list[BaseMessage]]:
    """把状态中的完整消息历史交给模型，并返回模型生成的消息。"""
    # Prompt 与工具历史都只投影到本次模型请求，不作为普通消息写入 checkpoint。
    model_messages = prepare_model_messages(system_message, state["messages"])
    response = model.invoke(model_messages)

    # 节点只返回本次新增消息；MessagesState 的 reducer 会把它追加到原历史中。
    return {"messages": [response]}


async def async_model_node(
    state: MessagesState,
    model: Runnable[LanguageModelInput, BaseMessage],
    system_message: SystemMessage,
) -> dict[str, list[BaseMessage]]:
    """异步调用模型，使 Web Run 可以通过取消 asyncio Task 中断等待。"""
    # 不能把同步 invoke 放进线程池冒充异步；ainvoke 才能把取消传播到模型 HTTP 请求。
    model_messages = prepare_model_messages(system_message, state["messages"])
    response = await model.ainvoke(model_messages)
    return {"messages": [response]}


def build_agent_graph(
    model: BaseChatModel | None = None,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    prompt_builder: AgentPromptBuilder | None = None,
    prompt_context: AgentPromptContext | None = None,
) -> CompiledStateGraph:
    """绑定模型、Prompt、工具和可选状态存储，并编译条件循环。"""
    # 显式参数供测试注入假模型；正常运行时才从项目配置创建真实模型。
    chat_model = model if model is not None else create_chat_model()
    # 每次构图只读取一次注册表，确保模型契约和工具执行节点使用完全相同的集合。
    agent_tools = get_agent_tools()
    # 工具名称必须来自同一注册表，不能由请求或 Prompt 配置伪造模型能力。
    resolved_prompt_context = replace(
        prompt_context or AgentPromptContext(),
        available_tool_names=tuple(tool.name for tool in agent_tools),
    )
    built_prompt = (prompt_builder or DefaultAgentPromptBuilder()).build(
        resolved_prompt_context
    )
    # bind_tools 只把工具契约交给模型；模型返回请求后不会在这里执行函数。
    tool_model = chat_model.bind_tools(agent_tools)

    # StateGraph 只是结构构建器，MessagesState 规定所有节点共享的状态形状。
    builder = StateGraph(MessagesState)
    # 同一 Runnable 同时提供同步和异步实现：学习脚本可继续 invoke，Web 使用 ainvoke。
    model_runnable = RunnableLambda(
        partial(
            model_node,
            model=tool_model,
            system_message=built_prompt.system_message,
        ),
        afunc=partial(
            async_model_node,
            model=tool_model,
            system_message=built_prompt.system_message,
        ),
        name="mini_deer_model",
    )
    builder.add_node("model", model_runnable)
    # ToolNode 按 AIMessage.tool_calls 中的名称查找工具，并追加 ToolMessage。
    builder.add_node("tools", ToolNode(agent_tools))

    # 模型有工具请求时进入 tools；没有请求时 tools_condition 直接路由到 END。
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition)
    # 工具结果必须交回模型，第二次模型调用才能把结果组织成最终自然语言回答。
    builder.add_edge("tools", "model")

    # Checkpointer 在每个图步骤保存状态；None 则保持原有的无状态调用方式。
    return builder.compile(checkpointer=checkpointer)
