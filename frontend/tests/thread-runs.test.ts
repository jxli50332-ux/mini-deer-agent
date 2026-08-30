import { describe, expect, it, vi } from "vitest";

import {
  fetchThreadRuns,
  parseThreadRuns,
  type ThreadRunsFetchLike,
} from "@/features/threads/api/thread-runs";

const THREAD_ID = "11111111-1111-4111-8111-111111111111";
const RUN_ID = "22222222-2222-4222-8222-222222222222";
const MESSAGE_ID = "33333333-3333-4333-8333-333333333333";

function wireRun() {
  return {
    run_id: RUN_ID,
    thread_id: THREAD_ID,
    status: "completed",
    user_message_id: MESSAGE_ID,
    created_at: "2026-08-29T08:00:00+00:00",
    started_at: "2026-08-29T08:00:01+00:00",
    finished_at: "2026-08-29T08:00:04+00:00",
    finish_reason: "stop",
    error_code: null,
  };
}

describe("Thread runs API client", () => {
  it("校验 Run 列表并规范化时间字段", () => {
    expect(parseThreadRuns([wireRun()], THREAD_ID)).toEqual([
      {
        runId: RUN_ID,
        threadId: THREAD_ID,
        status: "completed",
        userMessageId: MESSAGE_ID,
        createdAt: "2026-08-29T08:00:00+00:00",
        startedAt: "2026-08-29T08:00:01+00:00",
        finishedAt: "2026-08-29T08:00:04+00:00",
        finishReason: "stop",
        errorCode: null,
      },
    ]);
  });

  it("读取当前 Thread 的最近 200 个 Run", async () => {
    const fetcher = vi.fn<ThreadRunsFetchLike>(() =>
      Promise.resolve(Response.json([wireRun()])),
    );

    await expect(
      fetchThreadRuns({ threadId: THREAD_ID }, { fetcher }),
    ).resolves.toHaveLength(1);
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/threads/${THREAD_ID}/runs?limit=200`,
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
  });

  it("拒绝跨 Thread、重复和非法时间的 Run 记录", () => {
    expect(() =>
      parseThreadRuns([{ ...wireRun(), thread_id: RUN_ID }], THREAD_ID),
    ).toThrow("Run 列表包含无效记录");
    expect(() => parseThreadRuns([wireRun(), wireRun()], THREAD_ID)).toThrow(
      "Run 列表包含重复身份",
    );
    expect(() =>
      parseThreadRuns([{ ...wireRun(), finished_at: "invalid" }], THREAD_ID),
    ).toThrow("Run 列表包含无效记录");
  });
});
