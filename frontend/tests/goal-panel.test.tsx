import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ThreadGoal } from "@/features/goals/api/thread-goal";
import { GoalPanel } from "@/features/goals/ui/GoalPanel";

const goal: ThreadGoal = {
  version: 1,
  revision: "22222222-2222-4222-8222-222222222222",
  objective: "定位缺陷并让测试通过",
  continuationCount: 2,
  maxContinuations: 6,
  noProgressCount: 1,
  lastEvaluation: {
    satisfied: false,
    blocker: "goal_not_met_yet",
    reason: "还差最终回归",
    evidenceSummary: "聚焦测试已经通过",
    evaluatedAt: "2026-09-08T01:00:00Z",
  },
  status: "active",
  stopReason: null,
  createdAt: "2026-09-08T00:00:00Z",
  updatedAt: "2026-09-08T01:00:00Z",
};

function props(overrides: Partial<Parameters<typeof GoalPanel>[0]> = {}) {
  return {
    goal,
    isLoading: false,
    isMutating: false,
    isRunActive: false,
    error: null,
    onSet: vi.fn(() => Promise.resolve(true)),
    onStop: vi.fn(() => Promise.resolve(true)),
    onContinue: vi.fn(() => Promise.resolve(true)),
    onClear: vi.fn(() => Promise.resolve(true)),
    onRetry: vi.fn(),
    ...overrides,
  };
}

describe("线程 Goal 面板", () => {
  it("展示目标、续跑计数、评估证据，并可停止或清除", () => {
    const onStop = vi.fn(() => Promise.resolve(true));
    const onClear = vi.fn(() => Promise.resolve(true));
    render(<GoalPanel {...props({ onStop, onClear })} />);

    expect(screen.getByText("定位缺陷并让测试通过")).toBeVisible();
    expect(screen.getByText(/续跑 2\/6 · 连续无进展 1/)).toBeVisible();
    expect(screen.getByText(/最近评估：还差最终回归/)).toBeVisible();
    expect(screen.getByText("聚焦测试已经通过")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "停止续跑" }));
    fireEvent.click(screen.getByRole("button", { name: "清除目标" }));
    expect(onStop).toHaveBeenCalledOnce();
    expect(onClear).toHaveBeenCalledOnce();
  });

  it("没有 Goal 时可设置具体目标和最大续跑次数", async () => {
    const onSet = vi.fn(() => Promise.resolve(true));
    render(<GoalPanel {...props({ goal: null, onSet })} />);

    fireEvent.change(screen.getByPlaceholderText(/定位缺陷/), {
      target: { value: "完成全部检查" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "最大续跑" }), {
      target: { value: "3" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存目标" }));

    await waitFor(() => expect(onSet).toHaveBeenCalledWith("完成全部检查", 3));
  });

  it("停止态展示明确原因且不会继续提供停止按钮", () => {
    const onContinue = vi.fn(() => Promise.resolve(true));
    render(
      <GoalPanel
        {...props({
          goal: {
            ...goal,
            status: "stopped",
            stopReason: "max_continuations_reached",
          },
          onContinue,
        })}
      />,
    );

    expect(screen.getByText("达到最大续跑次数")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "停止续跑" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "恢复并继续" }));
    expect(onContinue).toHaveBeenCalledWith(goal.revision);
  });

  it("Run 结束后等待 Goal 判定时显示独立评估阶段", () => {
    render(<GoalPanel {...props({ isRunActive: true, isEvaluating: true })} />);

    expect(screen.getByText("Goal · 评估中")).toBeVisible();
  });

  it("活动 Run 明示停止会同时停止本轮执行和后续续跑", () => {
    render(<GoalPanel {...props({ isRunActive: true })} />);

    expect(
      screen.getByRole("button", { name: "停止执行与续跑" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "停止续跑" }),
    ).not.toBeInTheDocument();
  });
});
