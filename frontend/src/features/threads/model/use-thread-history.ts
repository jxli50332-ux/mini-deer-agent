import { useCallback, useEffect, useRef, useState } from "react";

import type { ThreadHistoryItem } from "@/entities/message/model/types";
import {
  fetchThreadHistoryPage,
  ThreadHistoryClientError,
  type ThreadHistoryPageLoader,
} from "@/features/threads/api/thread-history";

interface ThreadHistoryState {
  readonly threadId: string;
  readonly items: readonly ThreadHistoryItem[];
  readonly isInitialLoading: boolean;
  readonly isLoadingMore: boolean;
  readonly hasMore: boolean;
  readonly nextBeforeSequence: number | null;
  readonly error: string | null;
  readonly revision: number;
}

export interface UseThreadHistoryOptions {
  readonly pageLoader?: ThreadHistoryPageLoader;
}

export interface UseThreadHistoryResult extends ThreadHistoryState {
  readonly retry: () => void;
  readonly loadMore: () => Promise<boolean>;
}

function initialState(threadId: string): ThreadHistoryState {
  return {
    threadId,
    items: [],
    isInitialLoading: true,
    isLoadingMore: false,
    hasMore: false,
    nextBeforeSequence: null,
    error: null,
    revision: 0,
  };
}

function publicHistoryError(error: unknown): string {
  if (error instanceof ThreadHistoryClientError) {
    return error.message;
  }
  return "历史加载发生未知错误";
}

/** 管理单个 Thread 的初始历史、失败重试和向前分页。 */
export function useThreadHistory(
  threadId: string,
  options: UseThreadHistoryOptions = {},
): UseThreadHistoryResult {
  const pageLoader = options.pageLoader ?? fetchThreadHistoryPage;
  const [state, setState] = useState(() => initialState(threadId));
  const requestGenerationRef = useRef(0);
  const loadMoreControllerRef = useRef<AbortController | null>(null);
  const retryRevisionRef = useRef(0);
  const [retryRevision, setRetryRevision] = useState(0);

  useEffect(() => {
    requestGenerationRef.current += 1;
    const generation = requestGenerationRef.current;
    const controller = new AbortController();
    // Thread 切换或重试时同时取消可能仍在进行的向前分页请求。
    loadMoreControllerRef.current?.abort();
    loadMoreControllerRef.current = null;
    setState({ ...initialState(threadId), revision: retryRevision });

    void pageLoader({ threadId, limit: 100, signal: controller.signal }).then(
      (page) => {
        if (
          controller.signal.aborted ||
          generation !== requestGenerationRef.current
        ) {
          return;
        }
        setState({
          threadId,
          items: page.items,
          isInitialLoading: false,
          isLoadingMore: false,
          hasMore: page.hasMore,
          nextBeforeSequence: page.nextBeforeSequence,
          error: null,
          revision: retryRevision,
        });
      },
      (error: unknown) => {
        if (
          controller.signal.aborted ||
          generation !== requestGenerationRef.current
        ) {
          return;
        }
        setState({
          ...initialState(threadId),
          isInitialLoading: false,
          error: publicHistoryError(error),
          revision: retryRevision,
        });
      },
    );

    return () => {
      controller.abort();
      loadMoreControllerRef.current?.abort();
      loadMoreControllerRef.current = null;
    };
  }, [pageLoader, retryRevision, threadId]);

  const retry = useCallback(() => {
    retryRevisionRef.current += 1;
    setRetryRevision(retryRevisionRef.current);
  }, []);

  const loadMore = useCallback(async (): Promise<boolean> => {
    if (
      state.threadId !== threadId ||
      state.isInitialLoading ||
      state.isLoadingMore ||
      !state.hasMore ||
      state.nextBeforeSequence === null
    ) {
      return false;
    }

    const generation = requestGenerationRef.current;
    const controller = new AbortController();
    loadMoreControllerRef.current = controller;
    setState((current) => ({
      ...current,
      isLoadingMore: true,
      error: null,
    }));
    try {
      const page = await pageLoader({
        threadId,
        limit: 100,
        beforeSequence: state.nextBeforeSequence,
        signal: controller.signal,
      });
      if (generation !== requestGenerationRef.current) {
        return false;
      }
      setState((current) => {
        const currentIds = new Set(current.items.map((item) => item.id));
        return {
          ...current,
          items: [
            ...page.items.filter((item) => !currentIds.has(item.id)),
            ...current.items,
          ],
          isLoadingMore: false,
          hasMore: page.hasMore,
          nextBeforeSequence: page.nextBeforeSequence,
          error: null,
        };
      });
      return true;
    } catch (error) {
      if (generation !== requestGenerationRef.current) {
        return false;
      }
      setState((current) => ({
        ...current,
        isLoadingMore: false,
        error: publicHistoryError(error),
      }));
      return false;
    } finally {
      if (loadMoreControllerRef.current === controller) {
        loadMoreControllerRef.current = null;
      }
    }
  }, [pageLoader, state, threadId]);

  return { ...state, retry, loadMore };
}
