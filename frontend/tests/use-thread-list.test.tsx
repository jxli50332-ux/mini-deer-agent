import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ThreadSummary } from "@/entities/thread/model/types";
import type {
  ThreadDeleter,
  ThreadListLoader,
  ThreadTitleUpdater,
} from "@/features/threads/api/thread-list";
import { useThreadList } from "@/features/threads/model/use-thread-list";

const THREAD: ThreadSummary = {
  threadId: "11111111-1111-4111-8111-111111111111",
  title: "原始标题",
  status: "idle",
  projectId: null,
  createdAt: "2026-08-26T08:00:00+00:00",
  updatedAt: "2026-08-26T09:00:00+00:00",
};

describe("useThreadList", () => {
  it("加载最近 Thread，并允许失败后显式重试", async () => {
    const loader = vi
      .fn<ThreadListLoader>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce([THREAD]);
    const { result } = renderHook(() => useThreadList({ loader }));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.items).toEqual([]);

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.items).toEqual([THREAD]));
    expect(result.current.error).toBeNull();
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("改名成功后用服务端返回记录更新当前列表", async () => {
    const loader = vi.fn<ThreadListLoader>().mockResolvedValue([THREAD]);
    const updater = vi.fn<ThreadTitleUpdater>().mockResolvedValue({
      ...THREAD,
      title: "服务端标题",
      updatedAt: "2026-08-26T10:00:00+00:00",
    });
    const { result } = renderHook(() => useThreadList({ loader, updater }));
    await waitFor(() => expect(result.current.items).toEqual([THREAD]));

    await act(() => result.current.renameTitle(THREAD.threadId, "服务端标题"));

    expect(updater).toHaveBeenCalledWith({
      threadId: THREAD.threadId,
      title: "服务端标题",
    });
    expect(result.current.items[0]?.title).toBe("服务端标题");
  });

  it("仅在服务端删除成功后从最近列表移除 Thread", async () => {
    const loader = vi.fn<ThreadListLoader>().mockResolvedValue([THREAD]);
    const deleter = vi
      .fn<ThreadDeleter>()
      .mockRejectedValueOnce(new Error("删除服务暂时不可用"))
      .mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useThreadList({ loader, deleter }));
    await waitFor(() => expect(result.current.items).toEqual([THREAD]));

    await expect(
      act(() => result.current.deleteThread(THREAD.threadId)),
    ).rejects.toThrow("删除服务暂时不可用");
    expect(result.current.items).toEqual([THREAD]);

    await act(() => result.current.deleteThread(THREAD.threadId));
    expect(deleter).toHaveBeenLastCalledWith({ threadId: THREAD.threadId });
    expect(result.current.items).toEqual([]);
  });
});
