"""构建 Mini Deer 主 Agent 的 LangGraph 状态图。"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, Literal

from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from mini_deer_agent.agents.middleware import (
    ContextSummarizer,
    ContextSummaryPolicy,
    ContextSummaryResult,
    DynamicContextClock,
    capture_durable_context,
    current_turn_skill_name,
    current_local_datetime,
    latest_human_turn_id,
    prepare_model_messages,
    project_dynamic_context,
)
from mini_deer_agent.agents.durable_state import (
    DelegationEntry,
    SkillContextEntry,
    TodoSnapshot,
    merge_delegations,
    merge_skill_context,
    merge_todos,
)
from mini_deer_agent.agents.state import MiniDeerAgentState
from mini_deer_agent.agents.prompts import (
    AgentPromptBuilder,
    AgentPromptContext,
    DefaultAgentPromptBuilder,
)
from mini_deer_agent.llms import create_chat_model
from mini_deer_agent.core import Settings
from mini_deer_agent.skills import (
    SKILL_ACTIVATION_TOOL_NAME,
    BuiltInSkillCatalog,
    SkillToolPolicyDecision,
    create_skill_activation_tool,
    find_automatic_skill_name,
    parse_slash_skill_reference,
    project_skill_activation,
    project_skill_tool_policy,
    resolve_skill_tool_policy,
    validate_skill_tool_policies,
)
from mini_deer_agent.tools import (
    ask_clarification,
    create_memory_tools,
    create_task_tool,
    get_agent_tools,
    get_skill_tools,
)
from mini_deer_agent.tools.task import (
    MAX_CONCURRENT_DELEGATIONS,
    DelegationBudget,
    create_task_failure_message,
)

if TYPE_CHECKING:
    from mini_deer_agent.application.memory import MemoryStore


def route_after_model(
    state: MiniDeerAgentState,
    *,
    skill_catalog: BuiltInSkillCatalog | None = None,
    passive_tool_names: tuple[str, ...] = (),
    execution_tool_names: tuple[str, ...] = (),
) -> Literal[
    "clarification",
    "skill_activation",
    "skill_policy_block",
    "delegation",
    "tools",
    "__end__",
]:
    """按澄清、技能激活、委派、普通工具的优先级选择下一节点。"""
    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []
    if any(call.get("name") == "ask_clarification" for call in tool_calls):
        return "clarification"
    if any(call.get("name") == SKILL_ACTIVATION_TOOL_NAME for call in tool_calls):
        return "skill_activation"
    if skill_catalog is not None and tool_calls:
        decision = _skill_policy_decision(
            state,
            catalog=skill_catalog,
            passive_tool_names=passive_tool_names,
            execution_tool_names=execution_tool_names,
        )
        allowed_names = set(decision.allowed_tool_names)
        if any(call.get("name") not in allowed_names for call in tool_calls):
            return "skill_policy_block"
    if any(call.get("name") == "task" for call in tool_calls):
        return "delegation"
    # 普通工具继续复用 LangGraph 的标准条件，避免维护第二份路由规则。
    return tools_condition(state)


def _skill_policy_decision(
    state: MiniDeerAgentState,
    *,
    catalog: BuiltInSkillCatalog,
    passive_tool_names: tuple[str, ...],
    execution_tool_names: tuple[str, ...],
) -> SkillToolPolicyDecision:
    """从当前 Run 的可信激活投影解析模型与执行端共享的权限。"""
    messages = state["messages"]
    turn_id = latest_human_turn_id(messages)
    projection = project_skill_activation(
        SystemMessage(content=""),
        messages,
        catalog,
        durable_skill_name=current_turn_skill_name(
            state.get("skill_context", []),
            turn_id,
        ),
    )
    return resolve_skill_tool_policy(
        active_skill_name=projection.skill_name,
        catalog=catalog,
        passive_tool_names=passive_tool_names,
        execution_tool_names=execution_tool_names,
    )


def _skipped_tool_message(
    tool_call: dict,
    *,
    reason: str,
    message: str,
) -> ToolMessage:
    """补齐未执行的并列工具调用，防止留下悬空协议状态。"""
    tool_call_id = tool_call.get("id")
    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
        raise RuntimeError("Tool call is missing a stable ID")
    name = tool_call.get("name")
    tool_name = (
        name.strip() if isinstance(name, str) and name.strip() else "unknown_tool"
    )
    content = json.dumps(
        {
            "version": 1,
            "kind": "tool_call_skipped",
            "reason": reason,
            "message": message,
        },
        ensure_ascii=False,
        indent=2,
    )
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        name=tool_name,
        status="error",
    )


def _blocked_tool_message(
    tool_call: dict,
    *,
    message: str,
) -> ToolMessage:
    """为模型伪造或越权的工具调用生成稳定、可审计的拒绝结果。"""
    tool_call_id = _required_tool_call_id(tool_call)
    name = tool_call.get("name")
    tool_name = (
        name.strip() if isinstance(name, str) and name.strip() else "unknown_tool"
    )
    content = json.dumps(
        {
            "version": 1,
            "kind": "tool_call_blocked",
            "reason": "skill_tool_not_allowed",
            "message": message,
        },
        ensure_ascii=False,
        indent=2,
    )
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        name=tool_name,
        status="error",
    )


def skill_policy_block_node(
    state: MiniDeerAgentState,
    *,
    catalog: BuiltInSkillCatalog,
    passive_tool_names: tuple[str, ...],
    execution_tool_names: tuple[str, ...],
) -> dict[str, list[BaseMessage]]:
    """拒绝含越权调用的整个批次，避免同批其他工具产生部分副作用。"""
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise RuntimeError("Skill policy node requires an AIMessage")
    decision = _skill_policy_decision(
        state,
        catalog=catalog,
        passive_tool_names=passive_tool_names,
        execution_tool_names=execution_tool_names,
    )
    allowed_names = set(decision.allowed_tool_names)
    active_scope = (
        f"技能 `{decision.active_skill_name}` 的 allowed-tools 策略"
        if decision.restricted and decision.active_skill_name is not None
        else "当前 Run 的工具策略"
    )
    results: list[BaseMessage] = []
    for tool_call in last_message.tool_calls:
        if tool_call.get("name") not in allowed_names:
            results.append(
                _blocked_tool_message(
                    tool_call,
                    message=f"{active_scope}不允许执行该工具。",
                )
            )
            continue
        results.append(
            _skipped_tool_message(
                tool_call,
                reason="skill_policy_batch_rejected",
                message="同批包含未授权工具，本次未执行任何工具。",
            )
        )
    return {"messages": results}


def clarification_node(state: MessagesState) -> dict[str, list[BaseMessage]]:
    """生成一个可持久化的澄清结果，并安全收敛同批所有工具调用。"""
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise RuntimeError("Clarification node requires an AIMessage")

    clarification_index = next(
        (
            index
            for index, call in enumerate(last_message.tool_calls)
            if call.get("name") == "ask_clarification"
        ),
        None,
    )
    if clarification_index is None:
        raise RuntimeError("Clarification node requires ask_clarification")

    results: list[BaseMessage] = []
    for index, tool_call in enumerate(last_message.tool_calls):
        if index != clarification_index:
            # 一次只允许提出一个澄清；并列普通工具和多余澄清都不执行。
            results.append(
                _skipped_tool_message(
                    tool_call,
                    reason="clarification_requested",
                    message="等待用户回答澄清问题，本次 Run 未执行该工具。",
                )
            )
            continue
        result = ask_clarification.invoke(tool_call)
        if not isinstance(result, ToolMessage):
            raise RuntimeError("ask_clarification must return a ToolMessage")
        results.append(result)
    return {"messages": results}


def _latest_explicit_skill_name(
    messages: list[BaseMessage],
    catalog: BuiltInSkillCatalog,
) -> str | None:
    """解析最新可见用户消息中的有效 slash，供自动激活节点执行优先级。"""
    target = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, HumanMessage)
        ),
        None,
    )
    if target is None or (target.additional_kwargs or {}).get("hide_from_ui") is True:
        return None
    if not isinstance(target.content, str):
        return None
    reference = parse_slash_skill_reference(target.content)
    if reference is None or catalog.get(reference.name) is None:
        return None
    return reference.name


def _requested_skill_name(tool_call: dict) -> str | None:
    """读取激活请求中的精确技能名，非法参数留给节点生成稳定错误。"""
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return None
    name = args.get("name")
    return name if isinstance(name, str) and name else None


def skill_activation_node(
    state: MiniDeerAgentState,
    *,
    activation_tool: BaseTool,
    catalog: BuiltInSkillCatalog,
) -> dict[str, list[BaseMessage]]:
    """执行首个自主激活调用，并安全结算本批全部并列调用。"""
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise RuntimeError("Skill activation node requires an AIMessage")
    activation_index = next(
        (
            index
            for index, call in enumerate(last_message.tool_calls)
            if call.get("name") == SKILL_ACTIVATION_TOOL_NAME
        ),
        None,
    )
    if activation_index is None:
        raise RuntimeError("Skill activation node requires activate_skill")

    previous_messages = state["messages"][:-1]
    explicit_name = _latest_explicit_skill_name(previous_messages, catalog)
    active_name = find_automatic_skill_name(previous_messages, catalog)
    if active_name is None:
        active_name = current_turn_skill_name(
            state.get("skill_context", []),
            latest_human_turn_id(previous_messages),
        )
    results: list[BaseMessage] = []
    for index, tool_call in enumerate(last_message.tool_calls):
        if index != activation_index:
            results.append(
                _skipped_tool_message(
                    tool_call,
                    reason="skill_activation_requested",
                    message=(
                        "技能激活必须独占模型响应，本批未执行其他工具。"
                    ),
                )
            )
            continue
        if explicit_name is not None:
            results.append(
                _skipped_tool_message(
                    tool_call,
                    reason="explicit_skill_active",
                    message=(
                        f"当前 Run 已由用户显式激活 `{explicit_name}`，"
                        "不能再自动激活技能。"
                    ),
                )
            )
            continue
        requested_name = _requested_skill_name(tool_call)
        if active_name is not None and requested_name != active_name:
            results.append(
                _skipped_tool_message(
                    tool_call,
                    reason="skill_activation_conflict",
                    message=(
                        f"当前 Run 已自动激活 `{active_name}`，不能切换或叠加技能。"
                    ),
                )
            )
            continue
        try:
            result = activation_tool.invoke(tool_call)
        except Exception:
            # 参数校验错误是可恢复的模型调用问题，不能让整个产品 Run 崩溃。
            results.append(
                _skipped_tool_message(
                    tool_call,
                    reason="invalid_skill_activation_call",
                    message="技能激活参数不合法，本次未激活技能。",
                )
            )
            continue
        if not isinstance(result, ToolMessage):
            raise RuntimeError("activate_skill must return a ToolMessage")
        results.append(result)
    return {"messages": results}


def _required_tool_call_id(tool_call: dict) -> str:
    """读取可用于预算和协议关联的稳定工具调用 ID。"""
    tool_call_id = tool_call.get("id")
    if not isinstance(tool_call_id, str) or not tool_call_id.strip():
        raise RuntimeError("Tool call is missing a stable ID")
    return tool_call_id


def _delegation_calls(state: MessagesState) -> tuple[AIMessage, list[int]]:
    """读取最后一次模型响应，并定位本批全部 task 调用。"""
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        raise RuntimeError("Delegation node requires an AIMessage")
    task_indices = [
        index
        for index, call in enumerate(last_message.tool_calls)
        if call.get("name") == "task"
    ]
    if not task_indices:
        raise RuntimeError("Delegation node requires task")
    return last_message, task_indices


def _task_description(tool_call: dict) -> str:
    """从不可信工具参数中提取有界说明，用于稳定失败结果。"""
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return "无效委派"
    description = args.get("description")
    if not isinstance(description, str) or not description.strip():
        return "无效委派"
    return description.strip()[:200]


def _task_invocation_failure(tool_call: dict) -> ToolMessage:
    """把工具参数或运行时包装错误转换为可交给主模型的失败结果。"""
    return create_task_failure_message(
        tool_call_id=_required_tool_call_id(tool_call),
        description=_task_description(tool_call),
        error_code="invalid_task_call",
        message="子 Agent 委派参数无效或无法启动。",
    )


def _invoke_task_call(task_tool: BaseTool, tool_call: dict) -> ToolMessage:
    """同步执行单个已获预算的 task，并隔离该调用自身的包装错误。"""
    try:
        result = task_tool.invoke(tool_call)
    except Exception:
        return _task_invocation_failure(tool_call)
    if not isinstance(result, ToolMessage):
        return _task_invocation_failure(tool_call)
    return result


async def _async_invoke_task_call(
    task_tool: BaseTool,
    tool_call: dict,
) -> ToolMessage:
    """异步执行单个 task；CancelledError 不会被普通异常包装吞掉。"""
    try:
        result = await task_tool.ainvoke(tool_call)
    except Exception:
        return _task_invocation_failure(tool_call)
    if not isinstance(result, ToolMessage):
        return _task_invocation_failure(tool_call)
    return result


def _prepare_delegation_batch(
    state: MessagesState,
    budget: DelegationBudget,
) -> tuple[AIMessage, list[int], str]:
    """按响应并发上限和 Run 剩余总量选择有序 task 批次。"""
    last_message, task_indices = _delegation_calls(state)
    task_call_ids = [
        _required_tool_call_id(last_message.tool_calls[index])
        for index in task_indices
    ]
    reservation = budget.reserve_batch(
        task_call_ids,
        max_concurrent=MAX_CONCURRENT_DELEGATIONS,
    )
    accepted_count = len(reservation.allowed_tool_call_ids)
    accepted_indices = task_indices[:accepted_count]
    # 并发上限先于总量上限判断；只有剩余总量不足以填满合法批次时才标记总量耗尽。
    legal_batch_size = min(len(task_indices), MAX_CONCURRENT_DELEGATIONS)
    rejected_reason = (
        "delegation_total_limit"
        if reservation.remaining_before < legal_batch_size
        else "delegation_concurrency_limit"
    )
    return last_message, accepted_indices, rejected_reason


def _merge_delegation_results(
    last_message: AIMessage,
    accepted_indices: list[int],
    executed_results: list[ToolMessage],
    rejected_reason: str,
) -> dict[str, list[BaseMessage]]:
    """按原始 ToolCall 顺序合并成功、失败和跳过结果。"""
    executed_by_index = dict(
        zip(accepted_indices, executed_results, strict=True)
    )
    results: list[BaseMessage] = []
    for index, tool_call in enumerate(last_message.tool_calls):
        executed = executed_by_index.get(index)
        if executed is not None:
            results.append(executed)
            continue
        if tool_call.get("name") != "task":
            results.append(
                _skipped_tool_message(
                    tool_call,
                    reason="delegation_batch_exclusive",
                    message="task 并发批次必须独占模型响应，本批未执行普通工具。",
                )
            )
            continue
        message = (
            "本次响应最多并发执行三个子 Agent，超额 task 未执行。"
            if rejected_reason == "delegation_concurrency_limit"
            else "当前 Run 已达到六次子 Agent 委派总量，超额 task 未执行。"
        )
        results.append(
            _skipped_tool_message(
                tool_call,
                reason=rejected_reason,
                message=message,
            )
        )
    return {"messages": results}


def delegation_node(
    state: MessagesState,
    task_tool: BaseTool,
    budget: DelegationBudget,
) -> dict[str, list[BaseMessage]]:
    """使用有界线程池并发执行本批 task，再按原顺序返回主模型。"""
    last_message, accepted_indices, rejected_reason = _prepare_delegation_batch(
        state,
        budget,
    )
    accepted_calls = [last_message.tool_calls[index] for index in accepted_indices]
    if accepted_calls:
        with ThreadPoolExecutor(
            max_workers=len(accepted_calls),
            thread_name_prefix="mini-deer-subagent",
        ) as executor:
            executed_results = list(
                executor.map(
                    lambda call: _invoke_task_call(task_tool, call),
                    accepted_calls,
                )
            )
    else:
        executed_results = []
    return _merge_delegation_results(
        last_message,
        accepted_indices,
        executed_results,
        rejected_reason,
    )


async def async_delegation_node(
    state: MessagesState,
    task_tool: BaseTool,
    budget: DelegationBudget,
) -> dict[str, list[BaseMessage]]:
    """使用 gather 并发等待本批 task，使取消传播到全部活动子图。"""
    last_message, accepted_indices, rejected_reason = _prepare_delegation_batch(
        state,
        budget,
    )
    accepted_calls = [last_message.tool_calls[index] for index in accepted_indices]
    executed_results = list(
        await asyncio.gather(
            *(
                _async_invoke_task_call(task_tool, tool_call)
                for tool_call in accepted_calls
            )
        )
    )
    return _merge_delegation_results(
        last_message,
        accepted_indices,
        executed_results,
        rejected_reason,
    )


def _model_request_with_skill_policy(
    *,
    model: Runnable[LanguageModelInput, BaseMessage],
    projected_system_message: SystemMessage,
    active_skill_name: str | None,
    skill_catalog: BuiltInSkillCatalog | None,
    passive_tools: tuple[BaseTool, ...] | None,
    execution_tools: tuple[BaseTool, ...] | None,
) -> tuple[Runnable[LanguageModelInput, BaseMessage], SystemMessage]:
    """为一次模型调用绑定实际工具 schema，并投影同源权限说明。"""
    if skill_catalog is None or passive_tools is None or execution_tools is None:
        return model, projected_system_message

    passive_tool_names = tuple(tool.name for tool in passive_tools)
    execution_tool_names = tuple(tool.name for tool in execution_tools)
    decision = resolve_skill_tool_policy(
        active_skill_name=active_skill_name,
        catalog=skill_catalog,
        passive_tool_names=passive_tool_names,
        execution_tool_names=execution_tool_names,
    )
    allowed_names = set(decision.allowed_tool_names)
    visible_tools = tuple(
        tool for tool in execution_tools if tool.name in allowed_names
    )
    bind_tools = getattr(model, "bind_tools", None)
    if not callable(bind_tools):
        raise TypeError("Policy-aware model must support bind_tools")
    request_model = bind_tools(visible_tools)
    request_system_message = project_skill_tool_policy(
        projected_system_message,
        decision,
    )
    return request_model, request_system_message


def _model_state_update(
    response: BaseMessage,
    compaction: ContextSummaryResult | None,
    *,
    delegations: list[DelegationEntry],
    skill_context: list[SkillContextEntry],
    todos: TodoSnapshot | None,
) -> dict[str, object]:
    """原子保存消息、摘要和从本次请求/响应捕获的结构化状态。"""
    durable_update: dict[str, object] = {}
    if delegations:
        durable_update["delegations"] = delegations
    if skill_context:
        durable_update["skill_context"] = skill_context
    if todos is not None:
        durable_update["todos"] = todos
    if compaction is None:
        return {"messages": [response], **durable_update}
    return {
        "messages": [
            RemoveMessage(id=REMOVE_ALL_MESSAGES),
            *compaction.preserved_messages,
            response,
        ],
        "summary_text": compaction.summary_text,
        **durable_update,
    }


def _durable_context_values(
    state: MiniDeerAgentState,
    catalog: BuiltInSkillCatalog | None,
    *,
    response: BaseMessage | None = None,
) -> tuple[
    list[DelegationEntry],
    list[SkillContextEntry],
    TodoSnapshot | None,
    str | None,
]:
    """合并 checkpoint 与当前消息证据，供同次投影和原子状态更新复用。"""
    messages = [*state["messages"]]
    if response is not None:
        messages.append(response)
    capture = capture_durable_context(messages, catalog)
    delegations = merge_delegations(
        state.get("delegations"),
        list(capture.delegations),
    )
    skill_context = merge_skill_context(
        state.get("skill_context"),
        list(capture.skill_context),
    )
    todos = merge_todos(state.get("todos"), capture.todos)
    return (
        delegations,
        skill_context,
        todos,
        latest_human_turn_id(messages),
    )


def model_node(
    state: MiniDeerAgentState,
    model: Runnable[LanguageModelInput, BaseMessage],
    system_message: SystemMessage,
    skill_catalog: BuiltInSkillCatalog | None = None,
    passive_tools: tuple[BaseTool, ...] | None = None,
    execution_tools: tuple[BaseTool, ...] | None = None,
    dynamic_context_clock: DynamicContextClock | None = None,
    context_summarizer: ContextSummarizer | None = None,
) -> dict[str, object]:
    """必要时压缩旧历史，再把安全投影后的上下文交给模型。"""
    delegations, skill_context, todos, current_turn_id = (
        _durable_context_values(state, skill_catalog)
    )
    compaction = (
        context_summarizer.compact(
            state["messages"],
            previous_summary=state.get("summary_text"),
        )
        if context_summarizer is not None
        else None
    )
    working_messages = (
        list(compaction.preserved_messages)
        if compaction is not None
        else state["messages"]
    )
    active_summary = (
        compaction.summary_text
        if compaction is not None
        else state.get("summary_text")
    )
    skill_projection = project_skill_activation(
        system_message,
        working_messages,
        skill_catalog,
        durable_skill_name=current_turn_skill_name(
            skill_context,
            current_turn_id,
        ),
    )
    if skill_projection.failure_message is not None:
        # slash 命令错误属于确定性产品边界，不应让模型猜测或消耗一次请求。
        return _model_state_update(
            AIMessageChunk(content=skill_projection.failure_message),
            compaction,
            delegations=delegations,
            skill_context=skill_context,
            todos=todos,
        )
    request_model, request_system_message = _model_request_with_skill_policy(
        model=model,
        projected_system_message=skill_projection.system_message,
        active_skill_name=skill_projection.skill_name,
        skill_catalog=skill_catalog,
        passive_tools=passive_tools,
        execution_tools=execution_tools,
    )
    if dynamic_context_clock is not None:
        # 动态事实放在技能与权限之后统一合并，且只存在于本次模型请求。
        request_system_message = project_dynamic_context(
            request_system_message,
            clock=dynamic_context_clock,
        )
    # Prompt、权限和工具历史都只投影到本次模型请求，不写入 checkpoint。
    model_messages = prepare_model_messages(
        request_system_message,
        skill_projection.messages,
        summary_text=active_summary,
        delegations=delegations,
        skill_context=skill_context,
        todos=todos,
        current_turn_id=current_turn_id,
    )
    response = request_model.invoke(model_messages)

    # 压缩成功时由 MessagesState reducer 先清空旧历史，再保留近期窗口和公开响应。
    updated_delegations, updated_skills, updated_todos, _ = (
        _durable_context_values(state, skill_catalog, response=response)
    )
    return _model_state_update(
        response,
        compaction,
        delegations=updated_delegations,
        skill_context=updated_skills,
        todos=updated_todos,
    )


async def async_model_node(
    state: MiniDeerAgentState,
    model: Runnable[LanguageModelInput, BaseMessage],
    system_message: SystemMessage,
    skill_catalog: BuiltInSkillCatalog | None = None,
    passive_tools: tuple[BaseTool, ...] | None = None,
    execution_tools: tuple[BaseTool, ...] | None = None,
    dynamic_context_clock: DynamicContextClock | None = None,
    context_summarizer: ContextSummarizer | None = None,
) -> dict[str, object]:
    """异步调用模型，使 Web Run 可以通过取消 asyncio Task 中断等待。"""
    delegations, skill_context, todos, current_turn_id = (
        _durable_context_values(state, skill_catalog)
    )
    compaction = (
        await context_summarizer.acompact(
            state["messages"],
            previous_summary=state.get("summary_text"),
        )
        if context_summarizer is not None
        else None
    )
    working_messages = (
        list(compaction.preserved_messages)
        if compaction is not None
        else state["messages"]
    )
    active_summary = (
        compaction.summary_text
        if compaction is not None
        else state.get("summary_text")
    )
    skill_projection = project_skill_activation(
        system_message,
        working_messages,
        skill_catalog,
        durable_skill_name=current_turn_skill_name(
            skill_context,
            current_turn_id,
        ),
    )
    if skill_projection.failure_message is not None:
        return _model_state_update(
            AIMessageChunk(content=skill_projection.failure_message),
            compaction,
            delegations=delegations,
            skill_context=skill_context,
            todos=todos,
        )
    request_model, request_system_message = _model_request_with_skill_policy(
        model=model,
        projected_system_message=skill_projection.system_message,
        active_skill_name=skill_projection.skill_name,
        skill_catalog=skill_catalog,
        passive_tools=passive_tools,
        execution_tools=execution_tools,
    )
    if dynamic_context_clock is not None:
        request_system_message = project_dynamic_context(
            request_system_message,
            clock=dynamic_context_clock,
        )
    # 不能把同步 invoke 放进线程池冒充异步；ainvoke 才能把取消传播到模型 HTTP 请求。
    model_messages = prepare_model_messages(
        request_system_message,
        skill_projection.messages,
        summary_text=active_summary,
        delegations=delegations,
        skill_context=skill_context,
        todos=todos,
        current_turn_id=current_turn_id,
    )
    response = await request_model.ainvoke(model_messages)
    updated_delegations, updated_skills, updated_todos, _ = (
        _durable_context_values(state, skill_catalog, response=response)
    )
    return _model_state_update(
        response,
        compaction,
        delegations=updated_delegations,
        skill_context=updated_skills,
        todos=updated_todos,
    )


def build_agent_graph(
    model: BaseChatModel | None = None,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    prompt_builder: AgentPromptBuilder | None = None,
    prompt_context: AgentPromptContext | None = None,
    skill_catalog: BuiltInSkillCatalog | None = None,
    dynamic_context_clock: DynamicContextClock | None = None,
    context_summary_policy: ContextSummaryPolicy | None = None,
    summary_model: BaseChatModel | None = None,
    memory_store: MemoryStore | None = None,
    mcp_tools: tuple[BaseTool, ...] = (),
) -> CompiledStateGraph:
    """绑定模型、Prompt、工具和可选状态存储，并编译条件循环。"""
    # 显式参数供测试注入假模型；正常运行时才从项目配置创建真实模型。
    settings = Settings() if model is None else None
    chat_model = model if model is not None else create_chat_model(settings)
    resolved_summary_policy = context_summary_policy or ContextSummaryPolicy(
        enabled=(settings.context_summary_enabled if settings is not None else True),
        trigger_tokens=(
            settings.context_summary_trigger_tokens
            if settings is not None
            else 24_000
        ),
        trigger_messages=(
            settings.context_summary_trigger_messages
            if settings is not None
            else 40
        ),
        keep_messages=(
            settings.context_summary_keep_messages
            if settings is not None
            else 10
        ),
        input_tokens=(
            settings.context_summary_input_tokens
            if settings is not None
            else 12_000
        ),
    )
    # 每个产品 Run 使用一次稳定快照；技能文件更新只影响之后的新 Run。
    resolved_skill_catalog = (
        skill_catalog
        if skill_catalog is not None
        else BuiltInSkillCatalog.discover()
    )
    resolved_dynamic_context_clock = (
        dynamic_context_clock or current_local_datetime
    )
    # 每次构图只读取一次注册表，确保模型契约和工具执行节点使用完全相同的集合。
    delegation_budget = DelegationBudget()
    task_tool = create_task_tool(
        chat_model,
        budget=delegation_budget,
        dynamic_context_clock=dynamic_context_clock,
        context_summary_policy=(
            resolved_summary_policy
            if settings is not None or context_summary_policy is not None
            else None
        ),
        summary_model=summary_model,
    )
    # 即使目录为空也保留一个仅供防御路由执行的闭包；模型注册表不会暴露它。
    runtime_activation_tool = create_skill_activation_tool(resolved_skill_catalog)
    model_activation_tool = (
        runtime_activation_tool if resolved_skill_catalog.skills else None
    )
    memory_tools = (
        create_memory_tools(memory_store) if memory_store is not None else ()
    )
    passive_tools = get_agent_tools(
        task_tool,
        model_activation_tool,
        extra_tools=(*memory_tools, *mcp_tools),
    )
    execution_tools = (*passive_tools, *get_skill_tools())
    passive_tool_names = tuple(tool.name for tool in passive_tools)
    execution_tool_names = tuple(tool.name for tool in execution_tools)
    if len(set(execution_tool_names)) != len(execution_tool_names):
        raise RuntimeError("Tool registry contains duplicate names")
    validate_skill_tool_policies(
        resolved_skill_catalog,
        execution_tool_names,
    )
    # 工具名称必须来自同一注册表，不能由请求或 Prompt 配置伪造模型能力。
    resolved_prompt_context = replace(
        prompt_context or AgentPromptContext(),
        available_tool_names=passive_tool_names,
        available_skills=resolved_skill_catalog.summaries,
    )
    built_prompt = (prompt_builder or DefaultAgentPromptBuilder()).build(
        resolved_prompt_context
    )
    context_summarizer = ContextSummarizer(
        summary_model or chat_model,
        resolved_summary_policy,
        base_system_message=built_prompt.system_message,
    )
    # 共享状态在标准消息 reducer 之外持久化累计摘要，不把内部摘要伪装成产品消息。
    builder = StateGraph(MiniDeerAgentState)
    # 同一 Runnable 同时提供同步和异步实现：学习脚本可继续 invoke，Web 使用 ainvoke。
    model_runnable = RunnableLambda(
        partial(
            model_node,
            model=chat_model,
            system_message=built_prompt.system_message,
            skill_catalog=resolved_skill_catalog,
            passive_tools=passive_tools,
            execution_tools=execution_tools,
            dynamic_context_clock=resolved_dynamic_context_clock,
            context_summarizer=context_summarizer,
        ),
        afunc=partial(
            async_model_node,
            model=chat_model,
            system_message=built_prompt.system_message,
            skill_catalog=resolved_skill_catalog,
            passive_tools=passive_tools,
            execution_tools=execution_tools,
            dynamic_context_clock=resolved_dynamic_context_clock,
            context_summarizer=context_summarizer,
        ),
        name="mini_deer_model",
    )
    builder.add_node("model", model_runnable)
    # 执行注册表包含专用工具；条件路由会在进入 ToolNode 前复核同一权限决策。
    builder.add_node("tools", ToolNode(execution_tools))
    # 澄清节点不执行并列普通工具，生成问题后通过固定边结束当前图。
    builder.add_node("clarification", clarification_node)
    # 自动激活必须在独占节点落下可审计 ToolMessage，再回到模型获得技能正文。
    # 空目录时该节点仍能安全拒绝模型意外生成的未注册调用，保证条件图始终可编译。
    builder.add_node(
        "skill_activation",
        partial(
            skill_activation_node,
            activation_tool=runtime_activation_tool,
            catalog=resolved_skill_catalog,
        ),
    )
    builder.add_node(
        "skill_policy_block",
        partial(
            skill_policy_block_node,
            catalog=resolved_skill_catalog,
            passive_tool_names=passive_tool_names,
            execution_tool_names=execution_tool_names,
        ),
    )
    # task 使用专用节点执行受控并发批次，并让执行、失败和跳过调用全部收敛。
    builder.add_node(
        "delegation",
        RunnableLambda(
            partial(
                delegation_node,
                task_tool=task_tool,
                budget=delegation_budget,
            ),
            afunc=partial(
                async_delegation_node,
                task_tool=task_tool,
                budget=delegation_budget,
            ),
            name="mini_deer_delegation",
        ),
    )

    # 澄清和技能激活优先进入专用节点；其他工具和无工具响应保持原有语义。
    builder.add_edge(START, "model")
    builder.add_conditional_edges(
        "model",
        partial(
            route_after_model,
            skill_catalog=resolved_skill_catalog,
            passive_tool_names=passive_tool_names,
            execution_tool_names=execution_tool_names,
        ),
    )
    # 工具结果必须交回模型，第二次模型调用才能把结果组织成最终自然语言回答。
    builder.add_edge("tools", "model")
    builder.add_edge("skill_activation", "model")
    builder.add_edge("skill_policy_block", "model")
    # 子 Agent 同步返回 ToolMessage 后，主模型必须核验并组织最终回答。
    builder.add_edge("delegation", "model")
    # 第一版不挂起并恢复同一 Run；用户回答会在同一 Thread 创建新 Run。
    builder.add_edge("clarification", END)

    # Checkpointer 在每个图步骤保存状态；None 则保持原有的无状态调用方式。
    return builder.compile(checkpointer=checkpointer)
