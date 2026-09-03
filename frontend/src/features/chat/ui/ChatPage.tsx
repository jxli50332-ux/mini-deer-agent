import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createCurrentThreadRepository,
  type CurrentThreadRepository,
} from "@/entities/thread/model/current-thread-repository";
import { selectLatestTodoSnapshot } from "@/entities/todo/model/todo-list";
import {
  useChatRun,
  type ChatRunCanceller,
  type ChatStreamRunner,
} from "@/features/chat/model/use-chat-run";
import { Composer } from "@/features/chat/ui/Composer";
import { ConversationRail } from "@/features/chat/ui/ConversationRail";
import { MessageList } from "@/features/chat/ui/MessageList";
import { ThreadHeader } from "@/features/chat/ui/ThreadHeader";
import type { ThreadHistoryPageLoader } from "@/features/threads/api/thread-history";
import type { ThreadRunsLoader } from "@/features/threads/api/thread-runs";
import type {
  ThreadListLoader,
  ThreadDeleter,
  ThreadTitleUpdater,
} from "@/features/threads/api/thread-list";
import { useConversationScroll } from "@/features/chat/model/use-conversation-scroll";
import { useThreadHistory } from "@/features/threads/model/use-thread-history";
import { useThreadList } from "@/features/threads/model/use-thread-list";
import { useThreadRuns } from "@/features/threads/model/use-thread-runs";
import {
  buildHumanInputResponseText,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/features/chat/model/human-input";

interface ChatPageProps {
  readonly streamRunner?: ChatStreamRunner;
  readonly cancelRunner?: ChatRunCanceller;
  readonly currentThreadRepository?: CurrentThreadRepository;
  readonly createMessageId?: () => string;
  readonly historyPageLoader?: ThreadHistoryPageLoader;
  readonly threadRunsLoader?: ThreadRunsLoader;
  readonly threadListLoader?: ThreadListLoader;
  readonly threadTitleUpdater?: ThreadTitleUpdater;
  readonly threadDeleter?: ThreadDeleter;
}

export function ChatPage({
  streamRunner,
  cancelRunner,
  currentThreadRepository,
  createMessageId,
  historyPageLoader,
  threadRunsLoader,
  threadListLoader,
  threadTitleUpdater,
  threadDeleter,
}: ChatPageProps) {
  // Repository 在组件生命周期内保持稳定，避免 render 时反复读取浏览器存储。
  const [threadRepository] = useState(
    () => currentThreadRepository ?? createCurrentThreadRepository(),
  );
  const [threadId, setThreadId] = useState(() =>
    threadRepository.getOrCreateCurrentThreadId(),
  );
  const [isRailCollapsed, setIsRailCollapsed] = useState(false);
  const [isMobileNavigationOpen, setIsMobileNavigationOpen] = useState(false);
  const { state, isActive, hydrateHistory, submit, cancel } = useChatRun({
    threadId,
    ...(streamRunner === undefined ? {} : { streamRunner }),
    ...(cancelRunner === undefined ? {} : { cancelRunner }),
    ...(createMessageId === undefined ? {} : { createMessageId }),
  });
  const history = useThreadHistory(threadId, {
    ...(historyPageLoader === undefined
      ? {}
      : { pageLoader: historyPageLoader }),
  });
  const { runs: threadRuns, retry: retryThreadRuns } = useThreadRuns(threadId, {
    ...(threadRunsLoader === undefined ? {} : { loader: threadRunsLoader }),
  });
  const {
    items: recentThreads,
    isLoading: isThreadListLoading,
    error: threadListError,
    retry: retryThreadList,
    renameTitle,
    deleteThread,
  } = useThreadList({
    ...(threadListLoader === undefined ? {} : { loader: threadListLoader }),
    ...(threadTitleUpdater === undefined
      ? {}
      : { updater: threadTitleUpdater }),
    ...(threadDeleter === undefined ? {} : { deleter: threadDeleter }),
  });
  const {
    setViewport: setConversationViewport,
    hasUnseenContent,
    handleScroll: handleConversationScroll,
    scrollToLatest,
  } = useConversationScroll({
    threadId,
    items: state.timeline,
    isStreaming: isActive,
  });
  const lastRefreshedRunId = useRef<string | null>(null);
  const latestTodoSnapshot = useMemo(
    () => selectLatestTodoSnapshot(state.timeline),
    [state.timeline],
  );

  useEffect(() => {
    if (!history.isInitialLoading && history.error === null) {
      // Hook 和 reducer 都携带 Thread ID，旧请求迟到时会被双重拒绝。
      hydrateHistory(history.threadId, history.items);
    }
  }, [
    history.error,
    history.isInitialLoading,
    history.items,
    history.threadId,
    hydrateHistory,
  ]);

  useEffect(() => {
    const isTerminal =
      state.phase === "completed" ||
      state.phase === "failed" ||
      state.phase === "cancelled";
    if (
      !isTerminal ||
      state.runId === null ||
      lastRefreshedRunId.current === state.runId
    ) {
      return;
    }
    // Run 终态已经进入产品数据库，此时刷新列表才能看到新 Thread 和最新活动时间。
    lastRefreshedRunId.current = state.runId;
    retryThreadList();
    retryThreadRuns();
  }, [retryThreadList, retryThreadRuns, state.phase, state.runId]);

  const createNewThread = useCallback(() => {
    if (isActive) {
      return;
    }

    // Repository 负责生成与持久化身份；改变 prop 后由 useChatRun 统一重置线程级运行状态。
    setThreadId(threadRepository.createNewCurrentThreadId());
  }, [isActive, threadRepository]);
  const selectThread = useCallback(
    (selectedThreadId: string) => {
      if (isActive || selectedThreadId === threadId) {
        return;
      }
      // 先持久化设备选择，再改变 React 身份；刷新页面时会恢复同一个 Thread。
      setThreadId(threadRepository.selectCurrentThreadId(selectedThreadId));
    },
    [isActive, threadId, threadRepository],
  );
  const deletePersistedThread = useCallback(
    async (deletedThreadId: string) => {
      await deleteThread(deletedThreadId);
      if (deletedThreadId === threadId) {
        // 远端删除成功后再切身份，失败时用户仍停留在原会话并可重试。
        setThreadId(threadRepository.createNewCurrentThreadId());
      }
    },
    [deleteThread, threadId, threadRepository],
  );
  const submitHumanInput = useCallback(
    (request: HumanInputRequest, response: HumanInputResponse) =>
      submit(buildHumanInputResponseText(request, response), [], {
        humanInputResponse: response,
      }),
    [submit],
  );

  return (
    <div className="app-shell" data-rail-collapsed={isRailCollapsed}>
      <ConversationRail
        phase={state.phase}
        currentThreadId={threadId}
        timelineItemCount={state.timeline.length}
        threads={recentThreads}
        isThreadListLoading={isThreadListLoading}
        threadListError={threadListError}
        isNewThreadDisabled={isActive}
        isThreadSwitchDisabled={isActive}
        collapsed={isRailCollapsed}
        mobileOpen={isMobileNavigationOpen}
        onToggleCollapsed={() => setIsRailCollapsed((current) => !current)}
        onCloseMobile={() => setIsMobileNavigationOpen(false)}
        onCreateNewThread={createNewThread}
        onSelectThread={selectThread}
        onRetryThreadList={retryThreadList}
        onRenameThread={renameTitle}
        onDeleteThread={deletePersistedThread}
      />
      <main className="workspace">
        <ThreadHeader
          phase={state.phase}
          threadId={threadId}
          runId={state.runId}
          navigationOpen={isMobileNavigationOpen}
          onOpenNavigation={() => setIsMobileNavigationOpen(true)}
        />
        <div className="chat-stage-region">
          <section
            ref={setConversationViewport}
            className="chat-stage"
            aria-label="聊天工作区"
            onScroll={handleConversationScroll}
          >
            <div className="chat-stage__content">
              {history.isInitialLoading && state.timeline.length === 0 && (
                <div className="history-state" role="status">
                  正在恢复当前 Thread 的历史消息……
                </div>
              )}
              {!history.isInitialLoading && state.timeline.length === 0 && (
                <div className="empty-chat" aria-label="开始新对话">
                  <span className="empty-chat__mark" aria-hidden="true">
                    M
                  </span>
                  <h2>从一个真实问题开始</h2>
                  <p>
                    试试“请使用天气工具查询北京当前天气”，页面会按顺序展示模型文字和工具活动。
                  </p>
                </div>
              )}
              {history.hasMore && (
                <div className="history-controls">
                  <button
                    type="button"
                    disabled={history.isLoadingMore}
                    onClick={() => void history.loadMore()}
                  >
                    {history.isLoadingMore ? "正在加载……" : "加载更早消息"}
                  </button>
                </div>
              )}
              <MessageList
                items={state.timeline}
                phase={state.phase}
                startedAt={state.startedAt}
                runs={threadRuns}
                onSubmitHumanInput={submitHumanInput}
              />
              {history.error !== null && (
                <aside className="history-error" role="alert">
                  <strong>历史消息加载失败</strong>
                  <span>{history.error}</span>
                  <button type="button" onClick={history.retry}>
                    重新加载
                  </button>
                </aside>
              )}
              {state.error !== null && (
                <aside className="run-error" role="alert">
                  <strong>
                    {state.error.code.startsWith("cancel_")
                      ? "停止请求失败"
                      : "本轮运行失败"}
                  </strong>
                  <span>{state.error.message}</span>
                  <small>
                    {state.error.retryable
                      ? "可以稍后重新发送。"
                      : `错误代码：${state.error.code}`}
                  </small>
                </aside>
              )}
            </div>
          </section>
          {hasUnseenContent && (
            <button
              type="button"
              className="jump-to-latest"
              aria-controls="conversation-message-list"
              onClick={scrollToLatest}
            >
              <span aria-hidden="true">↓</span>
              回到最新
            </button>
          )}
        </div>
        <Composer
          key={threadId}
          isActive={isActive}
          isStopping={state.phase === "stopping"}
          {...(latestTodoSnapshot === null
            ? {}
            : {
                todoList: latestTodoSnapshot.list,
                todoSourceStepId: latestTodoSnapshot.sourceToolItemId,
              })}
          onSubmit={submit}
          onCancel={cancel}
        />
      </main>
    </div>
  );
}
