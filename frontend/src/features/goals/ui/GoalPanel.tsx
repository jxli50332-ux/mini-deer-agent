import { useState } from "react";

import type { ThreadGoal } from "@/features/goals/api/thread-goal";

interface GoalPanelProps {
  readonly goal: ThreadGoal | null;
  readonly isLoading: boolean;
  readonly isMutating: boolean;
  readonly isRunActive: boolean;
  readonly isEvaluating?: boolean;
  readonly error: string | null;
  readonly onSet: (
    objective: string,
    maxContinuations: number,
  ) => Promise<boolean>;
  readonly onStop: () => Promise<boolean>;
  readonly onContinue: (revision: string) => Promise<boolean>;
  readonly onClear: () => Promise<boolean>;
  readonly onRetry: () => void;
}

const STATUS_LABELS = {
  active: "进行中",
  paused: "已暂停",
  stopped: "已停止",
  completed: "已完成",
} as const;

const STOP_REASON_LABELS: Record<string, string> = {
  user_stopped: "用户已停止",
  max_continuations_reached: "达到最大续跑次数",
  no_progress: "连续无进展",
  token_capped: "达到 Token 预算",
  turn_capped: "达到模型轮次预算",
  loop_capped: "触发循环保护",
  missing_evidence: "缺少完成证据",
  needs_user_input: "需要用户输入",
  run_failed: "运行失败",
  external_wait: "等待外部条件",
};

export function GoalPanel({
  goal,
  isLoading,
  isMutating,
  error,
  onSet,
  onStop,
  onContinue,
  onClear,
  onRetry,
  isRunActive,
  isEvaluating = false,
}: GoalPanelProps) {
  const [editing, setEditing] = useState(false);
  const [objective, setObjective] = useState(goal?.objective ?? "");
  const [maxContinuations, setMaxContinuations] = useState(
    goal?.maxContinuations ?? 6,
  );

  if (isLoading && goal === null) {
    return (
      <div className="goal-panel goal-panel--loading">正在读取线程目标……</div>
    );
  }

  const showForm = editing || goal === null;
  return (
    <section className="goal-panel" aria-label="线程目标">
      {goal !== null && !showForm && (
        <>
          <div className="goal-panel__main">
            <span className="goal-panel__badge" data-status={goal.status}>
              Goal · {isEvaluating ? "评估中" : STATUS_LABELS[goal.status]}
            </span>
            <strong>{goal.objective}</strong>
            <span>
              续跑 {goal.continuationCount}/{goal.maxContinuations}
              {goal.noProgressCount > 0
                ? ` · 连续无进展 ${goal.noProgressCount}`
                : ""}
            </span>
          </div>
          {goal.lastEvaluation !== null && (
            <details className="goal-panel__evaluation">
              <summary>最近评估：{goal.lastEvaluation.reason}</summary>
              <p>{goal.lastEvaluation.evidenceSummary}</p>
            </details>
          )}
          {goal.stopReason !== null && (
            <span className="goal-panel__stop-reason">
              {STOP_REASON_LABELS[goal.stopReason] ?? goal.stopReason}
            </span>
          )}
          <div className="goal-panel__actions">
            <button
              type="button"
              disabled={isMutating}
              onClick={() => setEditing(true)}
            >
              {goal.status === "completed" ? "设置新目标" : "替换目标"}
            </button>
            {goal.status === "active" && !isRunActive && (
              <button
                type="button"
                disabled={isMutating}
                onClick={() => void onContinue(goal.revision)}
              >
                执行 Goal
              </button>
            )}
            {goal.status === "active" && (
              <button
                type="button"
                disabled={isMutating}
                onClick={() => void onStop()}
              >
                {isRunActive ? "停止执行与续跑" : "停止续跑"}
              </button>
            )}
            {(goal.status === "stopped" ||
              (goal.status === "paused" &&
                goal.stopReason !== "needs_user_input")) && (
              <button
                type="button"
                disabled={isMutating || isRunActive}
                onClick={() => void onContinue(goal.revision)}
              >
                {goal.status === "stopped" ? "恢复并继续" : "重试执行"}
              </button>
            )}
            <button
              type="button"
              disabled={isMutating}
              onClick={() => void onClear()}
            >
              清除目标
            </button>
          </div>
          {goal.status === "paused" &&
            goal.stopReason === "needs_user_input" && (
              <p className="goal-panel__hint">
                请在下方回答澄清问题；提交回答后 Goal 会自动恢复。
              </p>
            )}
          {goal.status === "completed" && (
            <p className="goal-panel__hint">
              Goal 已完成。你可以查看最近评估、清除目标或设置新目标。
            </p>
          )}
        </>
      )}
      {showForm && (
        <form
          className="goal-panel__form"
          onSubmit={(event) => {
            event.preventDefault();
            void onSet(objective, maxContinuations).then((saved) => {
              if (saved) setEditing(false);
            });
          }}
        >
          <label>
            <span>{goal === null ? "设置线程目标" : "替换线程目标"}</span>
            <textarea
              value={objective}
              maxLength={4000}
              rows={2}
              placeholder="例如：定位缺陷、完成修复并让测试通过"
              onChange={(event) => setObjective(event.target.value)}
            />
          </label>
          <label className="goal-panel__limit">
            最大续跑
            <input
              type="number"
              min={1}
              max={20}
              value={maxContinuations}
              onChange={(event) =>
                setMaxContinuations(Number(event.target.value))
              }
            />
          </label>
          <button
            type="submit"
            disabled={isMutating || objective.trim().length === 0}
          >
            {isMutating ? "正在保存……" : "保存目标"}
          </button>
          {goal !== null && (
            <button
              type="button"
              disabled={isMutating}
              onClick={() => setEditing(false)}
            >
              取消
            </button>
          )}
        </form>
      )}
      {error !== null && (
        <div className="goal-panel__error" aria-live="polite">
          <span>{error}</span>
          <button type="button" onClick={onRetry}>
            重试
          </button>
        </div>
      )}
    </section>
  );
}
