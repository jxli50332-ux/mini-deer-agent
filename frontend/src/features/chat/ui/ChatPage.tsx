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
import { fetchThreadSummary } from "@/features/threads/api/thread-list";
import type { ThreadSummary } from "@/entities/thread/model/types";
import { useConversationScroll } from "@/features/chat/model/use-conversation-scroll";
import { useThreadHistory } from "@/features/threads/model/use-thread-history";
import { useThreadList } from "@/features/threads/model/use-thread-list";
import { useThreadRuns } from "@/features/threads/model/use-thread-runs";
import { useProjectThreadDraft } from "@/features/workspace/model/use-project-thread-draft";
import { createSkillInstallAuthorization } from "@/features/skills/api/skills";
import {
  buildHumanInputResponseText,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/features/chat/model/human-input";
import { projectToolResultChangesTree } from "@/features/chat/model/project-changes";
import type { ChatRunEvent } from "@/features/chat/model/events";
import type { PreparedAttachment } from "@/entities/attachment/model/attachments";
import type { BenchmarkCase } from "@/features/benchmarks/api/benchmarks";
import { BenchmarkPanel } from "@/features/benchmarks/ui/BenchmarkPanel";
import type {
  GoalClearer,
  GoalLoader,
  GoalSetter,
  GoalStopper,
} from "@/features/goals/api/thread-goal";
import { useThreadGoal } from "@/features/goals/model/use-thread-goal";
import { GoalPanel } from "@/features/goals/ui/GoalPanel";
import { OfficeWorkspace } from "@/features/office/ui/OfficeWorkspace";
import { useResizablePreference } from "@/shared/model/use-resizable-preference";
import {
  loadModelSettings,
  MODEL_SETTINGS_CHANGED_EVENT,
  saveModelSelection,
  type ModelProfile,
  type ModelSelection,
} from "@/features/models/api/models";

const RAIL_SIZE_PREFERENCE = {
  storageKey: "mini-deer-agent.layout.rail-width.v1",
  defaultValue: 280,
  minValue: 240,
  maxStoredValue: 480,
  getMaxValue: () =>
    Math.max(240, Math.min(480, (globalThis.innerWidth || 1200) * 0.45)),
} as const;

const COMPOSER_SIZE_PREFERENCE = {
  storageKey: "mini-deer-agent.layout.composer-height.v1",
  defaultValue: 88,
  minValue: 64,
  maxStoredValue: 420,
  getMaxValue: () => {
    const viewportHeight = globalThis.innerHeight || 900;
    const ratio = (globalThis.innerWidth || 1200) <= 800 ? 0.35 : 0.42;
    return Math.max(64, Math.min(420, viewportHeight * ratio));
  },
} as const;

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
  readonly goalLoader?: GoalLoader;
  readonly goalSetter?: GoalSetter;
  readonly goalStopper?: GoalStopper;
  readonly goalClearer?: GoalClearer;
  readonly modelSettingsLoader?: typeof loadModelSettings;
  readonly modelSelectionSaver?: typeof saveModelSelection;
}

interface ComposerDraftInsertion {
  readonly id: number;
  readonly threadId: string;
  readonly text: string;
}

interface SelectedBenchmark {
  readonly threadId: string;
  readonly caseId: string;
  readonly title: string;
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
  goalLoader,
  goalSetter,
  goalStopper,
  goalClearer,
  modelSettingsLoader = loadModelSettings,
  modelSelectionSaver = saveModelSelection,
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
  const [isBenchmarkPanelOpen, setIsBenchmarkPanelOpen] = useState(false);
  const [selectedBenchmark, setSelectedBenchmark] =
    useState<SelectedBenchmark | null>(null);
  const [projectFileTreeRevision, setProjectFileTreeRevision] = useState(0);
  const [fetchedThreadMetadata, setFetchedThreadMetadata] = useState<{
    readonly threadId: string;
    readonly summary: ThreadSummary;
  } | null>(null);
  const [goalEvaluationThreadId, setGoalEvaluationThreadId] = useState<
    string | null
  >(null);
  const structureChangedRunIds = useRef(new Set<string>());
  const [composerDraftInsertion, setComposerDraftInsertion] =
    useState<ComposerDraftInsertion | null>(null);
  const [modelProfiles, setModelProfiles] = useState<readonly ModelProfile[]>(
    [],
  );
  const [modelSelection, setModelSelection] = useState<ModelSelection | null>(
    null,
  );
  const [isModelLoading, setIsModelLoading] = useState(true);
  const [isModelSwitching, setIsModelSwitching] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const railSize = useResizablePreference(RAIL_SIZE_PREFERENCE);
  const composerSize = useResizablePreference(COMPOSER_SIZE_PREFERENCE);
  const nextDraftInsertionId = useRef(0);
  const loadComposerModels = useCallback(async () => {
    setIsModelLoading(true);
    try {
      const result = await modelSettingsLoader();
      setModelProfiles(result.profiles);
      setModelSelection(result.selection);
      setModelError(null);
    } catch (reason) {
      setModelError(
        reason instanceof Error ? reason.message : "无法读取模型配置",
      );
    } finally {
      setIsModelLoading(false);
    }
  }, [modelSettingsLoader]);
  useEffect(() => {
    queueMicrotask(() => void loadComposerModels());
    const reload = () => void loadComposerModels();
    globalThis.addEventListener(MODEL_SETTINGS_CHANGED_EVENT, reload);
    return () =>
      globalThis.removeEventListener(MODEL_SETTINGS_CHANGED_EVENT, reload);
  }, [loadComposerModels]);
  const switchComposerModel = useCallback(
    async (name: string) => {
      if (modelSelection === null || name === modelSelection.primaryModel)
        return;
      setIsModelSwitching(true);
      setModelError(null);
      try {
        setModelSelection(
          await modelSelectionSaver({ ...modelSelection, primaryModel: name }),
        );
      } catch (reason) {
        const failure =
          reason instanceof Error ? reason.message : "无法切换模型";
        await loadComposerModels();
        setModelError(failure);
      } finally {
        setIsModelSwitching(false);
      }
    },
    [loadComposerModels, modelSelection, modelSelectionSaver],
  );
  const {
    goal,
    isLoading: isGoalLoading,
    isMutating: isGoalMutating,
    error: goalError,
    retry: retryGoal,
    setGoal,
    stopGoal: stopGoalState,
    clearGoal,
  } = useThreadGoal(threadId, {
    ...(goalLoader === undefined ? {} : { loader: goalLoader }),
    ...(goalSetter === undefined ? {} : { setter: goalSetter }),
    ...(goalStopper === undefined ? {} : { stopper: goalStopper }),
    ...(goalClearer === undefined ? {} : { clearer: goalClearer }),
  });
  const {
    items: recentThreads,
    isLoading: isThreadListLoading,
    isLoadingMore: isThreadListLoadingMore,
    hasMore: hasMoreThreads,
    error: threadListError,
    retry: retryThreadList,
    loadMore: loadMoreThreads,
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
    discardedThreadId: discardedProjectThreadId,
    error: projectDraftError,
    requiresDiscardBeforeLeaving,
    discardBeforeLeaving: discardEmptyProjectThread,
    markCreated: markProjectThreadCreated,
    markRunStarted: markProjectThreadRunStarted,
  } = useProjectThreadDraft({ currentThreadId: threadId, deleteThread });
  const handleRunRequested = useCallback(
    (requestedThreadId: string) => {
      markProjectThreadRunStarted(requestedThreadId);
      retryThreadList();
    },
    [markProjectThreadRunStarted, retryThreadList],
  );
  const handleRunEvent = useCallback(
    (event: ChatRunEvent) => {
      if (
        event.event === "tool_result" &&
        projectToolResultChangesTree(event.payload.name, event.payload.content)
      ) {
        structureChangedRunIds.current.add(event.runId);
      }
      if (event.event === "goal_status") {
        if (event.payload.phase === "evaluating") {
          setGoalEvaluationThreadId(event.threadId);
        } else {
          setGoalEvaluationThreadId((current) =>
            current === event.threadId ? null : current,
          );
          retryGoal();
        }
      }
    },
    [retryGoal],
  );
  const handleRunSettled = useCallback(
    (settledThreadId: string, runId: string) => {
      retryThreadList();
      retryGoal();
      setGoalEvaluationThreadId((current) =>
        current === settledThreadId ? null : current,
      );
      if (structureChangedRunIds.current.delete(runId)) {
        setProjectFileTreeRevision((current) => current + 1);
      }
    },
    [retryGoal, retryThreadList],
  );
  const { state, isActive, activeThreadIds, hydrateHistory, submit, cancel } =
    useChatRun({
      threadId,
      ...(streamRunner === undefined ? {} : { streamRunner }),
      ...(cancelRunner === undefined ? {} : { cancelRunner }),
      ...(createMessageId === undefined ? {} : { createMessageId }),
      onRunRequested: handleRunRequested,
      onRunStarted: markProjectThreadRunStarted,
      onRunSettled: handleRunSettled,
      onEventReceived: handleRunEvent,
    });
  useEffect(() => {
    if (!isActive || goal === null || isGoalMutating) return;
    // 隐藏续跑期间没有伪造用户消息；短轮询让续跑计数和评估仍能及时反映服务端 checkpoint。
    const intervalId = window.setInterval(retryGoal, 1_500);
    return () => window.clearInterval(intervalId);
  }, [goal, isActive, isGoalMutating, retryGoal]);
  const history = useThreadHistory(threadId, {
    ...(historyPageLoader === undefined
      ? {}
      : { pageLoader: historyPageLoader }),
  });
  useEffect(() => {
    const listed = recentThreads.find((thread) => thread.threadId === threadId);
    if (listed !== undefined) return;
    if (isThreadListLoading) return;
    const controller = new AbortController();
    void fetchThreadSummary({ threadId, signal: controller.signal }).then(
      (summary) => setFetchedThreadMetadata({ threadId, summary }),
      () => undefined,
    );
    return () => controller.abort();
  }, [isThreadListLoading, recentThreads, threadId]);
  const stopGoal = useCallback(async () => {
    // Goal API 在服务端先收敛同 Thread Run；不要再发第二次取消请求制造假错误。
    return await stopGoalState();
  }, [stopGoalState]);
  const continueGoal = useCallback(
    (revision: string) =>
      submit("继续执行当前 Goal。", [], { goalResumeRevision: revision }),
    [submit],
  );
  const saveGoal = useCallback(
    async (objective: string, maxContinuations: number) => {
      const saved = await setGoal(objective, maxContinuations);
      if (saved) retryThreadList();
      return saved;
    },
    [retryThreadList, setGoal],
  );
  const { runs: threadRuns, retry: retryThreadRuns } = useThreadRuns(threadId, {
    ...(threadRunsLoader === undefined ? {} : { loader: threadRunsLoader }),
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
  }, [
    retryThreadList,
    retryThreadRuns,
    state.phase,
    state.runId,
    state.timeline,
  ]);

  const createNewThread = useCallback(() => {
    if (!requiresDiscardBeforeLeaving) {
      setThreadId(threadRepository.createNewCurrentThreadId());
      return;
    }
    void (async () => {
      if (!(await discardEmptyProjectThread())) return;
      // Repository 负责生成与持久化身份；改变 prop 后由 useChatRun 统一重置线程级运行状态。
      setThreadId(threadRepository.createNewCurrentThreadId());
    })();
  }, [
    discardEmptyProjectThread,
    requiresDiscardBeforeLeaving,
    threadRepository,
  ]);
  const selectThread = useCallback(
    (selectedThreadId: string) => {
      if (selectedThreadId === threadId) {
        return;
      }
      if (!requiresDiscardBeforeLeaving) {
        setThreadId(threadRepository.selectCurrentThreadId(selectedThreadId));
        return;
      }
      void (async () => {
        if (!(await discardEmptyProjectThread())) return;
        // 先持久化设备选择，再改变 React 身份；刷新页面时会恢复同一个 Thread。
        setThreadId(threadRepository.selectCurrentThreadId(selectedThreadId));
      })();
    },
    [
      discardEmptyProjectThread,
      requiresDiscardBeforeLeaving,
      threadId,
      threadRepository,
    ],
  );
  const selectCreatedProjectThread = useCallback(
    (createdThreadId: string) => {
      markProjectThreadCreated(createdThreadId);
      setThreadId(threadRepository.selectCurrentThreadId(createdThreadId));
      retryThreadList();
    },
    [markProjectThreadCreated, retryThreadList, threadRepository],
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
  const referenceProjectFile = useCallback(
    (path: string) => {
      nextDraftInsertionId.current += 1;
      setComposerDraftInsertion({
        id: nextDraftInsertionId.current,
        threadId,
        text: `请读取并参考项目文件 ${JSON.stringify(path)}：`,
      });
    },
    [threadId],
  );
  const startSkillCreation = useCallback(
    async (
      mode: "balanced" | "guided" | "automatic",
      requirement: string,
      expectedName?: string,
    ) => {
      nextDraftInsertionId.current += 1;
      const authorization =
        mode === "automatic"
          ? await createSkillInstallAuthorization({
              threadId,
              expectedName: expectedName ?? "",
              requirement,
            })
          : null;
      const modeInstruction =
        mode === "guided"
          ? "先询问我触发条件、输入输出和边界；得到回答后再生成。"
          : mode === "automatic"
            ? `自行做出合理假设，不要中途提问；只创建名为 ${JSON.stringify(authorization?.expectedName)} 的全新 Skill。依次调用 skill_manage 的 create_draft、validate_draft 和 request_install；一次性授权已在服务端绑定本次 Run、草稿和已校验内容摘要，不要索要或传递授权令牌。`
            : "先搜索 Skill 市场候选；若继续自建，请列出关键假设并生成第一版草稿。";
      await submit(
        `请使用 Skill 创作流程处理以下需求：${requirement}\n\n模式要求：${modeInstruction} 使用 skill_market_search 只读搜索，使用 skill_manage 创建并校验草稿。除自动模式使用服务端的一次性授权安装全新 Skill 外，不要安装、覆盖、启用或删除 Skill。`,
        [],
        authorization === null
          ? {}
          : {
              skillInstallAuthorizationToken: authorization.authorizationToken,
            },
      );
    },
    [submit, threadId],
  );
  const clearAppliedDraftInsertion = useCallback((id: number) => {
    setComposerDraftInsertion((current) =>
      current?.id === id ? null : current,
    );
  }, []);
  const useBenchmarkCase = useCallback(
    (item: BenchmarkCase) => {
      nextDraftInsertionId.current += 1;
      setSelectedBenchmark({
        threadId,
        caseId: item.caseId,
        title: item.title,
      });
      setComposerDraftInsertion({
        id: nextDraftInsertionId.current,
        threadId,
        text: item.prompt,
      });
    },
    [threadId],
  );
  const submitComposer = useCallback(
    async (message: string, attachments: readonly PreparedAttachment[]) => {
      const benchmark =
        selectedBenchmark?.threadId === threadId ? selectedBenchmark : null;
      const accepted = await submit(message, attachments, {
        ...(benchmark === null ? {} : { benchmarkCaseId: benchmark.caseId }),
      });
      if (accepted && benchmark !== null) setSelectedBenchmark(null);
      return accepted;
    },
    [selectedBenchmark, submit, threadId],
  );

  const listedCurrentThread = recentThreads.find(
    (thread) => thread.threadId === threadId,
  );
  const currentThreadMetadata =
    listedCurrentThread ??
    (fetchedThreadMetadata?.threadId === threadId
      ? fetchedThreadMetadata.summary
      : null);
  const hasCurrentProject =
    currentThreadMetadata?.projectId !== null &&
    currentThreadMetadata?.projectId !== undefined;

  return (
    <OfficeWorkspace
      threadId={threadId}
      projectId={currentThreadMetadata?.projectId ?? null}
      refreshKey={`${threadId}:${state.phase}`}
      hasOfficeTools={state.timeline.some(
        (item) => item.kind === "tool" && item.name?.startsWith("word_"),
      )}
    >
      <div
        className="app-shell"
        data-rail-collapsed={isRailCollapsed}
        style={
          {
            "--rail-width": `${railSize.value}px`,
            "--composer-editor-height": `${composerSize.value}px`,
          } as React.CSSProperties
        }
      >
        <ConversationRail
          phase={state.phase}
          currentThreadId={threadId}
          currentProjectId={currentThreadMetadata?.projectId ?? null}
          timelineItemCount={state.timeline.length}
          threads={recentThreads}
          isThreadListLoading={isThreadListLoading}
          threadListError={threadListError}
          isLoadingMoreThreads={isThreadListLoadingMore}
          hasMoreThreads={hasMoreThreads}
          isNewThreadDisabled={false}
          isThreadSwitchDisabled={false}
          collapsed={isRailCollapsed}
          mobileOpen={isMobileNavigationOpen}
          width={railSize.value}
          minWidth={RAIL_SIZE_PREFERENCE.minValue}
          maxWidth={RAIL_SIZE_PREFERENCE.getMaxValue()}
          onWidthChange={railSize.setValue}
          onResetWidth={railSize.reset}
          onToggleCollapsed={() => setIsRailCollapsed((current) => !current)}
          onCloseMobile={() => setIsMobileNavigationOpen(false)}
          onCreateNewThread={createNewThread}
          onSelectThread={selectThread}
          onBeforeCreateProjectThread={discardEmptyProjectThread}
          onSelectCreatedProjectThread={selectCreatedProjectThread}
          discardedProjectThreadId={discardedProjectThreadId}
          projectDraftError={projectDraftError}
          activeThreadIds={activeThreadIds}
          projectFileTreeRevision={projectFileTreeRevision}
          onRetryThreadList={retryThreadList}
          onLoadMoreThreads={loadMoreThreads}
          onRenameThread={renameTitle}
          onDeleteThread={deletePersistedThread}
          onReferenceProjectFile={referenceProjectFile}
          onStartSkillCreation={startSkillCreation}
        />
        <main className="workspace">
          <div className="thread-header-region">
            <ThreadHeader
              phase={state.phase}
              threadId={threadId}
              runId={state.runId}
              modelProfile={
                state.modelProfile ??
                (state.phase === "idle"
                  ? (threadRuns[0]?.modelProfile ?? null)
                  : null)
              }
              navigationOpen={isMobileNavigationOpen}
              onOpenNavigation={() => setIsMobileNavigationOpen(true)}
              onOpenBenchmarks={() => setIsBenchmarkPanelOpen(true)}
            />
            <GoalPanel
              key={`${threadId}:${goal?.revision ?? "none"}`}
              goal={goal}
              isLoading={isGoalLoading}
              isMutating={isGoalMutating}
              isRunActive={isActive}
              isEvaluating={goalEvaluationThreadId === threadId}
              error={goalError}
              onSet={saveGoal}
              onStop={stopGoal}
              onContinue={continueGoal}
              onClear={clearGoal}
              onRetry={retryGoal}
            />
          </div>
          <BenchmarkPanel
            open={isBenchmarkPanelOpen}
            hasProject={hasCurrentProject}
            onClose={() => setIsBenchmarkPanelOpen(false)}
            onUseCase={useBenchmarkCase}
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
                      告诉 Agent
                      你要实现、排查或理解什么。进入项目会话后，它可以读取代码、编辑文件并运行验证。
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
            editorHeight={composerSize.value}
            minEditorHeight={COMPOSER_SIZE_PREFERENCE.minValue}
            maxEditorHeight={COMPOSER_SIZE_PREFERENCE.getMaxValue()}
            onEditorHeightChange={composerSize.setValue}
            onResetEditorHeight={composerSize.reset}
            draftInsertion={
              composerDraftInsertion?.threadId === threadId
                ? composerDraftInsertion
                : null
            }
            onDraftInsertionApplied={clearAppliedDraftInsertion}
            modelOptions={modelProfiles.map((profile) => ({
              name: profile.name,
              displayName: profile.displayName,
              available: profile.supportsTools && profile.apiKeyConfigured,
            }))}
            selectedModel={modelSelection?.primaryModel ?? null}
            isModelLoading={isModelLoading}
            isModelSwitching={isModelSwitching}
            modelError={modelError}
            onModelChange={switchComposerModel}
            {...(latestTodoSnapshot === null
              ? {}
              : {
                  todoList: latestTodoSnapshot.list,
                  todoSourceStepId: latestTodoSnapshot.sourceToolItemId,
                })}
            onSubmit={submitComposer}
            onCancel={cancel}
          />
          {selectedBenchmark?.threadId === threadId && (
            <div className="benchmark-selection" role="status">
              基准任务：{selectedBenchmark.title}
              <button type="button" onClick={() => setSelectedBenchmark(null)}>
                取消标记
              </button>
            </div>
          )}
        </main>
      </div>
    </OfficeWorkspace>
  );
}
