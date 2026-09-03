"""提供受控 task 委派工具，把独立任务并发交给受限子 Agent。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Annotated, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool
from pydantic import Field, StringConstraints


if TYPE_CHECKING:
    from mini_deer_agent.agents.middleware import (
        ContextSummaryPolicy,
        DynamicContextClock,
    )


logger = logging.getLogger(__name__)


# 单个模型响应最多并发三个子 Agent；同一产品 Run 最多累计六次委派。
MAX_CONCURRENT_DELEGATIONS = 3
MAX_TOTAL_DELEGATIONS_PER_RUN = 6

type TaskDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    Field(description="便于主 Agent 识别的简短任务说明"),
]
type TaskPrompt = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=8000),
    Field(description="包含目标、必要背景、输入和期望输出的自包含任务提示"),
]
type SubagentType = Annotated[
    Literal["general-purpose"],
    Field(description="受限子 Agent 类型，当前只支持 general-purpose"),
]


@dataclass(frozen=True)
class DelegationReservation:
    """一次模型响应获得的有序委派名额快照。"""

    allowed_tool_call_ids: tuple[str, ...]
    remaining_before: int


class DelegationBudget:
    """线程安全地维护一张主图在当前产品 Run 内的委派总量。"""

    def __init__(self, max_total: int = MAX_TOTAL_DELEGATIONS_PER_RUN) -> None:
        """创建正数总量预算；主图生命周期就是产品 Run 生命周期。"""
        if max_total < 1:
            raise ValueError("max_total must be positive")
        self._max_total = max_total
        self._used = 0
        self._reserved: dict[str, int] = {}
        self._lock = Lock()

    @property
    def remaining(self) -> int:
        """返回当前仍可启动的委派数量。"""
        with self._lock:
            return max(0, self._max_total - self._used)

    def reserve_batch(
        self,
        tool_call_ids: list[str],
        *,
        max_concurrent: int = MAX_CONCURRENT_DELEGATIONS,
    ) -> DelegationReservation:
        """按调用顺序为一个批次原子预留并发和总量名额。"""
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        with self._lock:
            remaining_before = max(0, self._max_total - self._used)
            allowed_count = min(
                len(tool_call_ids),
                max_concurrent,
                remaining_before,
            )
            allowed_ids = tuple(tool_call_ids[:allowed_count])
            self._used += allowed_count
            for tool_call_id in allowed_ids:
                self._reserved[tool_call_id] = (
                    self._reserved.get(tool_call_id, 0) + 1
                )
            return DelegationReservation(
                allowed_tool_call_ids=allowed_ids,
                remaining_before=remaining_before,
            )

    def claim(self, tool_call_id: str) -> bool:
        """消费预留名额；直接调用工具时则原子占用一个剩余名额。"""
        with self._lock:
            reserved_count = self._reserved.get(tool_call_id, 0)
            if reserved_count > 0:
                if reserved_count == 1:
                    del self._reserved[tool_call_id]
                else:
                    self._reserved[tool_call_id] = reserved_count - 1
                return True
            if self._used >= self._max_total:
                return False
            self._used += 1
            return True


def _render_success(
    *, description: str, subagent_type: SubagentType, result: str
) -> str:
    """渲染主 Agent 可稳定解析的成功结果。"""
    return json.dumps(
        {
            "version": 1,
            "kind": "subagent_result",
            "status": "completed",
            "subagent_type": subagent_type,
            "description": description,
            "result": result,
        },
        ensure_ascii=False,
        indent=2,
    )


def _render_failure(
    *,
    description: str,
    subagent_type: SubagentType,
    error_code: str,
    message: str,
) -> str:
    """渲染不暴露内部异常细节的稳定失败结果。"""
    return json.dumps(
        {
            "version": 1,
            "kind": "subagent_result",
            "status": "failed",
            "subagent_type": subagent_type,
            "description": description,
            "error_code": error_code,
            "message": message,
        },
        ensure_ascii=False,
        indent=2,
    )


def create_task_failure_message(
    *,
    tool_call_id: str,
    description: str,
    error_code: str,
    message: str,
) -> ToolMessage:
    """创建一个不泄露内部异常的标准 task 失败结果。"""
    return ToolMessage(
        content=_render_failure(
            description=description,
            subagent_type="general-purpose",
            error_code=error_code,
            message=message,
        ),
        tool_call_id=tool_call_id,
        name="task",
        status="error",
    )


def create_task_tool(
    model: BaseChatModel,
    *,
    budget: DelegationBudget | None = None,
    dynamic_context_clock: DynamicContextClock | None = None,
    context_summary_policy: ContextSummaryPolicy | None = None,
    summary_model: BaseChatModel | None = None,
) -> StructuredTool:
    """为单个已编译主图创建共享 Run 总量预算的 task 工具。"""
    active_budget = budget or DelegationBudget()

    def limit_message(
        description: str,
        subagent_type: SubagentType,
        tool_call_id: str,
    ) -> ToolMessage:
        """返回超过当前 Run 委派总量的稳定协议错误。"""
        del subagent_type
        return create_task_failure_message(
            tool_call_id=tool_call_id,
            description=description,
            error_code="delegation_limit_reached",
            message="当前 Run 已达到子 Agent 委派总量上限。",
        )

    def execute_task(
        description: TaskDescription,
        prompt: TaskPrompt,
        subagent_type: SubagentType,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> ToolMessage:
        """同步执行一次隔离的通用子 Agent 任务并返回结构化结果。"""
        if not active_budget.claim(tool_call_id):
            return limit_message(description, subagent_type, tool_call_id)
        try:
            # 延迟导入可避免 tools 与主 Agent 包初始化时形成循环依赖。
            from mini_deer_agent.agents.subagent import run_subagent

            subagent_options: dict[str, object] = {}
            if dynamic_context_clock is not None:
                subagent_options["dynamic_context_clock"] = dynamic_context_clock
            if context_summary_policy is not None:
                subagent_options["context_summary_policy"] = context_summary_policy
            if summary_model is not None:
                subagent_options["summary_model"] = summary_model
            if not subagent_options:
                result = run_subagent(model, prompt)
            else:
                result = run_subagent(model, prompt, **subagent_options)
        except Exception as exc:
            logger.exception(
                "子 Agent 执行失败：error_type=%s",
                type(exc).__name__,
                extra={"tool_call_id": tool_call_id},
            )
            return create_task_failure_message(
                tool_call_id=tool_call_id,
                description=description,
                error_code="subagent_execution_failed",
                message="子 Agent 执行失败，未返回可用结果。",
            )
        return ToolMessage(
            content=_render_success(
                description=description,
                subagent_type=subagent_type,
                result=result,
            ),
            tool_call_id=tool_call_id,
            name="task",
        )

    async def async_execute_task(
        description: TaskDescription,
        prompt: TaskPrompt,
        subagent_type: SubagentType,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> ToolMessage:
        """异步执行一次隔离任务，并允许取消信号自然向子图传播。"""
        if not active_budget.claim(tool_call_id):
            return limit_message(description, subagent_type, tool_call_id)
        logger.info(
            "子 Agent 开始执行：tool_call_id=%s description=%s",
            tool_call_id,
            description,
        )
        try:
            # 与同步入口保持相同的延迟导入边界。
            from mini_deer_agent.agents.subagent import async_run_subagent

            subagent_options: dict[str, object] = {}
            if dynamic_context_clock is not None:
                subagent_options["dynamic_context_clock"] = dynamic_context_clock
            if context_summary_policy is not None:
                subagent_options["context_summary_policy"] = context_summary_policy
            if summary_model is not None:
                subagent_options["summary_model"] = summary_model
            if not subagent_options:
                result = await async_run_subagent(model, prompt)
            else:
                result = await async_run_subagent(
                    model,
                    prompt,
                    **subagent_options,
                )
        except Exception as exc:
            logger.exception(
                "子 Agent 执行失败：error_type=%s",
                type(exc).__name__,
                extra={"tool_call_id": tool_call_id},
            )
            return create_task_failure_message(
                tool_call_id=tool_call_id,
                description=description,
                error_code="subagent_execution_failed",
                message="子 Agent 执行失败，未返回可用结果。",
            )
        logger.info(
            "子 Agent 执行成功：tool_call_id=%s result_chars=%d",
            tool_call_id,
            len(result),
        )
        return ToolMessage(
            content=_render_success(
                description=description,
                subagent_type=subagent_type,
                result=result,
            ),
            tool_call_id=tool_call_id,
            name="task",
        )

    return StructuredTool.from_function(
        func=execute_task,
        coroutine=async_execute_task,
        name="task",
        description=(
            "把一个自包含、可独立并发完成的任务同步委派给通用子 Agent。"
            "每次响应最多并发三个，当前 Run 累计最多调用六次；task 批次必须独占响应。"
            "子 Agent 只拥有 web_search 和 web_fetch，返回结果后由主 Agent 核验。"
        ),
    )
