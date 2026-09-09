import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatRunDuration } from "@/features/chat/model/run-timing";
import { RunTiming } from "@/features/chat/ui/RunTiming";

describe("RunTiming", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-29T08:00:02.200Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("从服务端开始时间按秒更新活动 Run 耗时", () => {
    render(
      <RunTiming
        timing={{
          kind: "active",
          startedAt: "2026-08-29T08:00:00.000Z",
        }}
      />,
    );

    expect(screen.getByTestId("run-timing")).toHaveTextContent(
      "执行中（2 秒）",
    );
    expect(screen.getByTestId("run-timing")).toHaveAttribute(
      "aria-label",
      "Agent 正在执行",
    );

    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(screen.getByTestId("run-timing")).toHaveTextContent(
      "执行中（3 秒）",
    );
  });

  it("拒绝显示非法开始时间", () => {
    const { container } = render(
      <RunTiming timing={{ kind: "active", startedAt: "not-a-time" }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it.each([
    ["completed", "执行完成，用时 2 秒"],
    ["failed", "执行失败，用时 2 秒"],
    ["cancelled", "执行已停止，用时 2 秒"],
  ] as const)("显示 %s Run 的终态耗时", (outcome, label) => {
    render(
      <RunTiming timing={{ kind: "settled", outcome, durationSeconds: 2 }} />,
    );

    expect(screen.getByLabelText(label)).toHaveTextContent(label);
    expect(screen.getByTestId("run-timing")).toHaveAttribute(
      "data-outcome",
      outcome,
    );
  });

  it("把预算触顶显示为正常 Run 终态并保留用量", () => {
    render(
      <RunTiming
        timing={{
          kind: "settled",
          outcome: "completed",
          durationSeconds: 12,
          finishReason: "token_capped",
          totalTokens: 120_321,
          modelCalls: 19,
        }}
      />,
    );

    const timing = screen.getByTestId("run-timing");
    expect(timing).toHaveAttribute("data-outcome", "completed");
    expect(timing).toHaveTextContent("Token 预算已达上限");
    expect(timing).toHaveTextContent("120,321 tokens");
    expect(timing).toHaveTextContent("19 次模型调用");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("formatRunDuration", () => {
  it.each([
    [0, "少于 1 秒"],
    [9, "9 秒"],
    [65, "1 分 5 秒"],
    [3_661, "1 小时 1 分 1 秒"],
  ])("把 %i 秒格式化为 %s", (seconds, expected) => {
    expect(formatRunDuration(seconds)).toBe(expected);
  });

  it("不接受负数、非整数和非有限值", () => {
    expect(formatRunDuration(-1)).toBeNull();
    expect(formatRunDuration(1.5)).toBeNull();
    expect(formatRunDuration(Number.POSITIVE_INFINITY)).toBeNull();
  });
});
