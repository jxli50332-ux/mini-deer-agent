import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ThreadGoal } from "@/features/goals/api/thread-goal";
import { useThreadGoal } from "@/features/goals/model/use-thread-goal";

const THREAD_ID = "11111111-1111-4111-8111-111111111111";

function goal(overrides: Partial<ThreadGoal> = {}): ThreadGoal {
  return {
    version: 1,
    revision: "22222222-2222-4222-8222-222222222222",
    objective: "完成可靠性修复",
    continuationCount: 0,
    maxContinuations: 6,
    noProgressCount: 0,
    lastEvaluation: null,
    status: "active",
    stopReason: null,
    createdAt: "2026-09-08T01:00:00Z",
    updatedAt: "2026-09-08T01:00:00Z",
    ...overrides,
  };
}

describe("useThreadGoal", () => {
  it("刷新失败时保留最后一次有效 Goal", async () => {
    const loader = vi
      .fn()
      .mockResolvedValueOnce(goal())
      .mockRejectedValueOnce(new Error("临时网络失败"));
    const { result } = renderHook(() => useThreadGoal(THREAD_ID, { loader }));
    await waitFor(() =>
      expect(result.current.goal?.objective).toBe("完成可靠性修复"),
    );

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.error).toBe("临时网络失败"));

    expect(result.current.goal?.objective).toBe("完成可靠性修复");
  });

  it("迟到的轮询结果不能覆盖停止操作返回的新状态", async () => {
    let resolvePolling: ((value: ThreadGoal) => void) | undefined;
    const polling = new Promise<ThreadGoal>((resolve) => {
      resolvePolling = resolve;
    });
    const loader = vi
      .fn()
      .mockResolvedValueOnce(goal())
      .mockReturnValueOnce(polling)
      .mockResolvedValue(
        goal({
          revision: "33333333-3333-4333-8333-333333333333",
          status: "stopped",
          stopReason: "user_stopped",
        }),
      );
    const stopper = vi.fn(() =>
      Promise.resolve(
        goal({
          revision: "33333333-3333-4333-8333-333333333333",
          status: "stopped",
          stopReason: "user_stopped",
        }),
      ),
    );
    const { result } = renderHook(() =>
      useThreadGoal(THREAD_ID, { loader, stopper }),
    );
    await waitFor(() => expect(result.current.goal?.status).toBe("active"));

    act(() => result.current.retry());
    await waitFor(() => expect(loader).toHaveBeenCalledTimes(2));
    await act(async () => {
      expect(await result.current.stopGoal()).toBe(true);
    });
    await act(async () => {
      resolvePolling?.(goal());
      await Promise.resolve();
    });

    expect(stopper).toHaveBeenCalledWith({
      threadId: THREAD_ID,
      revision: "22222222-2222-4222-8222-222222222222",
    });
    expect(result.current.goal?.status).toBe("stopped");
  });
});
