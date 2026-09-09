import { useCallback, useEffect, useState } from "react";

import type { ThreadSummary } from "@/entities/thread/model/types";
import {
  fetchThreadList,
  ThreadListClientError,
  type ThreadListLoader,
} from "@/features/threads/api/thread-list";

interface NavigationThreadIndexState {
  readonly items: readonly ThreadSummary[];
  readonly loading: boolean;
  readonly error: string | null;
}

const PAGE_SIZE = 100;

/** 建立完整但非阻塞首屏的侧栏索引，供跨项目搜索、计数和筛选使用。 */
export function useNavigationThreadIndex(
  enabled: boolean,
  loader: ThreadListLoader = fetchThreadList,
) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<NavigationThreadIndexState>({
    items: [],
    loading: enabled,
    error: null,
  });

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void (async () => {
      const indexed: ThreadSummary[] = [];
      try {
        for (let offset = 0; ; offset += PAGE_SIZE) {
          const page = await loader({
            limit: PAGE_SIZE,
            offset,
            scope: "all",
            signal: controller.signal,
          });
          indexed.push(...page);
          if (page.length < PAGE_SIZE) break;
        }
        if (controller.signal.aborted) return;
        setState({
          items: [
            ...new Map(
              indexed.map((thread) => [thread.threadId, thread]),
            ).values(),
          ],
          loading: false,
          error: null,
        });
      } catch (error) {
        if (
          controller.signal.aborted ||
          (error instanceof ThreadListClientError && error.code === "aborted")
        ) {
          return;
        }
        setState((current) => ({
          ...current,
          loading: false,
          error: "无法建立完整会话索引",
        }));
      }
    })();
    return () => controller.abort();
  }, [enabled, loader, revision]);

  const syncTitle = useCallback((threadId: string, title: string) => {
    setState((current) => ({
      ...current,
      items: current.items.map((thread) =>
        thread.threadId === threadId
          ? { ...thread, title, updatedAt: new Date().toISOString() }
          : thread,
      ),
    }));
  }, []);
  const remove = useCallback((threadId: string) => {
    setState((current) => ({
      ...current,
      items: current.items.filter((thread) => thread.threadId !== threadId),
    }));
  }, []);

  return {
    ...state,
    retry: () => {
      setState((current) => ({ ...current, loading: true, error: null }));
      setRevision((value) => value + 1);
    },
    syncTitle,
    remove,
  };
}
