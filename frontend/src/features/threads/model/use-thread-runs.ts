import { useCallback, useEffect, useRef, useState } from "react";

import type { ChatRunDetail } from "@/features/chat/api/chat-stream";
import {
  fetchThreadRuns,
  type ThreadRunsLoader,
} from "@/features/threads/api/thread-runs";

export interface UseThreadRunsOptions {
  readonly loader?: ThreadRunsLoader;
}

export interface UseThreadRunsResult {
  readonly threadId: string;
  readonly runs: readonly ChatRunDetail[];
  readonly isLoading: boolean;
  readonly retry: () => void;
}

interface ThreadRunsState {
  readonly threadId: string;
  readonly runs: readonly ChatRunDetail[];
  readonly isLoading: boolean;
}

/** 加载当前 Thread 的 Run 元数据；失败时不阻断消息历史渲染。 */
export function useThreadRuns(
  threadId: string,
  options: UseThreadRunsOptions = {},
): UseThreadRunsResult {
  const loader = options.loader ?? fetchThreadRuns;
  const [state, setState] = useState<ThreadRunsState>(() => ({
    threadId,
    runs: [],
    isLoading: true,
  }));
  const [revision, setRevision] = useState(0);
  const generationRef = useRef(0);

  useEffect(() => {
    generationRef.current += 1;
    const generation = generationRef.current;
    const controller = new AbortController();

    void loader({ threadId, limit: 200, signal: controller.signal }).then(
      (nextRuns) => {
        if (controller.signal.aborted || generation !== generationRef.current) {
          return;
        }
        setState({ threadId, runs: nextRuns, isLoading: false });
      },
      () => {
        if (controller.signal.aborted || generation !== generationRef.current) {
          return;
        }
        // 耗时是增强信息，查询失败时保留消息主流程，不展示客户端猜测值。
        setState((current) =>
          current.threadId === threadId
            ? { ...current, isLoading: false }
            : { threadId, runs: [], isLoading: false },
        );
      },
    );

    return () => controller.abort();
  }, [loader, revision, threadId]);

  const retry = useCallback(() => {
    setState((current) =>
      current.threadId === threadId ? { ...current, isLoading: true } : current,
    );
    setRevision((current) => current + 1);
  }, [threadId]);

  return state.threadId === threadId
    ? { ...state, retry }
    : { threadId, runs: [], isLoading: true, retry };
}
