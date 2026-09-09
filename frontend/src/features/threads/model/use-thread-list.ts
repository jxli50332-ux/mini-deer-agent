import { useCallback, useEffect, useRef, useState } from "react";

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
  readonly isLoadingMore: boolean;
  readonly hasMore: boolean;
  readonly error: string | null;
}

export interface UseThreadListOptions {
  readonly loader?: ThreadListLoader;
  readonly updater?: ThreadTitleUpdater;
  readonly deleter?: ThreadDeleter;
}

export interface UseThreadListResult extends ThreadListState {
  readonly retry: () => void;
  readonly loadMore: () => Promise<void>;
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
  const loadMoreController = useRef<AbortController | null>(null);
  const pageSize = 50;
  const [state, setState] = useState<ThreadListState>({
    items: [],
    isLoading: true,
    isLoadingMore: false,
    hasMore: false,
    error: null,
  });
  const retry = useCallback(() => setRevision((value) => value + 1), []);
  const loadMore = useCallback(async () => {
    if (
      loadMoreController.current !== null ||
      !state.hasMore ||
      state.isLoading
    )
      return;
    const offset = state.items.length;
    setState((current) => ({
      ...current,
      isLoadingMore: true,
      error: null,
    }));
    const controller = new AbortController();
    loadMoreController.current = controller;
    try {
      const items = await loader({
        limit: pageSize,
        offset,
        scope: "standalone",
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setState((current) => ({
        ...current,
        items: [
          ...new Map(
            [...current.items, ...items].map((item) => [item.threadId, item]),
          ).values(),
        ],
        isLoadingMore: false,
        hasMore: items.length === pageSize,
      }));
    } catch (error) {
      if (controller.signal.aborted) return;
      setState((current) => ({
        ...current,
        isLoadingMore: false,
        error: errorMessage(error),
      }));
    } finally {
      if (loadMoreController.current === controller) {
        loadMoreController.current = null;
      }
    }
  }, [loader, state.hasMore, state.isLoading, state.items.length]);
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
    loadMoreController.current?.abort();
    loadMoreController.current = null;
    setState((current) => ({
      ...current,
      isLoading: true,
      error: null,
    }));

    void (async () => {
      try {
        const items = await loader({
          limit: pageSize,
          offset: 0,
          scope: "standalone",
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setState({
            items,
            isLoading: false,
            isLoadingMore: false,
            hasMore: items.length === pageSize,
            error: null,
          });
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

    return () => {
      controller.abort();
      loadMoreController.current?.abort();
      loadMoreController.current = null;
    };
  }, [loader, revision]);

  return { ...state, retry, loadMore, renameTitle, deleteThread };
}
