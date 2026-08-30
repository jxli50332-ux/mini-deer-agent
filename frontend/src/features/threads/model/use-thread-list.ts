import { useCallback, useEffect, useState } from "react";

import type { ThreadSummary } from "@/entities/thread/model/types";
import {
  deleteThread as requestThreadDeletion,
  fetchThreadList,
  ThreadListClientError,
  type ThreadDeleter,
  type ThreadListLoader,
  type ThreadTitleUpdater,
  updateThreadTitle,
} from "@/features/threads/api/thread-list";

interface ThreadListState {
  readonly items: readonly ThreadSummary[];
  readonly isLoading: boolean;
  readonly error: string | null;
}

export interface UseThreadListOptions {
  readonly loader?: ThreadListLoader;
  readonly updater?: ThreadTitleUpdater;
  readonly deleter?: ThreadDeleter;
}

export interface UseThreadListResult extends ThreadListState {
  readonly retry: () => void;
  readonly renameTitle: (threadId: string, title: string) => Promise<void>;
  readonly deleteThread: (threadId: string) => Promise<void>;
}

function errorMessage(error: unknown): string {
  if (error instanceof ThreadListClientError) {
    return error.message;
  }
  return "无法加载最近会话";
}

/** 管理最近 Thread 的初始加载、终态刷新和显式失败重试。 */
export function useThreadList(
  options: UseThreadListOptions = {},
): UseThreadListResult {
  const loader = options.loader ?? fetchThreadList;
  const updater = options.updater ?? updateThreadTitle;
  const deleter = options.deleter ?? requestThreadDeletion;
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<ThreadListState>({
    items: [],
    isLoading: true,
    error: null,
  });
  const retry = useCallback(() => setRevision((value) => value + 1), []);
  const renameTitle = useCallback(
    async (threadId: string, title: string) => {
      const updated = await updater({ threadId, title });
      // 以 PATCH 返回的 title/updatedAt 为准，不提前制造可能回滚的乐观标题。
      setState((current) => ({
        ...current,
        items: current.items.map((item) =>
          item.threadId === updated.threadId ? updated : item,
        ),
      }));
    },
    [updater],
  );
  const deleteThread = useCallback(
    async (threadId: string) => {
      await deleter({ threadId });
      // 只有 204 成功后才移除，失败时保留用户仍可操作的服务端事实。
      setState((current) => ({
        ...current,
        items: current.items.filter((item) => item.threadId !== threadId),
      }));
    },
    [deleter],
  );

  useEffect(() => {
    const controller = new AbortController();
    setState((current) => ({
      ...current,
      isLoading: true,
      error: null,
    }));

    void (async () => {
      try {
        const items = await loader({ limit: 20, signal: controller.signal });
        if (!controller.signal.aborted) {
          setState({ items, isLoading: false, error: null });
        }
      } catch (error) {
        if (
          controller.signal.aborted ||
          (error instanceof ThreadListClientError && error.code === "aborted")
        ) {
          return;
        }
        setState((current) => ({
          ...current,
          isLoading: false,
          error: errorMessage(error),
        }));
      }
    })();

    return () => controller.abort();
  }, [loader, revision]);

  return { ...state, retry, renameTitle, deleteThread };
}
