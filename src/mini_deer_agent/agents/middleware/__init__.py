"""提供进入模型前的消息协议修复与其他 Agent 中间层能力。"""

from mini_deer_agent.agents.middleware.context_summary import (
    ContextSummarizer,
    ContextSummaryPolicy,
    ContextSummaryResult,
    SummaryContextProjection,
    project_context_summary,
)
from mini_deer_agent.agents.middleware.dynamic_context import (
    DynamicContextClock,
    current_local_datetime,
    project_dynamic_context,
)
from mini_deer_agent.agents.middleware.durable_context import (
    DurableContextCapture,
    DurableContextProjection,
    capture_durable_context,
    current_turn_skill_name,
    latest_human_turn_id,
    project_durable_context,
)
from mini_deer_agent.agents.middleware.model_messages import prepare_model_messages
from mini_deer_agent.agents.middleware.tool_history import (
    repair_tool_call_message_history,
)
from mini_deer_agent.agents.middleware.tool_results import (
    TOOL_RESULT_META_KEY,
    ToolResultMeta,
    attach_tool_result_meta,
    awrap_tool_call,
    normalize_tool_message,
    tool_result_meta,
    wrap_tool_call,
)
from mini_deer_agent.agents.middleware.loop_detection import (
    LOOP_CAPPED_REASON,
    LOOP_STOP_REASON_KEY,
    ToolLoopDetector,
    ToolLoopPolicy,
    loop_finalize_messages,
    mark_loop_capped,
    tool_call_signature,
)
from mini_deer_agent.agents.middleware.tool_progress import (
    ToolProgressPolicy,
    ToolProgressTracker,
)
from mini_deer_agent.agents.middleware.tool_output_budget import (
    TOOL_OUTPUT_META_KEY,
    RunOutputError,
    RunOutputStore,
    ToolOutputBudget,
    ToolOutputBudgetPolicy,
    ToolOutputMeta,
    create_run_output_read_tool,
)
from mini_deer_agent.agents.middleware.run_budget import (
    RUN_USAGE_KEY,
    BudgetStopReason,
    RunBudgetPolicy,
    RunBudgetTracker,
    RunUsageSnapshot,
    ScopedRunBudgetTracker,
)


__all__ = [
    "ContextSummarizer",
    "ContextSummaryPolicy",
    "ContextSummaryResult",
    "LOOP_CAPPED_REASON",
    "LOOP_STOP_REASON_KEY",
    "TOOL_OUTPUT_META_KEY",
    "RUN_USAGE_KEY",
    "BudgetStopReason",
    "DynamicContextClock",
    "DurableContextCapture",
    "DurableContextProjection",
    "SummaryContextProjection",
    "current_local_datetime",
    "capture_durable_context",
    "current_turn_skill_name",
    "TOOL_RESULT_META_KEY",
    "ToolResultMeta",
    "ToolLoopDetector",
    "ToolLoopPolicy",
    "ToolProgressPolicy",
    "ToolProgressTracker",
    "RunOutputError",
    "RunOutputStore",
    "RunBudgetPolicy",
    "RunBudgetTracker",
    "RunUsageSnapshot",
    "ScopedRunBudgetTracker",
    "ToolOutputBudget",
    "ToolOutputBudgetPolicy",
    "ToolOutputMeta",
    "attach_tool_result_meta",
    "awrap_tool_call",
    "create_run_output_read_tool",
    "normalize_tool_message",
    "tool_result_meta",
    "wrap_tool_call",
    "latest_human_turn_id",
    "loop_finalize_messages",
    "mark_loop_capped",
    "prepare_model_messages",
    "project_context_summary",
    "project_dynamic_context",
    "project_durable_context",
    "repair_tool_call_message_history",
    "tool_call_signature",
]
