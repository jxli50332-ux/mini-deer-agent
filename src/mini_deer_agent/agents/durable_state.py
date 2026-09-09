"""定义摘要之外仍需精确保留的结构化 Agent 状态。"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


DELEGATION_LEDGER_MAX_ENTRIES = 50
SKILL_CONTEXT_MAX_ENTRIES = 8
_TERMINAL_DELEGATION_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "timed_out"}
)


class DelegationEntry(TypedDict):
    """一条受控子 Agent 委派的确定性台账记录。"""

    id: str
    turn_id: str
    description: str
    subagent_type: str
    status: Literal[
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "timed_out",
    ]
    result_brief: NotRequired[str]
    result_sha256: NotRequired[str]
    error_code: NotRequired[str]
    stop_reason: NotRequired[str]
    started_at: NotRequired[str]
    finished_at: NotRequired[str]
    duration_ms: NotRequired[int]
    input_tokens: NotRequired[int]
    output_tokens: NotRequired[int]
    total_tokens: NotRequired[int]
    model_calls: NotRequired[int]


class SkillContextEntry(TypedDict):
    """已加载内置技能的引用；正文和工具权限不进入此状态。"""

    name: str
    description: str
    path: str
    source: Literal["explicit", "automatic"]
    turn_id: str


class TodoStateItem(TypedDict):
    """任务清单中一项经过工具 Schema 校验的稳定快照。"""

    content: str
    status: Literal["pending", "in_progress", "completed"]


class TodoSnapshot(TypedDict):
    """最近一次成功 write_todos 调用提交的完整清单。"""

    turn_id: str
    items: list[TodoStateItem]


class PromotedToolState(TypedDict):
    """当前目录版本下已经显式发现并获准绑定的工具名称。"""

    catalog_hash: str
    names: list[str]


class GoalEvaluationState(TypedDict):
    """一次独立 Goal 完成评估的结构化结果。"""

    satisfied: bool
    blocker: Literal[
        "none",
        "missing_evidence",
        "needs_user_input",
        "run_failed",
        "external_wait",
        "goal_not_met_yet",
    ]
    reason: str
    evidence_summary: str
    evaluated_at: str


class GoalState(TypedDict):
    """持久化在线程 checkpoint 中的 Goal mode 控制状态。"""

    version: Literal[1]
    revision: str
    objective: str
    continuation_count: int
    max_continuations: int
    no_progress_count: int
    last_evaluation: GoalEvaluationState | None
    status: Literal["active", "paused", "stopped", "completed"]
    stop_reason: str | None
    context_anchor_message_id: NotRequired[str | None]
    created_at: str
    updated_at: str


def merge_delegations(
    existing: list[DelegationEntry] | None,
    new: list[DelegationEntry] | None,
) -> list[DelegationEntry]:
    """按调用 ID 合并台账，终态不回退，并只保留最近 50 条。"""
    if not new:
        return list(existing or [])

    by_id: dict[str, DelegationEntry] = {}
    order: list[str] = []
    for raw_entry in [*(existing or []), *new]:
        entry = dict(raw_entry)
        entry_id = entry["id"]
        previous = by_id.get(entry_id)
        if (
            previous is not None
            and previous["status"] in _TERMINAL_DELEGATION_STATUSES
            and entry["status"] not in _TERMINAL_DELEGATION_STATUSES
        ):
            continue
        if entry_id not in by_id:
            order.append(entry_id)
        by_id[entry_id] = entry  # type: ignore[assignment]

    merged = [by_id[entry_id] for entry_id in order]
    return merged[-DELEGATION_LEDGER_MAX_ENTRIES:]


def merge_skill_context(
    existing: list[SkillContextEntry] | None,
    new: list[SkillContextEntry] | None,
) -> list[SkillContextEntry]:
    """按用户回合和技能名去重，刷新引用后只保留最近八条。"""
    if not new:
        return list(existing or [])

    by_key: dict[tuple[str, str], SkillContextEntry] = {}
    order: list[tuple[str, str]] = []
    for raw_entry in [*(existing or []), *new]:
        entry = dict(raw_entry)
        key = (entry["turn_id"], entry["name"])
        if key in by_key:
            order.remove(key)
        order.append(key)
        by_key[key] = entry  # type: ignore[assignment]

    merged = [by_key[key] for key in order]
    return merged[-SKILL_CONTEXT_MAX_ENTRIES:]


def merge_todos(
    existing: TodoSnapshot | None,
    new: TodoSnapshot | None,
) -> TodoSnapshot | None:
    """节点未更新时保留旧快照，成功的新完整快照直接替换。"""
    if new is None:
        return existing
    return {
        "turn_id": new["turn_id"],
        "items": [dict(item) for item in new["items"]],  # type: ignore[misc]
    }
