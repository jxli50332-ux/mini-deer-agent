import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CotStep } from "@/features/chat/model/project-cot";
import { CotTimeline } from "@/features/chat/ui/CotTimeline";

function completedStep(): CotStep {
  const rawResult = JSON.stringify(
    {
      version: 1,
      kind: "subagent_result",
      status: "completed",
      subagent_type: "project-reader",
      result: "child_scope 定义在 run_budget.py。",
      duration_ms: 1250,
      usage: { total_tokens: 600, model_calls: 2 },
    },
    null,
    2,
  );
  return {
    id: "task-reader",
    kind: "tool",
    icon: "task",
    text: "project-reader：定位 child_scope",
    toolName: "task",
    status: "completed",
    subagent: {
      name: "project-reader",
      description: "定位 child_scope",
      status: "completed",
      durationMs: 1250,
      stopReason: null,
      totalTokens: 600,
      modelCalls: 2,
      resultSummary: "child_scope 定义在 run_budget.py。",
      rawResult,
    },
  };
}

describe("子 Agent COT 卡片", () => {
  it("显示名称和状态，并可逐层展开摘要与原始结果", () => {
    render(<CotTimeline steps={[completedStep()]} />);

    expect(screen.getByText("project-reader")).toBeInTheDocument();
    expect(screen.getByText("已完成")).toBeInTheDocument();
    expect(screen.queryByText("结果摘要")).not.toBeVisible();

    fireEvent.click(screen.getByText("project-reader"));
    expect(
      screen.getByText("耗时 1.3 s · 600 tokens · 2 次模型调用"),
    ).toBeVisible();
    expect(screen.getByText("结果摘要")).toBeVisible();
    expect(
      screen.getByText("child_scope 定义在 run_budget.py。"),
    ).toBeVisible();

    const raw = screen.getByText("查看原始结果").closest("details");
    expect(raw).not.toBeNull();
    fireEvent.click(screen.getByText("查看原始结果"));
    expect(within(raw!).getByText(/"duration_ms": 1250/)).toBeVisible();
  });

  it("失败和超时默认展开并展示停止原因与部分结果", () => {
    const step: CotStep = {
      ...completedStep(),
      status: "timed_out",
      subagent: {
        ...completedStep().subagent!,
        status: "timed_out",
        stopReason: "timeout",
        resultSummary: "超时前找到一条可靠来源。",
      },
    };
    render(<CotTimeline steps={[step]} />);

    expect(screen.getByText("已超时")).toBeVisible();
    expect(screen.getByText("timeout")).toBeVisible();
    expect(screen.getByText("超时前找到一条可靠来源。")).toBeVisible();
  });
});
