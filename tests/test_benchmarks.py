"""验证 14.1 固定能力基准的目录、指标与评分持久化。"""

from pathlib import Path
from typing import Any, cast

from mini_deer_agent.application import BenchmarkService
from mini_deer_agent.domain import BENCHMARK_CASES, BenchmarkAttempt
from mini_deer_agent.persistence import open_sqlite_conversation_repository
from mini_deer_agent.streaming import RunEvent


THREAD_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
ASSISTANT_1 = "44444444-4444-4444-8444-444444444444"
ASSISTANT_2 = "55555555-5555-4555-8555-555555555555"


def _event(
    name: str,
    sequence: int,
    *,
    message_id: str | None = None,
    payload: dict[str, object],
) -> RunEvent:
    return RunEvent(
        event=cast(Any, name),
        run_id=RUN_ID,
        thread_id=THREAD_ID,
        sequence=sequence,
        message_id=message_id,
        payload=payload,
    )


def test_catalog_contains_all_fixed_acceptance_scenarios(tmp_path: Path) -> None:
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repository:
        cases = BenchmarkService(repository).list_cases()

    assert [case.case_id for case in cases] == [
        "simple-qa",
        "ambiguous-request",
        "multi-source-research",
        "repeated-empty-results",
        "large-tool-output",
        "single-file-fix",
        "small-multi-file-feature",
        "parallel-delegation",
    ]


def test_report_derives_trace_repetition_model_calls_and_persists_score(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "app.sqlite"
    with open_sqlite_conversation_repository(database_path) as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="benchmark",
            benchmark_case_id="repeated-empty-results",
        )
        events = (
            _event("run_started", 1, payload={"created_at": "2026-09-07T08:00:00+00:00"}),
            _event(
                "tool_call_delta",
                2,
                message_id=ASSISTANT_1,
                payload={"tool_call_id": "call-1", "name": "web_search", "arguments_delta": '{"query":"missing"}'},
            ),
            _event(
                "tool_result",
                3,
                payload={"tool_call_id": "call-1", "name": "web_search", "content": "[]"},
            ),
            _event(
                "tool_call_delta",
                4,
                message_id=ASSISTANT_2,
                payload={"tool_call_id": "call-2", "name": "web_search", "arguments_delta": '{"query":"missing"}'},
            ),
            _event(
                "tool_result",
                5,
                payload={"tool_call_id": "call-2", "name": "web_search", "content": "[]"},
            ),
            _event("ai_delta", 6, message_id=ASSISTANT_2, payload={"text": "没有证据"}),
            _event("run_completed", 7, payload={"finish_reason": "completed"}),
        )
        for item in events:
            assert repository.apply_run_event(item)

        service = BenchmarkService(repository)
        report = service.get_report(RUN_ID)
        assert report is not None
        assert report.metrics.model_calls == 2
        assert report.metrics.repeated_tool_calls == 1
        assert [step.name for step in report.metrics.tool_trajectory] == [
            "web_search",
            "web_search",
        ]
        assert report.metrics.total_tokens is None
        scored = service.score(
            RUN_ID,
            task_completed=True,
            score=4,
            notes="改变策略仍可更快",
        )
        assert scored is not None
        assert scored.attempt.task_completed is True
        assert scored.attempt.score == 4

    with open_sqlite_conversation_repository(database_path) as reopened:
        restored = BenchmarkService(reopened).get_report(RUN_ID)
        assert restored is not None
        assert restored.attempt.notes == "改变策略仍可更快"
        assert restored.attempt.scored_at is not None


def test_plain_run_is_not_exposed_as_benchmark_attempt(tmp_path: Path) -> None:
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repository:
        repository.create_run(
            thread_id=THREAD_ID,
            run_id=RUN_ID,
            user_message_id=MESSAGE_ID,
            user_message="ordinary chat",
        )
        service = BenchmarkService(repository)
        assert service.get_report(RUN_ID) is None
        assert service.list_reports() == ()


class _RegressionStore:
    def __init__(self, attempts: tuple[BenchmarkAttempt, ...]) -> None:
        self.attempts = attempts

    def list_benchmark_attempts(
        self, *, limit: int
    ) -> tuple[BenchmarkAttempt, ...]:
        return self.attempts[:limit]

    def get_benchmark_attempt(self, run_id: str) -> BenchmarkAttempt | None:
        return next(
            (attempt for attempt in self.attempts if attempt.run_id == run_id),
            None,
        )

    def update_benchmark_score(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None

    def list_run_events(
        self,
        thread_id: str,
        run_id: str,
        *,
        after_sequence: int,
        limit: int,
    ) -> tuple[Any, ...]:
        del thread_id, run_id, after_sequence, limit
        return ()


def _attempt(
    case_id: str,
    generation: str,
    *,
    completed: bool,
    duration_ms: int,
    tokens: int,
) -> BenchmarkAttempt:
    second = duration_ms // 1000
    millisecond = duration_ms % 1000
    return BenchmarkAttempt(
        case_id=case_id,
        run_id=f"{case_id}-{generation}",
        thread_id=f"thread-{case_id}-{generation}",
        status="completed",
        created_at=(
            "2026-01-01T00:00:00+00:00"
            if generation == "baseline"
            else "2026-02-01T00:00:00+00:00"
        ),
        started_at="2026-01-01T00:00:00+00:00",
        finished_at=f"2026-01-01T00:00:{second:02d}.{millisecond:03d}+00:00",
        finish_reason="stop",
        error_code=None,
        input_tokens=tokens - 10,
        output_tokens=10,
        total_tokens=tokens,
        model_calls=2,
        task_completed=completed,
        score=4 if completed else 1,
        notes=None,
        scored_at="2026-02-01T00:01:00+00:00",
    )


def test_regression_summary_requires_all_cases_and_applies_fixed_gates() -> None:
    attempts: list[BenchmarkAttempt] = []
    complex_index = 0
    for case in BENCHMARK_CASES:
        is_complex = case.category not in {"simple_qa", "clarification"}
        if is_complex:
            complex_index += 1
        attempts.extend(
            [
                _attempt(
                    case.case_id,
                    "baseline",
                    completed=not is_complex or complex_index <= 3,
                    duration_ms=1_000,
                    tokens=100,
                ),
                _attempt(
                    case.case_id,
                    "current",
                    completed=not is_complex or complex_index <= 4,
                    duration_ms=1_100,
                    tokens=110,
                ),
            ]
        )

    summary = BenchmarkService(
        cast(Any, _RegressionStore(tuple(reversed(attempts))))
    ).regression_summary()

    assert summary.rerun_case_count == 8
    assert summary.all_cases_rerun is True
    assert summary.baseline.complex_completion_rate == 0.5
    assert summary.current.complex_completion_rate == 4 / 6
    assert summary.baseline.p95_duration_ms == 1_000
    assert summary.current.p95_total_tokens == 110
    assert summary.ready_to_close is True
    assert {
        summary.gates.complex_completion,
        summary.gates.convergence,
        summary.gates.simple_tool_calls,
        summary.gates.p95_duration,
        summary.gates.p95_tokens,
    } == {"passed"}
