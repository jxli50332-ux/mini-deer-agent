"""定义固定能力基准的版本化 HTTP 契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BenchmarkCaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    title: str
    category: str
    prompt: str
    expected_behavior: str
    requires_project: bool


class BenchmarkToolStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: str
    status: str


class BenchmarkMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_trajectory: list[BenchmarkToolStepResponse]
    repeated_tool_calls: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    final_check_result: Literal["passed", "failed", "not_run"]
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class BenchmarkAttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    run_id: str
    thread_id: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    finish_reason: str | None
    error_code: str | None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    model_calls: int | None = Field(default=None, ge=0)
    task_completed: bool | None
    score: int | None = Field(default=None, ge=1, le=5)
    notes: str | None
    scored_at: str | None


class BenchmarkReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    case: BenchmarkCaseResponse
    attempt: BenchmarkAttemptResponse
    metrics: BenchmarkMetricsResponse


class BenchmarkRegressionSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_count: int = Field(ge=0)
    evaluated_complex_cases: int = Field(ge=0)
    completed_complex_cases: int = Field(ge=0)
    complex_completion_rate: float | None = Field(default=None, ge=0, le=1)
    repeated_tool_calls: int = Field(ge=0)
    simple_qa_tool_calls: int | None = Field(default=None, ge=0)
    p95_duration_ms: int | None = Field(default=None, ge=0)
    p95_total_tokens: int | None = Field(default=None, ge=0)


class BenchmarkRegressionGatesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complex_completion: Literal["passed", "failed", "insufficient_data"]
    convergence: Literal["passed", "failed", "insufficient_data"]
    simple_tool_calls: Literal["passed", "failed", "insufficient_data"]
    p95_duration: Literal["passed", "failed", "insufficient_data"]
    p95_tokens: Literal["passed", "failed", "insufficient_data"]


class BenchmarkRegressionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    case_count: int = Field(ge=1)
    rerun_case_count: int = Field(ge=0)
    all_cases_rerun: bool
    baseline: BenchmarkRegressionSnapshotResponse
    current: BenchmarkRegressionSnapshotResponse
    gates: BenchmarkRegressionGatesResponse
    ready_to_close: bool


class BenchmarkScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_completed: bool
    score: int = Field(ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)
