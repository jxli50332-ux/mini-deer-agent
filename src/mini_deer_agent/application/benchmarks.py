"""组合固定能力基准目录、Event Store 指标和人工评分。"""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable
from typing import Literal, Protocol

from mini_deer_agent.domain import (
    BENCHMARK_CASES,
    BenchmarkAttempt,
    BenchmarkCase,
    BenchmarkScore,
    StoredRunEventRecord,
    require_benchmark_case,
)


@dataclass(frozen=True, slots=True)
class BenchmarkToolStep:
    """报告中的一次规范化工具请求。"""

    name: str
    arguments: str
    status: str


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    """只从持久化事件推导的可复现指标。"""

    tool_trajectory: tuple[BenchmarkToolStep, ...]
    repeated_tool_calls: int
    model_calls: int
    duration_ms: int | None
    final_check_result: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """固定案例、Run 生命周期、自动指标和人工评分的聚合视图。"""

    attempt: BenchmarkAttempt
    case: BenchmarkCase
    metrics: BenchmarkMetrics


type BenchmarkGateStatus = Literal["passed", "failed", "insufficient_data"]


@dataclass(frozen=True, slots=True)
class BenchmarkRegressionSnapshot:
    """一组固定案例在某个时间切片的聚合指标。"""

    run_count: int
    evaluated_complex_cases: int
    completed_complex_cases: int
    complex_completion_rate: float | None
    repeated_tool_calls: int
    simple_qa_tool_calls: int | None
    p95_duration_ms: int | None
    p95_total_tokens: int | None


@dataclass(frozen=True, slots=True)
class BenchmarkRegressionGates:
    """第 14 阶段四个退出条件的可解释判定。"""

    complex_completion: BenchmarkGateStatus
    convergence: BenchmarkGateStatus
    simple_tool_calls: BenchmarkGateStatus
    p95_duration: BenchmarkGateStatus
    p95_tokens: BenchmarkGateStatus


@dataclass(frozen=True, slots=True)
class BenchmarkRegressionSummary:
    """最早基线与每案例最新复测之间的固定口径比较。"""

    case_count: int
    rerun_case_count: int
    all_cases_rerun: bool
    baseline: BenchmarkRegressionSnapshot
    current: BenchmarkRegressionSnapshot
    gates: BenchmarkRegressionGates
    ready_to_close: bool


class BenchmarkStore(Protocol):
    """能力基准依赖的最小持久化端口。"""

    def list_benchmark_attempts(self, *, limit: int) -> tuple[BenchmarkAttempt, ...]: ...

    def get_benchmark_attempt(self, run_id: str) -> BenchmarkAttempt | None: ...

    def update_benchmark_score(
        self,
        run_id: str,
        *,
        task_completed: bool,
        score: int,
        notes: str | None,
    ) -> BenchmarkScore | None: ...

    def list_run_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        after_sequence: int,
        limit: int,
    ) -> tuple[StoredRunEventRecord, ...]: ...


def _canonical_arguments(value: object) -> str:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return " ".join(value.split())
        return json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _p95(values: list[int | None]) -> int | None:
    if not values or any(value is None for value in values):
        return None
    ordered = sorted(value for value in values if value is not None)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _snapshot(reports: list[BenchmarkReport]) -> BenchmarkRegressionSnapshot:
    complex_reports = [
        report
        for report in reports
        if report.case.category not in {"simple_qa", "clarification"}
    ]
    evaluated = [
        report
        for report in complex_reports
        if report.attempt.task_completed is not None
    ]
    completed = sum(report.attempt.task_completed is True for report in evaluated)
    simple = next(
        (report for report in reports if report.case.category == "simple_qa"),
        None,
    )
    return BenchmarkRegressionSnapshot(
        run_count=len(reports),
        evaluated_complex_cases=len(evaluated),
        completed_complex_cases=completed,
        complex_completion_rate=(completed / len(evaluated) if evaluated else None),
        repeated_tool_calls=sum(
            report.metrics.repeated_tool_calls for report in reports
        ),
        simple_qa_tool_calls=(
            len(simple.metrics.tool_trajectory) if simple is not None else None
        ),
        p95_duration_ms=_p95([report.metrics.duration_ms for report in reports]),
        p95_total_tokens=_p95(
            [report.metrics.total_tokens for report in reports]
        ),
    )


def _comparison_gate(
    baseline: int | float | None,
    current: int | float | None,
    *,
    predicate: Callable[[int | float, int | float], bool],
) -> BenchmarkGateStatus:
    if baseline is None or current is None:
        return "insufficient_data"
    return "passed" if predicate(baseline, current) else "failed"


def _duration_ms(attempt: BenchmarkAttempt) -> int | None:
    if attempt.started_at is None or attempt.finished_at is None:
        return None
    try:
        delta = datetime.fromisoformat(attempt.finished_at) - datetime.fromisoformat(attempt.started_at)
    except ValueError:
        return None
    return max(0, round(delta.total_seconds() * 1000))


def _metrics(
    attempt: BenchmarkAttempt,
    events: tuple[StoredRunEventRecord, ...],
) -> BenchmarkMetrics:
    calls: dict[str, dict[str, str]] = {}
    order: list[str] = []
    model_message_ids: set[str] = set()
    for event in events:
        if event.event in {"ai_delta", "tool_call_delta"} and event.message_id:
            model_message_ids.add(event.message_id)
        if event.event == "tool_call_delta":
            call_id = str(event.payload.get("tool_call_id") or event.message_id or event.sequence)
            if call_id not in calls:
                calls[call_id] = {
                    "name": "unknown",
                    "arguments": "",
                    "status": "pending",
                    "content": "",
                }
                order.append(call_id)
            step = calls[call_id]
            if event.payload.get("name") is not None:
                step["name"] = str(event.payload["name"])
            if event.payload.get("arguments_delta") is not None:
                step["arguments"] += str(event.payload["arguments_delta"])
        elif event.event == "tool_result":
            call_id = str(event.payload.get("tool_call_id") or event.message_id or event.sequence)
            if call_id not in calls:
                calls[call_id] = {
                    "name": str(event.payload.get("name") or "unknown"),
                    "arguments": "",
                    "status": "completed",
                    "content": "",
                }
                order.append(call_id)
            calls[call_id]["status"] = "completed"
            calls[call_id]["content"] = str(event.payload.get("content") or "")

    trajectory = tuple(
        BenchmarkToolStep(
            name=calls[call_id]["name"],
            arguments=_canonical_arguments(calls[call_id]["arguments"]),
            status=calls[call_id]["status"],
        )
        for call_id in order
    )
    signatures = [(step.name, step.arguments) for step in trajectory]
    repeated = sum(
        1 for previous, current in zip(signatures, signatures[1:], strict=False)
        if previous == current
    )
    check_call_ids = [
        call_id
        for call_id in order
        if calls[call_id]["name"] == "run_project_command"
    ]
    if not check_call_ids:
        check_result = "not_run"
    else:
        last_check = calls[check_call_ids[-1]]
        try:
            check_payload = json.loads(last_check["content"])
        except json.JSONDecodeError:
            check_payload = None
        check_result = (
            "passed"
            if isinstance(check_payload, dict)
            and check_payload.get("ok") is True
            and check_payload.get("exit_code") == 0
            else "failed"
        )
    return BenchmarkMetrics(
        tool_trajectory=trajectory,
        repeated_tool_calls=repeated,
        model_calls=(
            attempt.model_calls
            if attempt.model_calls is not None
            else len(model_message_ids)
        ),
        duration_ms=_duration_ms(attempt),
        final_check_result=check_result,
        input_tokens=attempt.input_tokens,
        output_tokens=attempt.output_tokens,
        total_tokens=attempt.total_tokens,
    )


class BenchmarkService:
    """提供案例目录和可复现报告，不触发额外模型调用。"""

    def __init__(self, store: BenchmarkStore) -> None:
        self._store = store

    def list_cases(self) -> tuple[BenchmarkCase, ...]:
        return BENCHMARK_CASES

    def list_reports(self, *, limit: int = 50) -> tuple[BenchmarkReport, ...]:
        return tuple(self._report(attempt) for attempt in self._store.list_benchmark_attempts(limit=limit))

    def get_report(self, run_id: str) -> BenchmarkReport | None:
        attempt = self._store.get_benchmark_attempt(run_id)
        return None if attempt is None else self._report(attempt)

    def regression_summary(self) -> BenchmarkRegressionSummary:
        """按案例最早/最新 Run 对比，缺数据时不伪造通过结论。"""
        attempts = self._store.list_benchmark_attempts(limit=10_000)
        grouped: dict[str, list[BenchmarkReport]] = {
            case.case_id: [] for case in BENCHMARK_CASES
        }
        for attempt in attempts:
            grouped[attempt.case_id].append(self._report(attempt))
        for reports in grouped.values():
            reports.sort(
                key=lambda report: (
                    report.attempt.created_at,
                    report.attempt.run_id,
                )
            )
        baseline_reports = [reports[0] for reports in grouped.values() if reports]
        current_reports = [reports[-1] for reports in grouped.values() if reports]
        rerun_case_count = sum(len(reports) >= 2 for reports in grouped.values())
        all_cases_rerun = rerun_case_count == len(BENCHMARK_CASES)
        baseline = _snapshot(baseline_reports)
        current = _snapshot(current_reports)
        complex_case_count = sum(
            case.category not in {"simple_qa", "clarification"}
            for case in BENCHMARK_CASES
        )
        completion_gate: BenchmarkGateStatus = "insufficient_data"
        if (
            all_cases_rerun
            and baseline.evaluated_complex_cases == complex_case_count
            and current.evaluated_complex_cases == complex_case_count
        ):
            completion_gate = _comparison_gate(
                baseline.complex_completion_rate,
                current.complex_completion_rate,
                predicate=lambda before, after: after > before,
            )
        convergence_gate: BenchmarkGateStatus = "insufficient_data"
        if all_cases_rerun:
            convergence_gate = _comparison_gate(
                baseline.repeated_tool_calls,
                current.repeated_tool_calls,
                predicate=lambda before, after: after <= before,
            )
        simple_gate = (
            _comparison_gate(
                baseline.simple_qa_tool_calls,
                current.simple_qa_tool_calls,
                predicate=lambda before, after: after <= before,
            )
            if all_cases_rerun
            else "insufficient_data"
        )
        duration_gate = (
            _comparison_gate(
                baseline.p95_duration_ms,
                current.p95_duration_ms,
                predicate=lambda before, after: after <= before * 1.2,
            )
            if all_cases_rerun
            else "insufficient_data"
        )
        token_gate = (
            _comparison_gate(
                baseline.p95_total_tokens,
                current.p95_total_tokens,
                predicate=lambda before, after: after <= before * 1.2,
            )
            if all_cases_rerun
            else "insufficient_data"
        )
        gates = BenchmarkRegressionGates(
            complex_completion=completion_gate,
            convergence=convergence_gate,
            simple_tool_calls=simple_gate,
            p95_duration=duration_gate,
            p95_tokens=token_gate,
        )
        statuses = (
            gates.complex_completion,
            gates.convergence,
            gates.simple_tool_calls,
            gates.p95_duration,
            gates.p95_tokens,
        )
        return BenchmarkRegressionSummary(
            case_count=len(BENCHMARK_CASES),
            rerun_case_count=rerun_case_count,
            all_cases_rerun=all_cases_rerun,
            baseline=baseline,
            current=current,
            gates=gates,
            ready_to_close=all(status == "passed" for status in statuses),
        )

    def score(
        self,
        run_id: str,
        *,
        task_completed: bool,
        score: int,
        notes: str | None,
    ) -> BenchmarkReport | None:
        if not 1 <= score <= 5:
            raise ValueError("Benchmark score must be between 1 and 5")
        normalized_notes = notes.strip() if notes is not None else None
        if normalized_notes == "":
            normalized_notes = None
        if normalized_notes is not None and len(normalized_notes) > 2000:
            raise ValueError("Benchmark notes must not exceed 2000 characters")
        updated = self._store.update_benchmark_score(
            run_id,
            task_completed=task_completed,
            score=score,
            notes=normalized_notes,
        )
        return None if updated is None else self.get_report(run_id)

    def _report(self, attempt: BenchmarkAttempt) -> BenchmarkReport:
        case = require_benchmark_case(attempt.case_id)
        events = self._store.list_run_events(
            attempt.thread_id,
            attempt.run_id,
            after_sequence=0,
            limit=100_000,
        )
        return BenchmarkReport(attempt=attempt, case=case, metrics=_metrics(attempt, events))
