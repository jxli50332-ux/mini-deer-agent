import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  ThreadHistoryPage,
  ThreadHistoryPageLoader,
} from "@/features/threads/api/thread-history";
import { useThreadHistory } from "@/features/threads/model/use-thread-history";

const THREAD_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_THREAD_ID = "22222222-2222-4222-8222-222222222222";
const RUN_ID = "33333333-3333-4333-8333-333333333333";

function page(
  threadId: string,
  sequences: readonly number[],
  hasMore: boolean,
): ThreadHistoryPage {
  return {
    version: "1",
    threadId,
    threadExists: true,
    items: sequences.map((sequence) => ({
      kind: "message",
      id: `${threadId}:${sequence}`,
      role: sequence % 2 === 0 ? "assistant" : "user",
      content: `消息 ${sequence}`,
      runId: RUN_ID,
      threadSequence: sequence,
      createdAt: "2026-08-26T08:00:00+00:00",
    })),
    hasMore,
    nextBeforeSequence: hasMore ? (sequences[0] ?? null) : null,
  };
}

describe("useThreadHistory", () => {
  it("加载最新页并按游标把更早消息前置", async () => {
    const loader = vi.fn<ThreadHistoryPageLoader>((request) =>
      Promise.resolve(
        request.beforeSequence === undefined
          ? page(THREAD_ID, [3, 4], true)
          : page(THREAD_ID, [1, 2], false),
      ),
    );
    const { result } = renderHook(() =>
      useThreadHistory(THREAD_ID, { pageLoader: loader }),
    );

    await waitFor(() => expect(result.current.isInitialLoading).toBe(false));
    expect(result.current.items.map((item) => item.threadSequence)).toEqual([
      3, 4,
    ]);

    await act(async () => {
      expect(await result.current.loadMore()).toBe(true);
    });
    expect(result.current.items.map((item) => item.threadSequence)).toEqual([
      1, 2, 3, 4,
    ]);
    expect(loader.mock.calls[1]?.[0].beforeSequence).toBe(3);
  });

  it("Thread 切换后忽略旧查询的迟到结果", async () => {
    let releaseOld: ((value: ThreadHistoryPage) => void) | undefined;
    const oldPage = new Promise<ThreadHistoryPage>((resolve) => {
      releaseOld = resolve;
    });
    const loader: ThreadHistoryPageLoader = (request) =>
      request.threadId === THREAD_ID
        ? oldPage
        : Promise.resolve(page(OTHER_THREAD_ID, [1], false));
    const { result, rerender } = renderHook(
      ({ threadId }: { readonly threadId: string }) =>
        useThreadHistory(threadId, { pageLoader: loader }),
      { initialProps: { threadId: THREAD_ID } },
    );

    rerender({ threadId: OTHER_THREAD_ID });
    await waitFor(() => expect(result.current.isInitialLoading).toBe(false));
    expect(result.current.threadId).toBe(OTHER_THREAD_ID);

    await act(async () => {
      releaseOld?.(page(THREAD_ID, [9], false));
      await oldPage;
    });
    expect(result.current.threadId).toBe(OTHER_THREAD_ID);
    expect(result.current.items[0]?.threadSequence).toBe(1);
  });
});
