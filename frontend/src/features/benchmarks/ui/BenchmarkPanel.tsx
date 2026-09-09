import { useEffect, useState } from "react";

import {
  fetchBenchmarkCases,
  fetchBenchmarkRegression,
  fetchBenchmarkReports,
  scoreBenchmarkReport,
  type BenchmarkCase,
  type BenchmarkGateStatus,
  type BenchmarkReport,
  type BenchmarkRegressionSummary,
} from "@/features/benchmarks/api/benchmarks";

interface BenchmarkPanelProps {
  readonly open: boolean;
  readonly hasProject: boolean;
  readonly onClose: () => void;
  readonly onUseCase: (item: BenchmarkCase) => void;
}

function formatDuration(value: number | null): string {
  return value === null ? "—" : `${(value / 1000).toFixed(1)}s`;
}

function formatRate(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function formatGate(status: BenchmarkGateStatus): string {
  if (status === "passed") return "通过";
  if (status === "failed") return "未通过";
  return "数据不足";
}

export function BenchmarkPanel({
  open,
  hasProject,
  onClose,
  onUseCase,
}: BenchmarkPanelProps) {
  const [cases, setCases] = useState<readonly BenchmarkCase[]>([]);
  const [reports, setReports] = useState<readonly BenchmarkReport[]>([]);
  const [regression, setRegression] =
    useState<BenchmarkRegressionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [scoringRunId, setScoringRunId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let current = true;
    void Promise.all([
      fetchBenchmarkCases(),
      fetchBenchmarkReports(),
      fetchBenchmarkRegression(),
    ])
      .then(([nextCases, nextReports, nextRegression]) => {
        if (!current) return;
        setCases(nextCases);
        setReports(nextReports);
        setRegression(nextRegression);
      })
      .catch((reason: unknown) => {
        if (current)
          setError(
            reason instanceof Error ? reason.message : "无法加载能力基准",
          );
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [open]);

  if (!open) return null;

  const score = async (
    report: BenchmarkReport,
    completed: boolean,
    value: number,
  ) => {
    setScoringRunId(report.attempt.runId);
    setError(null);
    try {
      const updated = await scoreBenchmarkReport(
        report.attempt.runId,
        completed,
        value,
        report.attempt.notes ?? "",
      );
      setReports((current) =>
        current.map((item) =>
          item.attempt.runId === updated.attempt.runId ? updated : item,
        ),
      );
      try {
        setRegression(await fetchBenchmarkRegression());
      } catch {
        setError("评分已保存，但无法刷新回归摘要");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法保存评分");
    } finally {
      setScoringRunId(null);
    }
  };

  return (
    <aside
      className="benchmark-panel"
      aria-label="能力基准"
      aria-busy={loading}
    >
      <header>
        <div>
          <p>第 14.1 阶段</p>
          <h2>固定能力基准</h2>
        </div>
        <button type="button" onClick={onClose} aria-label="关闭能力基准">
          ×
        </button>
      </header>
      <p className="benchmark-panel__hint">
        选择任务会把固定输入填入编辑器；发送后使用普通 Run/Event Store
        记录真实轨迹。
      </p>
      {error !== null && (
        <p role="alert" className="benchmark-panel__error">
          {error}
        </p>
      )}
      <section>
        <h3>回归门槛</h3>
        {regression !== null && (
          <article className="benchmark-regression">
            <p>
              已复测 {regression.rerunCaseCount}/{regression.caseCount}{" "}
              个固定案例 ·{" "}
              {regression.readyToClose ? "满足退出条件" : "尚未满足退出条件"}
            </p>
            <dl>
              <div>
                <dt>复杂任务完成率</dt>
                <dd>
                  {formatRate(regression.baseline.complexCompletionRate)} →{" "}
                  {formatRate(regression.current.complexCompletionRate)} ·{" "}
                  {formatGate(regression.gates.complexCompletion)}
                </dd>
              </div>
              <div>
                <dt>重复调用</dt>
                <dd>
                  {regression.baseline.repeatedToolCalls} →{" "}
                  {regression.current.repeatedToolCalls} ·{" "}
                  {formatGate(regression.gates.convergence)}
                </dd>
              </div>
              <div>
                <dt>简单问答工具调用</dt>
                <dd>
                  {regression.baseline.simpleQaToolCalls ?? "—"} →{" "}
                  {regression.current.simpleQaToolCalls ?? "—"} ·{" "}
                  {formatGate(regression.gates.simpleToolCalls)}
                </dd>
              </div>
              <div>
                <dt>P95 时延</dt>
                <dd>
                  {formatDuration(regression.baseline.p95DurationMs)} →{" "}
                  {formatDuration(regression.current.p95DurationMs)} ·{" "}
                  {formatGate(regression.gates.p95Duration)}
                </dd>
              </div>
              <div>
                <dt>P95 Token</dt>
                <dd>
                  {regression.baseline.p95TotalTokens ?? "—"} →{" "}
                  {regression.current.p95TotalTokens ?? "—"} ·{" "}
                  {formatGate(regression.gates.p95Tokens)}
                </dd>
              </div>
            </dl>
          </article>
        )}
      </section>
      <section>
        <h3>固定任务</h3>
        <div className="benchmark-case-list">
          {cases.map((item) => {
            const disabled = item.requiresProject && !hasProject;
            return (
              <article key={item.caseId} className="benchmark-card">
                <span>{item.category}</span>
                <h4>{item.title}</h4>
                <p>{item.expectedBehavior}</p>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => {
                    onUseCase(item);
                    onClose();
                  }}
                >
                  {disabled ? "请先打开项目" : "填入固定输入"}
                </button>
              </article>
            );
          })}
        </div>
      </section>
      <section>
        <h3>最近运行</h3>
        {reports.length === 0 && !loading && <p>还没有基准运行。</p>}
        <div className="benchmark-report-list">
          {reports.map((report) => (
            <article key={report.attempt.runId} className="benchmark-report">
              <h4>{report.case.title}</h4>
              <dl>
                <div>
                  <dt>状态</dt>
                  <dd>{report.attempt.status}</dd>
                </div>
                <div>
                  <dt>工具调用</dt>
                  <dd>{report.metrics.toolTrajectory.length}</dd>
                </div>
                <div>
                  <dt>连续重复</dt>
                  <dd>{report.metrics.repeatedToolCalls}</dd>
                </div>
                <div>
                  <dt>模型轮次</dt>
                  <dd>{report.metrics.modelCalls}</dd>
                </div>
                <div>
                  <dt>耗时</dt>
                  <dd>{formatDuration(report.metrics.durationMs)}</dd>
                </div>
                <div>
                  <dt>Token</dt>
                  <dd>{report.metrics.totalTokens ?? "暂不可得"}</dd>
                </div>
              </dl>
              <div className="benchmark-report__score" aria-label="人工评分">
                <button
                  type="button"
                  disabled={scoringRunId === report.attempt.runId}
                  onClick={() => void score(report, false, 1)}
                >
                  未完成 · 1
                </button>
                <button
                  type="button"
                  disabled={scoringRunId === report.attempt.runId}
                  onClick={() => void score(report, true, 3)}
                >
                  完成 · 3
                </button>
                <button
                  type="button"
                  disabled={scoringRunId === report.attempt.runId}
                  onClick={() => void score(report, true, 5)}
                >
                  优秀 · 5
                </button>
                {report.attempt.score !== null && (
                  <span>已评分：{report.attempt.score}/5</span>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>
    </aside>
  );
}
