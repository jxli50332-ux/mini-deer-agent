"""提供受控 task 委派工具，把独立任务并发交给受限子 Agent。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING, Annotated

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import (
    BaseTool,
    InjectedToolArg,
    InjectedToolCallId,
    StructuredTool,
)
from pydantic import Field, StringConstraints


if TYPE_CHECKING:
    from mini_deer_agent.agents.middleware import (
        ContextSummaryPolicy,
        DynamicContextClock,
        RunBudgetTracker,
        ToolOutputBudgetPolicy,
    )
    from mini_deer_agent.agents.subagent.registry import (
        SubagentConfig,
        SubagentRegistry,
    )
    from mini_deer_agent.skills import BuiltInSkillCatalog
    from mini_deer_agent.deferred_tools import DeferredToolCatalog


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
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    Field(
        description=(
            "专用子 Agent 类型：research、project-reader 或 test-runner"
        )
    ),
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
    *,
    description: str,
    subagent_type: str,
    result: str,
    lifecycle: dict[str, object] | None = None,
    stop_reason: str | None = None,
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
            **(lifecycle or {}),
            **({"stop_reason": stop_reason} if stop_reason is not None else {}),
        },
        ensure_ascii=False,
        indent=2,
    )


def _render_failure(
    *,
    description: str,
    subagent_type: str,
    error_code: str,
    message: str,
    lifecycle: dict[str, object] | None = None,
    status: str = "failed",
    stop_reason: str | None = None,
    last_result: str | None = None,
) -> str:
    """渲染不暴露内部异常细节的稳定失败结果。"""
    return json.dumps(
        {
            "version": 1,
            "kind": "subagent_result",
            "status": status,
            "subagent_type": subagent_type,
            "description": description,
            "error_code": error_code,
            "message": message,
            **(lifecycle or {}),
            **({"stop_reason": stop_reason} if stop_reason is not None else {}),
            **({"last_result": last_result} if last_result is not None else {}),
        },
        ensure_ascii=False,
        indent=2,
    )


def _utc_timestamp() -> str:
    """生成可持久化且不依赖本地时区的生命周期时间。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _usage_payload(tracker: RunBudgetTracker) -> dict[str, int]:
    """把当前子任务的独立计量快照转换为稳定 JSON。"""
    snapshot = tracker.snapshot()
    return {
        "input_tokens": snapshot.input_tokens,
        "output_tokens": snapshot.output_tokens,
        "total_tokens": snapshot.total_tokens,
        "model_calls": snapshot.model_calls,
    }


def _lifecycle_payload(
    *,
    started_at: str,
    started_perf: float,
    tracker: RunBudgetTracker,
) -> dict[str, object]:
    """在任意终态生成时间、耗时和本子任务 Token 用量。"""
    return {
        "started_at": started_at,
        "finished_at": _utc_timestamp(),
        "duration_ms": max(0, round((perf_counter() - started_perf) * 1000)),
        "usage": _usage_payload(tracker),
    }


def create_task_failure_message(
    *,
    tool_call_id: str,
    description: str,
    error_code: str,
    message: str,
    subagent_type: str = "unknown",
) -> ToolMessage:
    """创建一个不泄露内部异常的标准 task 失败结果。"""
    return ToolMessage(
        content=_render_failure(
            description=description,
            subagent_type=subagent_type,
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
    tool_output_policy: ToolOutputBudgetPolicy | None = None,
    run_budget_tracker: RunBudgetTracker | None = None,
    registry: SubagentRegistry | None = None,
    parent_tools: tuple[BaseTool, ...] | None = None,
    skill_catalog: BuiltInSkillCatalog | None = None,
    deferred_tool_catalog: DeferredToolCatalog | None = None,
) -> StructuredTool:
    """为单个已编译主图创建共享 Run 总量预算的 task 工具。"""
    from mini_deer_agent.agents.subagent.registry import (
        DEFAULT_SUBAGENT_REGISTRY,
    )

    active_budget = budget or DelegationBudget()
    active_registry = registry or DEFAULT_SUBAGENT_REGISTRY
    parent_tool_names = (
        tuple(tool.name for tool in parent_tools)
        if parent_tools is not None
        else ()
    )
    if len(parent_tool_names) != len(set(parent_tool_names)):
        raise ValueError("parent_tools contains duplicate names")

    def effective_tools(
        config: SubagentConfig,
        active_skill_name: str | None,
    ) -> tuple[BaseTool, ...] | None:
        """计算父能力、角色白名单和活动 Skill 白名单的严格交集。"""
        if parent_tools is None:
            return None
        role_tools = set(config.tools) - set(config.disallowed_tools)
        if active_skill_name is not None:
            skill = (
                skill_catalog.get(active_skill_name)
                if skill_catalog is not None
                else None
            )
            if skill is None:
                role_tools.clear()
            elif skill.allowed_tools is not None:
                role_tools.intersection_update(skill.allowed_tools)
        return tuple(tool for tool in parent_tools if tool.name in role_tools)

    def limit_message(
        description: str,
        subagent_type: SubagentType,
        tool_call_id: str,
    ) -> ToolMessage:
        """返回超过当前 Run 委派总量的稳定协议错误。"""
        return create_task_failure_message(
            tool_call_id=tool_call_id,
            description=description,
            error_code="delegation_limit_reached",
            message="当前 Run 已达到子 Agent 委派总量上限。",
            subagent_type=subagent_type,
        )

    def unknown_type_message(
        description: str,
        subagent_type: str,
        tool_call_id: str,
    ) -> ToolMessage:
        """未知名称必须以稳定工具错误返回，不能隐式退回其他角色。"""
        return create_task_failure_message(
            tool_call_id=tool_call_id,
            description=description,
            error_code="unknown_subagent_type",
            message=(
                "未知子 Agent 类型；可用类型："
                + "、".join(active_registry.names)
                + "。"
            ),
            subagent_type=subagent_type,
        )

    def execute_task(
        description: TaskDescription,
        prompt: TaskPrompt,
        subagent_type: SubagentType,
        tool_call_id: Annotated[str, InjectedToolCallId],
        active_skill_name: Annotated[str | None, InjectedToolArg] = None,
    ) -> ToolMessage:
        """同步解析并执行一次明确命名的专用子 Agent 任务。"""
        config = active_registry.get(subagent_type)
        if config is None:
            return unknown_type_message(description, subagent_type, tool_call_id)
        if not active_budget.claim(tool_call_id):
            return limit_message(description, subagent_type, tool_call_id)
        started_at = _utc_timestamp()
        started_perf = perf_counter()
        from mini_deer_agent.agents.middleware import RunBudgetTracker
        from mini_deer_agent.agents.subagent import SubagentProgress

        child_budget_tracker = (
            run_budget_tracker.child_scope()
            if run_budget_tracker is not None
            else RunBudgetTracker()
        )
        execution_progress = SubagentProgress()
        try:
            # 延迟导入可避免 tools 与主 Agent 包初始化时形成循环依赖。
            from mini_deer_agent.agents.subagent import run_subagent

            subagent_options: dict[str, object] = {"config": config}
            selected_tools = effective_tools(config, active_skill_name)
            if selected_tools is not None:
                subagent_options["available_tools"] = selected_tools
            if dynamic_context_clock is not None:
                subagent_options["dynamic_context_clock"] = dynamic_context_clock
            if context_summary_policy is not None:
                subagent_options["context_summary_policy"] = context_summary_policy
            if summary_model is not None:
                subagent_options["summary_model"] = summary_model
            if tool_output_policy is not None:
                subagent_options["tool_output_policy"] = tool_output_policy
            if deferred_tool_catalog is not None:
                from mini_deer_agent.agents.subagent import DEFERRED_TOOL_WILDCARD

                if DEFERRED_TOOL_WILDCARD in config.tools:
                    subagent_options["deferred_tool_catalog"] = deferred_tool_catalog
            subagent_options["run_budget_tracker"] = child_budget_tracker
            subagent_options["execution_progress"] = execution_progress
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
            return ToolMessage(
                content=_render_failure(
                    description=description,
                    subagent_type=subagent_type,
                    error_code="subagent_execution_failed",
                    message="子 Agent 执行失败，未返回完整结果。",
                    lifecycle=_lifecycle_payload(
                        started_at=started_at,
                        started_perf=started_perf,
                        tracker=child_budget_tracker,
                    ),
                    stop_reason="execution_failed",
                    last_result=execution_progress.snapshot(),
                ),
                tool_call_id=tool_call_id,
                name="task",
                status="error",
            )
        return ToolMessage(
            content=_render_success(
                description=description,
                subagent_type=subagent_type,
                result=str(result.content if hasattr(result, "content") else result),
                lifecycle=_lifecycle_payload(
                    started_at=started_at,
                    started_perf=started_perf,
                    tracker=child_budget_tracker,
                ),
                stop_reason=getattr(result, "stop_reason", None),
            ),
            tool_call_id=tool_call_id,
            name="task",
        )

    async def async_execute_task(
        description: TaskDescription,
        prompt: TaskPrompt,
        subagent_type: SubagentType,
        tool_call_id: Annotated[str, InjectedToolCallId],
        active_skill_name: Annotated[str | None, InjectedToolArg] = None,
    ) -> ToolMessage:
        """异步执行一次隔离任务，并允许取消信号自然向子图传播。"""
        config = active_registry.get(subagent_type)
        if config is None:
            return unknown_type_message(description, subagent_type, tool_call_id)
        if not active_budget.claim(tool_call_id):
            return limit_message(description, subagent_type, tool_call_id)
        started_at = _utc_timestamp()
        started_perf = perf_counter()
        from mini_deer_agent.agents.middleware import RunBudgetTracker
        from mini_deer_agent.agents.subagent import SubagentProgress

        child_budget_tracker = (
            run_budget_tracker.child_scope()
            if run_budget_tracker is not None
            else RunBudgetTracker()
        )
        execution_progress = SubagentProgress()
        logger.info(
            "子 Agent 开始执行：tool_call_id=%s description=%s",
            tool_call_id,
            description,
        )
        try:
            # 与同步入口保持相同的延迟导入边界。
            from mini_deer_agent.agents.subagent import async_run_subagent

            subagent_options: dict[str, object] = {"config": config}
            selected_tools = effective_tools(config, active_skill_name)
            if selected_tools is not None:
                subagent_options["available_tools"] = selected_tools
            if dynamic_context_clock is not None:
                subagent_options["dynamic_context_clock"] = dynamic_context_clock
            if context_summary_policy is not None:
                subagent_options["context_summary_policy"] = context_summary_policy
            if summary_model is not None:
                subagent_options["summary_model"] = summary_model
            if tool_output_policy is not None:
                subagent_options["tool_output_policy"] = tool_output_policy
            if deferred_tool_catalog is not None:
                from mini_deer_agent.agents.subagent import DEFERRED_TOOL_WILDCARD

                if DEFERRED_TOOL_WILDCARD in config.tools:
                    subagent_options["deferred_tool_catalog"] = deferred_tool_catalog
            subagent_options["run_budget_tracker"] = child_budget_tracker
            subagent_options["execution_progress"] = execution_progress
            async with asyncio.timeout(config.timeout_seconds):
                result = await async_run_subagent(
                    model,
                    prompt,
                    **subagent_options,
                )
        except asyncio.CancelledError:
            logger.info(
                "子 Agent 随父 Run 取消：tool_call_id=%s",
                tool_call_id,
            )
            raise
        except TimeoutError:
            logger.warning(
                "子 Agent 执行超时：tool_call_id=%s timeout_seconds=%d",
                tool_call_id,
                config.timeout_seconds,
            )
            return ToolMessage(
                content=_render_failure(
                    description=description,
                    subagent_type=subagent_type,
                    error_code="subagent_timed_out",
                    message=(
                        f"子 Agent 在 {config.timeout_seconds} 秒内未完成，已取消。"
                    ),
                    lifecycle=_lifecycle_payload(
                        started_at=started_at,
                        started_perf=started_perf,
                        tracker=child_budget_tracker,
                    ),
                    status="timed_out",
                    stop_reason="timeout",
                    last_result=execution_progress.snapshot(),
                ),
                tool_call_id=tool_call_id,
                name="task",
                status="error",
            )
        except Exception as exc:
            logger.exception(
                "子 Agent 执行失败：error_type=%s",
                type(exc).__name__,
                extra={"tool_call_id": tool_call_id},
            )
            return ToolMessage(
                content=_render_failure(
                    description=description,
                    subagent_type=subagent_type,
                    error_code="subagent_execution_failed",
                    message="子 Agent 执行失败，未返回完整结果。",
                    lifecycle=_lifecycle_payload(
                        started_at=started_at,
                        started_perf=started_perf,
                        tracker=child_budget_tracker,
                    ),
                    stop_reason="execution_failed",
                    last_result=execution_progress.snapshot(),
                ),
                tool_call_id=tool_call_id,
                name="task",
                status="error",
            )
        logger.info(
            "子 Agent 执行成功：tool_call_id=%s result_chars=%d",
            tool_call_id,
            len(result.content if hasattr(result, "content") else result),
        )
        return ToolMessage(
            content=_render_success(
                description=description,
                subagent_type=subagent_type,
                result=str(result.content if hasattr(result, "content") else result),
                lifecycle=_lifecycle_payload(
                    started_at=started_at,
                    started_perf=started_perf,
                    tracker=child_budget_tracker,
                ),
                stop_reason=getattr(result, "stop_reason", None),
            ),
            tool_call_id=tool_call_id,
            name="task",
        )

    return StructuredTool.from_function(
        func=execute_task,
        coroutine=async_execute_task,
        name="task",
        description=(
            "把一个自包含、可独立并发完成的任务委派给明确命名的专用子 Agent。"
            "subagent_type 必须是 research、project-reader 或 test-runner；"
            "未知名称稳定失败且不回退。"
            "每次响应最多并发三个，当前 Run 累计最多调用六次；task 批次必须独占响应。"
            "实际工具由服务端注册配置决定，返回结果后由主 Agent 核验。"
        ),
    )
