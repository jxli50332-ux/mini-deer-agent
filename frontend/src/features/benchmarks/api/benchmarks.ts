export interface BenchmarkCase {
  readonly caseId: string;
  readonly title: string;
  readonly category: string;
  readonly prompt: string;
  readonly expectedBehavior: string;
  readonly requiresProject: boolean;
}

export interface BenchmarkToolStep {
  readonly name: string;
  readonly arguments: string;
  readonly status: string;
}

export interface BenchmarkReport {
  readonly case: BenchmarkCase;
  readonly attempt: {
    readonly caseId: string;
    readonly runId: string;
    readonly threadId: string;
    readonly status: string;
    readonly taskCompleted: boolean | null;
    readonly score: number | null;
    readonly notes: string | null;
    readonly createdAt: string;
    readonly finishedAt: string | null;
  };
  readonly metrics: {
    readonly toolTrajectory: readonly BenchmarkToolStep[];
    readonly repeatedToolCalls: number;
    readonly modelCalls: number;
    readonly durationMs: number | null;
    readonly finalCheckResult: "passed" | "failed" | "not_run";
    readonly totalTokens: number | null;
  };
}

export type BenchmarkGateStatus = "passed" | "failed" | "insufficient_data";

export interface BenchmarkRegressionSummary {
  readonly caseCount: number;
  readonly rerunCaseCount: number;
  readonly allCasesRerun: boolean;
  readonly readyToClose: boolean;
  readonly baseline: BenchmarkRegressionSnapshot;
  readonly current: BenchmarkRegressionSnapshot;
  readonly gates: Readonly<{
    complexCompletion: BenchmarkGateStatus;
    convergence: BenchmarkGateStatus;
    simpleToolCalls: BenchmarkGateStatus;
    p95Duration: BenchmarkGateStatus;
    p95Tokens: BenchmarkGateStatus;
  }>;
}

export interface BenchmarkRegressionSnapshot {
  readonly runCount: number;
  readonly evaluatedComplexCases: number;
  readonly completedComplexCases: number;
  readonly complexCompletionRate: number | null;
  readonly repeatedToolCalls: number;
  readonly simpleQaToolCalls: number | null;
  readonly p95DurationMs: number | null;
  readonly p95TotalTokens: number | null;
}

type UnknownRecord = Record<string, unknown>;

function record(value: unknown, label: string): UnknownRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} 不是有效对象`);
  }
  return value as UnknownRecord;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string") throw new Error(`${label} 不是字符串`);
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  return value === null ? null : string(value, label);
}

function integer(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new Error(`${label} 不是非负整数`);
  }
  return value as number;
}

function nullableInteger(value: unknown, label: string): number | null {
  return value === null ? null : integer(value, label);
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} 不是布尔值`);
  return value;
}

function nullableRate(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || value < 0 || value > 1) {
    throw new Error(`${label} 不是 0 到 1 的数字或 null`);
  }
  return value;
}

function gate(value: unknown, label: string): BenchmarkGateStatus {
  if (
    value !== "passed" &&
    value !== "failed" &&
    value !== "insufficient_data"
  ) {
    throw new Error(`${label} 不是受支持的门槛状态`);
  }
  return value;
}

function parseSnapshot(value: unknown): BenchmarkRegressionSnapshot {
  const snapshot = record(value, "回归快照");
  return {
    runCount: integer(snapshot.run_count, "run_count"),
    evaluatedComplexCases: integer(
      snapshot.evaluated_complex_cases,
      "evaluated_complex_cases",
    ),
    completedComplexCases: integer(
      snapshot.completed_complex_cases,
      "completed_complex_cases",
    ),
    complexCompletionRate: nullableRate(
      snapshot.complex_completion_rate,
      "complex_completion_rate",
    ),
    repeatedToolCalls: integer(
      snapshot.repeated_tool_calls,
      "repeated_tool_calls",
    ),
    simpleQaToolCalls: nullableInteger(
      snapshot.simple_qa_tool_calls,
      "simple_qa_tool_calls",
    ),
    p95DurationMs: nullableInteger(snapshot.p95_duration_ms, "p95_duration_ms"),
    p95TotalTokens: nullableInteger(
      snapshot.p95_total_tokens,
      "p95_total_tokens",
    ),
  };
}

function parseRegression(value: unknown): BenchmarkRegressionSummary {
  const summary = record(value, "回归摘要");
  const gates = record(summary.gates, "回归门槛");
  return {
    caseCount: integer(summary.case_count, "case_count"),
    rerunCaseCount: integer(summary.rerun_case_count, "rerun_case_count"),
    allCasesRerun: boolean(summary.all_cases_rerun, "all_cases_rerun"),
    readyToClose: boolean(summary.ready_to_close, "ready_to_close"),
    baseline: parseSnapshot(summary.baseline),
    current: parseSnapshot(summary.current),
    gates: {
      complexCompletion: gate(gates.complex_completion, "complex_completion"),
      convergence: gate(gates.convergence, "convergence"),
      simpleToolCalls: gate(gates.simple_tool_calls, "simple_tool_calls"),
      p95Duration: gate(gates.p95_duration, "p95_duration"),
      p95Tokens: gate(gates.p95_tokens, "p95_tokens"),
    },
  };
}

function parseCase(value: unknown): BenchmarkCase {
  const item = record(value, "基准案例");
  if (typeof item.requires_project !== "boolean") {
    throw new Error("requires_project 不是布尔值");
  }
  return {
    caseId: string(item.case_id, "case_id"),
    title: string(item.title, "title"),
    category: string(item.category, "category"),
    prompt: string(item.prompt, "prompt"),
    expectedBehavior: string(item.expected_behavior, "expected_behavior"),
    requiresProject: item.requires_project,
  };
}

function parseReport(value: unknown): BenchmarkReport {
  const report = record(value, "基准报告");
  const attempt = record(report.attempt, "attempt");
  const metrics = record(report.metrics, "metrics");
  if (!Array.isArray(metrics.tool_trajectory)) {
    throw new Error("tool_trajectory 不是数组");
  }
  const taskCompleted = attempt.task_completed;
  if (taskCompleted !== null && typeof taskCompleted !== "boolean") {
    throw new Error("task_completed 不是布尔值或 null");
  }
  const finalCheckResult = string(
    metrics.final_check_result,
    "final_check_result",
  );
  if (!["passed", "failed", "not_run"].includes(finalCheckResult)) {
    throw new Error("final_check_result 不受支持");
  }
  return {
    case: parseCase(report.case),
    attempt: {
      caseId: string(attempt.case_id, "case_id"),
      runId: string(attempt.run_id, "run_id"),
      threadId: string(attempt.thread_id, "thread_id"),
      status: string(attempt.status, "status"),
      taskCompleted,
      score: nullableInteger(attempt.score, "score"),
      notes: nullableString(attempt.notes, "notes"),
      createdAt: string(attempt.created_at, "created_at"),
      finishedAt: nullableString(attempt.finished_at, "finished_at"),
    },
    metrics: {
      toolTrajectory: metrics.tool_trajectory.map((raw) => {
        const step = record(raw, "tool step");
        return {
          name: string(step.name, "tool name"),
          arguments: string(step.arguments, "tool arguments"),
          status: string(step.status, "tool status"),
        };
      }),
      repeatedToolCalls: integer(
        metrics.repeated_tool_calls,
        "repeated_tool_calls",
      ),
      modelCalls: integer(metrics.model_calls, "model_calls"),
      durationMs: nullableInteger(metrics.duration_ms, "duration_ms"),
      finalCheckResult: finalCheckResult as "passed" | "failed" | "not_run",
      totalTokens: nullableInteger(metrics.total_tokens, "total_tokens"),
    },
  };
}

async function json(response: Response): Promise<unknown> {
  if (!response.ok)
    throw new Error(`能力基准请求失败（HTTP ${response.status}）`);
  return response.json();
}

export async function fetchBenchmarkCases(): Promise<readonly BenchmarkCase[]> {
  const value = await json(
    await fetch("/api/v1/benchmarks/cases", { cache: "no-store" }),
  );
  if (!Array.isArray(value)) throw new Error("能力基准案例响应不是数组");
  return value.map(parseCase);
}

export async function fetchBenchmarkReports(): Promise<
  readonly BenchmarkReport[]
> {
  const value = await json(
    await fetch("/api/v1/benchmarks/attempts", { cache: "no-store" }),
  );
  if (!Array.isArray(value)) throw new Error("能力基准报告响应不是数组");
  return value.map(parseReport);
}

export async function fetchBenchmarkRegression(): Promise<BenchmarkRegressionSummary> {
  return parseRegression(
    await json(
      await fetch("/api/v1/benchmarks/regression", { cache: "no-store" }),
    ),
  );
}

export async function scoreBenchmarkReport(
  runId: string,
  taskCompleted: boolean,
  score: number,
  notes: string,
): Promise<BenchmarkReport> {
  return parseReport(
    await json(
      await fetch(
        `/api/v1/benchmarks/attempts/${encodeURIComponent(runId)}/score`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task_completed: taskCompleted, score, notes }),
        },
      ),
    ),
  );
}
