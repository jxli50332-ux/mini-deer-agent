import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useProjectThreadDraft } from "@/features/workspace/model/use-project-thread-draft";

const DRAFT_THREAD_ID = "66778899-1234-4234-9234-123456789012";

describe("空项目会话生命周期", () => {
  it("尚无 Run 时离开会删除草稿并公开被取消的身份", async () => {
    const deleteThread = vi.fn(() => Promise.resolve());
    const { result } = renderHook(() =>
      useProjectThreadDraft({
        currentThreadId: DRAFT_THREAD_ID,
        deleteThread,
      }),
    );
    act(() => result.current.markCreated(DRAFT_THREAD_ID));

    await act(async () => {
      expect(await result.current.discardBeforeLeaving()).toBe(true);
    });

    expect(deleteThread).toHaveBeenCalledWith(DRAFT_THREAD_ID);
    expect(result.current.discardedThreadId).toBe(DRAFT_THREAD_ID);
    expect(result.current.error).toBeNull();
  });

  it("收到 Run 身份后转为正式会话，离开时不删除", async () => {
    const deleteThread = vi.fn(() => Promise.resolve());
    const { result } = renderHook(() =>
      useProjectThreadDraft({
        currentThreadId: DRAFT_THREAD_ID,
        deleteThread,
      }),
    );
    act(() => result.current.markCreated(DRAFT_THREAD_ID));
    act(() => result.current.markRunStarted(DRAFT_THREAD_ID));
    await waitFor(() => expect(result.current.draftThreadId).toBeNull());

    await act(async () => {
      expect(await result.current.discardBeforeLeaving()).toBe(true);
    });

    expect(deleteThread).not.toHaveBeenCalled();
  });

  it("其他 Thread 的 Run 身份不会把新建项目草稿误判为正式会话", async () => {
    const deleteThread = vi.fn(() => Promise.resolve());
    const { result } = renderHook(() =>
      useProjectThreadDraft({
        currentThreadId: DRAFT_THREAD_ID,
        deleteThread,
      }),
    );
    act(() => result.current.markCreated(DRAFT_THREAD_ID));
    act(() =>
      result.current.markRunStarted("88990011-1234-4234-9234-123456789012"),
    );

    await act(async () => {
      expect(await result.current.discardBeforeLeaving()).toBe(true);
    });

    expect(deleteThread).toHaveBeenCalledWith(DRAFT_THREAD_ID);
  });

  it("删除失败时阻止离开并保留可见错误", async () => {
    const deleteThread = vi.fn(() => Promise.reject(new Error("删除失败")));
    const { result } = renderHook(() =>
      useProjectThreadDraft({
        currentThreadId: DRAFT_THREAD_ID,
        deleteThread,
      }),
    );
    act(() => result.current.markCreated(DRAFT_THREAD_ID));

    await act(async () => {
      expect(await result.current.discardBeforeLeaving()).toBe(false);
    });

    expect(result.current.error).toBe("删除失败");
    expect(result.current.discardedThreadId).toBeNull();
  });
});
