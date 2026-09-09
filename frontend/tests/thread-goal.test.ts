import { describe, expect, it, vi } from "vitest";

import {
  clearThreadGoal,
  fetchThreadGoal,
  parseThreadGoal,
  setThreadGoal,
  stopThreadGoal,
} from "@/features/goals/api/thread-goal";

const THREAD_ID = "11111111-1111-4111-8111-111111111111";

function payload(overrides: Record<string, unknown> = {}) {
  return {
    version: 1,
    revision: "22222222-2222-4222-8222-222222222222",
    objective: "完成修复并让测试通过",
    continuation_count: 2,
    max_continuations: 6,
    no_progress_count: 1,
    last_evaluation: {
      satisfied: false,
      blocker: "goal_not_met_yet",
      reason: "还差最终测试",
      evidence_summary: "代码已修改",
      evaluated_at: "2026-09-08T01:00:00Z",
    },
    status: "active",
    stop_reason: null,
    created_at: "2026-09-08T00:00:00Z",
    updated_at: "2026-09-08T01:00:00Z",
    ...overrides,
  };
}

describe("线程 Goal API", () => {
  it("严格解析状态、续跑计数和最近评估", () => {
    expect(parseThreadGoal(payload())).toMatchObject({
      objective: "完成修复并让测试通过",
      continuationCount: 2,
      maxContinuations: 6,
      noProgressCount: 1,
      status: "active",
      lastEvaluation: {
        blocker: "goal_not_met_yet",
        evidenceSummary: "代码已修改",
      },
    });
    expect(() => parseThreadGoal(payload({ status: "invented" }))).toThrow(
      "Goal status 不受支持",
    );
    expect(() => parseThreadGoal(payload({ continuation_count: 7 }))).toThrow(
      "continuation_count 不能超过 max_continuations",
    );
    expect(() => parseThreadGoal(payload({ unexpected: true }))).toThrow(
      "Goal 响应包含未知字段",
    );
  });

  it("未创建 Thread 或未设置 Goal 时返回 null", async () => {
    const fetcher = vi.fn(() =>
      Promise.resolve(new Response(null, { status: 404 })),
    );
    await expect(
      fetchThreadGoal({ threadId: THREAD_ID }, { fetcher }),
    ).resolves.toBeNull();
  });

  it("区分未设置 Goal 与 Thread 不存在", async () => {
    const missingGoal = vi.fn(() =>
      Promise.resolve(
        Response.json(
          { detail: { code: "goal_not_found", message: "missing" } },
          { status: 404 },
        ),
      ),
    );
    const missingThread = vi.fn(() =>
      Promise.resolve(
        Response.json(
          { detail: { code: "thread_not_found", message: "missing" } },
          { status: 404 },
        ),
      ),
    );

    await expect(
      fetchThreadGoal({ threadId: THREAD_ID }, { fetcher: missingGoal }),
    ).resolves.toBeNull();
    await expect(
      fetchThreadGoal({ threadId: THREAD_ID }, { fetcher: missingThread }),
    ).rejects.toMatchObject({ code: "thread_not_found" });
  });

  it("设置、停止和清除调用各自的稳定端点", async () => {
    const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "DELETE")
        return Promise.resolve(new Response(null, { status: 204 }));
      return Promise.resolve(
        Response.json(
          payload({
            status: init?.method === "POST" ? "stopped" : "active",
            stop_reason: init?.method === "POST" ? "user_stopped" : null,
          }),
        ),
      );
    });

    await setThreadGoal(
      { threadId: THREAD_ID, objective: " 完成任务 ", maxContinuations: 4 },
      { fetcher },
    );
    const revision = "22222222-2222-4222-8222-222222222222";
    await stopThreadGoal({ threadId: THREAD_ID, revision }, { fetcher });
    await clearThreadGoal({ threadId: THREAD_ID, revision }, { fetcher });

    expect(
      fetcher.mock.calls.map(([input, init]) => [
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url,
        init?.method,
      ]),
    ).toEqual([
      [`/api/v1/threads/${THREAD_ID}/goal`, "PUT"],
      [`/api/v1/threads/${THREAD_ID}/goal/stop`, "POST"],
      [`/api/v1/threads/${THREAD_ID}/goal?revision=${revision}`, "DELETE"],
    ]);
    const firstBody = fetcher.mock.calls[0]?.[1]?.body;
    expect(typeof firstBody).toBe("string");
    if (typeof firstBody !== "string")
      throw new Error("请求体应为 JSON 字符串");
    expect(JSON.parse(firstBody)).toEqual({
      objective: "完成任务",
      max_continuations: 4,
    });
    const stopBody = fetcher.mock.calls[1]?.[1]?.body;
    if (typeof stopBody !== "string")
      throw new Error("停止请求体应为 JSON 字符串");
    expect(JSON.parse(stopBody)).toEqual({
      revision,
    });
  });
});
