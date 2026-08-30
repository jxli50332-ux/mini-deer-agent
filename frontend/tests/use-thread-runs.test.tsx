import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ChatRunDetail } from "@/features/chat/api/chat-stream";
import type { ThreadRunsLoader } from "@/features/threads/api/thread-runs";
import { useThreadRuns } from "@/features/threads/model/use-thread-runs";

const THREAD_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_THREAD_ID = "22222222-2222-4222-8222-222222222222";

function run(threadId: string, runId = "run-1"): ChatRunDetail {
  return {
    runId,
    threadId,
    status: "completed",
    userMessageId: "message-1",
    createdAt: "2026-08-29T08:00:00Z",
    startedAt: "2026-08-29T08:00:01Z",
    finishedAt: "2026-08-29T08:00:03Z",
    finishReason: "stop",
    errorCode: null,
  };
}

describe("useThreadRuns", () => {
  it("刷新后使用最新持久化 Run，并忽略旧 Thread 的迟到结果", async () => {
    let releaseOld: ((runs: readonly ChatRunDetail[]) => void) | undefined;
    const oldRuns = new Promise<readonly ChatRunDetail[]>((resolve) => {
      releaseOld = resolve;
    });
    const loader = vi.fn<ThreadRunsLoader>((request) =>
      request.threadId === THREAD_ID
        ? oldRuns
        : Promise.resolve([run(OTHER_THREAD_ID, "run-new")]),
    );
    const { result, rerender } = renderHook(
      ({ threadId }: { readonly threadId: string }) =>
        useThreadRuns(threadId, { loader }),
      { initialProps: { threadId: THREAD_ID } },
    );

    rerender({ threadId: OTHER_THREAD_ID });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.runs[0]?.runId).toBe("run-new");

    await act(async () => {
      releaseOld?.([run(THREAD_ID, "run-old")]);
      await oldRuns;
    });
    expect(result.current.threadId).toBe(OTHER_THREAD_ID);
    expect(result.current.runs[0]?.runId).toBe("run-new");

    act(() => result.current.retry());
    await waitFor(() => expect(loader).toHaveBeenCalledTimes(3));
  });
});
