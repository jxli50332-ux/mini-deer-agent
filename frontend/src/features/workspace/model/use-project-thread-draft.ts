import { useCallback, useState } from "react";

interface ProjectThreadDraftOptions {
  readonly currentThreadId: string;
  readonly deleteThread: (threadId: string) => Promise<void>;
}

/** 管理尚未产生 Run 的项目 Thread；离开时删除，开始 Run 后转为正式会话。 */
export function useProjectThreadDraft({
  currentThreadId,
  deleteThread,
}: ProjectThreadDraftOptions) {
  const [draftThreadId, setDraftThreadId] = useState<string | null>(null);
  const [discardedThreadId, setDiscardedThreadId] = useState<string | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const requiresDiscardBeforeLeaving =
    draftThreadId !== null && draftThreadId === currentThreadId;

  const discardBeforeLeaving = useCallback(async (): Promise<boolean> => {
    if (!requiresDiscardBeforeLeaving || draftThreadId === null) {
      return true;
    }
    setError(null);
    try {
      await deleteThread(draftThreadId);
      setDiscardedThreadId(draftThreadId);
      setDraftThreadId(null);
      return true;
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "无法取消尚未运行的项目会话，请重试。",
      );
      return false;
    }
  }, [deleteThread, draftThreadId, requiresDiscardBeforeLeaving]);

  const markCreated = useCallback((threadId: string) => {
    setError(null);
    setDraftThreadId(threadId);
  }, []);

  const markRunStarted = useCallback((threadId: string) => {
    setDraftThreadId((current) => (current === threadId ? null : current));
    setError(null);
  }, []);

  return {
    draftThreadId,
    requiresDiscardBeforeLeaving,
    discardedThreadId,
    error: draftThreadId === null ? null : error,
    discardBeforeLeaving,
    markCreated,
    markRunStarted,
  };
}
