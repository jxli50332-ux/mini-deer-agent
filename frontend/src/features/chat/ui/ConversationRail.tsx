import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent,
  type UIEvent,
} from "react";

import type { ThreadSummary } from "@/entities/thread/model/types";
import type { ProjectSummary } from "@/entities/project/model/types";
import type { ChatRunPhase } from "@/features/chat/model/reducer";
import {
  filterNavigationThreads,
  type NavigationThreadScope,
  type NavigationThreadSort,
} from "@/features/threads/model/navigation-index";
import { useNavigationThreadIndex } from "@/features/threads/model/use-navigation-thread-index";
import { WorkspaceLauncher } from "@/features/workspace/ui/WorkspaceLauncher";
import { SettingsDialog } from "@/features/settings/ui/SettingsDialog";

interface ConversationRailProps {
  readonly phase: ChatRunPhase;
  readonly currentThreadId: string;
  readonly currentProjectId?: string | null;
  readonly timelineItemCount: number;
  readonly threads: readonly ThreadSummary[];
  readonly isThreadListLoading: boolean;
  readonly threadListError: string | null;
  readonly isLoadingMoreThreads?: boolean;
  readonly hasMoreThreads?: boolean;
  readonly isNewThreadDisabled: boolean;
  readonly isThreadSwitchDisabled: boolean;
  readonly collapsed: boolean;
  readonly mobileOpen: boolean;
  readonly width?: number;
  readonly minWidth?: number;
  readonly maxWidth?: number;
  readonly onWidthChange?: (width: number) => void;
  readonly onResetWidth?: () => void;
  readonly onToggleCollapsed: () => void;
  readonly onCloseMobile: () => void;
  readonly onCreateNewThread: () => void;
  readonly onSelectThread: (threadId: string) => void;
  readonly onBeforeCreateProjectThread: () => Promise<boolean>;
  readonly onSelectCreatedProjectThread: (threadId: string) => void;
  readonly discardedProjectThreadId: string | null;
  readonly projectDraftError: string | null;
  readonly activeThreadIds: readonly string[];
  readonly projectFileTreeRevision?: number;
  readonly onRetryThreadList: () => void;
  readonly onLoadMoreThreads?: () => Promise<void>;
  readonly onRenameThread: (threadId: string, title: string) => Promise<void>;
  readonly onDeleteThread: (threadId: string) => Promise<void>;
  readonly onReferenceProjectFile?: (path: string) => void;
  readonly onStartSkillCreation?: (
    mode: "balanced" | "guided" | "automatic",
    requirement: string,
    expectedName?: string,
  ) => void | Promise<void>;
}

const PHASE_SUMMARIES: Record<ChatRunPhase, string> = {
  idle: "等待第一条消息",
  connecting: "正在连接 Agent",
  streaming: "正在流式生成",
  stopping: "正在停止当前运行",
  completed: "最近一轮已完成",
  failed: "最近一轮失败",
  cancelled: "最近一轮已取消",
};

const THREAD_STATUS_SUMMARIES = {
  idle: "可继续",
  busy: "正在运行",
  error: "上次运行失败",
} as const;

const NAVIGATION_FILTER_KEY = "mini-deer-agent.navigation.filters.v1";

function readNavigationFilters(): {
  scope: NavigationThreadScope;
  sort: NavigationThreadSort;
} {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(NAVIGATION_FILTER_KEY) ?? "{}",
    );
    const record =
      typeof value === "object" && value !== null
        ? (value as Record<string, unknown>)
        : {};
    const scope: NavigationThreadScope =
      record.scope === "running" ||
      record.scope === "project" ||
      record.scope === "standalone"
        ? record.scope
        : "all";
    const sort: NavigationThreadSort =
      record.sort === "oldest" || record.sort === "title"
        ? record.sort
        : "recent";
    return { scope, sort };
  } catch {
    return { scope: "all", sort: "recent" };
  }
}

function shortThreadId(threadId: string): string {
  return threadId.slice(0, 8);
}

function titleOfThread(thread: ThreadSummary): string {
  return thread.title ?? `会话 ${shortThreadId(thread.threadId)}`;
}

function formatUpdatedAt(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function ConversationRail({
  phase,
  currentThreadId,
  currentProjectId = null,
  timelineItemCount,
  threads,
  isThreadListLoading,
  threadListError,
  isLoadingMoreThreads = false,
  hasMoreThreads = false,
  isNewThreadDisabled,
  isThreadSwitchDisabled,
  collapsed,
  mobileOpen,
  width = 280,
  minWidth = 240,
  maxWidth = 480,
  onWidthChange = () => undefined,
  onResetWidth = () => undefined,
  onToggleCollapsed,
  onCloseMobile,
  onCreateNewThread,
  onSelectThread,
  onBeforeCreateProjectThread,
  onSelectCreatedProjectThread,
  discardedProjectThreadId,
  projectDraftError,
  activeThreadIds,
  projectFileTreeRevision = 0,
  onRetryThreadList,
  onLoadMoreThreads = () => Promise.resolve(),
  onRenameThread,
  onDeleteThread,
  onReferenceProjectFile = () => undefined,
  onStartSkillCreation,
}: ConversationRailProps) {
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [isRenaming, setIsRenaming] = useState(false);
  const [confirmingDeleteThreadId, setConfirmingDeleteThreadId] = useState<
    string | null
  >(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const resizeStart = useRef<{ x: number; width: number } | null>(null);
  const [isResizing, setIsResizing] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [navigationQuery, setNavigationQuery] = useState("");
  const [navigationScope, setNavigationScope] = useState<NavigationThreadScope>(
    () => readNavigationFilters().scope,
  );
  const [navigationSort, setNavigationSort] = useState<NavigationThreadSort>(
    () => readNavigationFilters().sort,
  );
  const [projectNames, setProjectNames] = useState<ReadonlyMap<string, string>>(
    new Map(),
  );
  const hasPersistedCurrentThread =
    currentProjectId !== null ||
    threads.some((thread) => thread.threadId === currentThreadId);
  const ordinaryThreads = threads.filter((thread) => thread.projectId == null);
  const isCompact = collapsed && !mobileOpen;
  const navigationIndex = useNavigationThreadIndex(!isCompact);
  const navigationActive =
    navigationQuery.trim().length > 0 ||
    navigationScope !== "all" ||
    navigationSort !== "recent";
  const indexedResults = useMemo(
    () =>
      filterNavigationThreads(navigationIndex.items, {
        query: navigationQuery,
        scope: navigationScope,
        sort: navigationSort,
        activeThreadIds,
        projectNames,
      }),
    [
      activeThreadIds,
      navigationIndex.items,
      navigationQuery,
      navigationScope,
      navigationSort,
      projectNames,
    ],
  );
  const displayedThreads = navigationActive ? indexedResults : ordinaryThreads;
  const rememberProjects = useCallback((items: readonly ProjectSummary[]) => {
    setProjectNames(
      new Map(items.map((project) => [project.projectId, project.name])),
    );
  }, []);

  useEffect(() => {
    if (!mobileOpen) {
      return;
    }
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        onCloseMobile();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [mobileOpen, onCloseMobile]);

  useEffect(() => {
    try {
      localStorage.setItem(
        NAVIGATION_FILTER_KEY,
        JSON.stringify({ scope: navigationScope, sort: navigationSort }),
      );
    } catch {
      // 隐私模式下仅保留当前页面状态。
    }
  }, [navigationScope, navigationSort]);

  const beginRename = (thread: ThreadSummary) => {
    setEditingThreadId(thread.threadId);
    setTitleDraft(titleOfThread(thread));
    setRenameError(null);
  };

  const cancelRename = () => {
    if (isRenaming) {
      return;
    }
    setEditingThreadId(null);
    setRenameError(null);
  };

  const submitRename = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (editingThreadId === null || isRenaming) {
      return;
    }
    const normalizedTitle = titleDraft.trim().replace(/\s+/g, " ");
    if (normalizedTitle.length < 1 || normalizedTitle.length > 60) {
      setRenameError("标题必须包含 1 到 60 个字符");
      return;
    }
    setIsRenaming(true);
    setRenameError(null);
    try {
      await onRenameThread(editingThreadId, normalizedTitle);
      navigationIndex.syncTitle(editingThreadId, normalizedTitle);
      setEditingThreadId(null);
      setTitleDraft("");
    } catch (error) {
      setRenameError(
        error instanceof Error ? error.message : "无法更新会话标题",
      );
    } finally {
      setIsRenaming(false);
    }
  };

  const beginDelete = (threadId: string) => {
    setConfirmingDeleteThreadId(threadId);
    setDeleteError(null);
  };

  const cancelDelete = () => {
    if (isDeleting) {
      return;
    }
    setConfirmingDeleteThreadId(null);
    setDeleteError(null);
  };

  const confirmDelete = async (threadId: string) => {
    if (isDeleting) {
      return;
    }
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await onDeleteThread(threadId);
      navigationIndex.remove(threadId);
      setConfirmingDeleteThreadId(null);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "无法删除会话");
    } finally {
      setIsDeleting(false);
    }
  };

  const startResize = (event: PointerEvent<HTMLDivElement>) => {
    resizeStart.current = { x: event.clientX, width };
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsResizing(true);
  };

  const resize = (event: PointerEvent<HTMLDivElement>) => {
    if (resizeStart.current === null) return;
    onWidthChange(
      resizeStart.current.width + event.clientX - resizeStart.current.x,
    );
  };

  const finishResize = (event: PointerEvent<HTMLDivElement>) => {
    resizeStart.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setIsResizing(false);
  };

  const resizeWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 32 : 8;
    if (event.key === "ArrowLeft") onWidthChange(width - step);
    else if (event.key === "ArrowRight") onWidthChange(width + step);
    else if (event.key === "Home") onWidthChange(minWidth);
    else if (event.key === "End") onWidthChange(maxWidth);
    else return;
    event.preventDefault();
  };

  const loadMoreNearEnd = (event: UIEvent<HTMLDivElement>) => {
    const viewport = event.currentTarget;
    if (
      hasMoreThreads &&
      !isLoadingMoreThreads &&
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 180
    ) {
      void onLoadMoreThreads();
    }
  };

  const workspaceNavigation = (
    <WorkspaceLauncher
      compact={isCompact}
      currentThreadId={currentThreadId}
      activeProjectId={currentProjectId}
      threadSwitchingDisabled={isThreadSwitchDisabled}
      onSelectThread={onSelectThread}
      onBeforeCreateProjectThread={onBeforeCreateProjectThread}
      onProjectThreadCreated={onSelectCreatedProjectThread}
      discardedProjectThreadId={discardedProjectThreadId}
      projectDraftError={projectDraftError}
      activeThreadIds={activeThreadIds}
      projectFileTreeRevision={projectFileTreeRevision}
      onCloseNavigation={onCloseMobile}
      onReferenceProjectFile={onReferenceProjectFile}
      onRenameThread={async (threadId, title) => {
        await onRenameThread(threadId, title);
        navigationIndex.syncTitle(threadId, title);
      }}
      onDeleteThread={async (threadId) => {
        await onDeleteThread(threadId);
        navigationIndex.remove(threadId);
      }}
      indexedThreads={navigationIndex.items}
      onProjectsChanged={rememberProjects}
      loadAllProjects={navigationActive}
      onThreadIndexInvalidated={navigationIndex.retry}
    />
  );

  return (
    <Fragment>
      {mobileOpen && (
        <button
          type="button"
          className="rail-backdrop"
          aria-label="关闭会话导航"
          onClick={onCloseMobile}
        />
      )}
      <aside
        id="conversation-navigation"
        className="conversation-rail"
        aria-label="会话导航"
        data-collapsed={isCompact}
        data-mobile-open={mobileOpen}
        data-resizing={isResizing}
      >
        <div className="conversation-rail__topbar">
          <div className="brand-lockup">
            <span className="brand-mark" aria-hidden="true">
              M
            </span>
            {!isCompact && (
              <span>
                <strong>Mini Deer</strong>
                <small>Agent Workspace</small>
              </span>
            )}
          </div>
          <button
            type="button"
            className="rail-collapse-toggle"
            aria-label={collapsed ? "展开会话栏" : "收起会话栏"}
            aria-expanded={!collapsed}
            aria-controls="conversation-navigation"
            onClick={onToggleCollapsed}
          >
            {collapsed ? "»" : "«"}
          </button>
          <button
            type="button"
            className="rail-mobile-close"
            aria-label="关闭会话导航"
            onClick={onCloseMobile}
          >
            ×
          </button>
        </div>

        {isCompact ? (
          <>
            {workspaceNavigation}
            <button
              className="new-thread-button new-thread-button--compact"
              type="button"
              disabled={isNewThreadDisabled}
              onClick={onCreateNewThread}
              aria-label="新会话"
            >
              <span aria-hidden="true">＋</span>
            </button>
          </>
        ) : (
          <>
            <button
              className="new-thread-button"
              type="button"
              disabled={isNewThreadDisabled}
              onClick={() => {
                onCreateNewThread();
                onCloseMobile();
              }}
              aria-describedby="new-thread-hint"
            >
              <span aria-hidden="true">＋</span>
              新会话
            </button>
            <p className="rail-hint" id="new-thread-hint">
              {isNewThreadDisabled
                ? "当前运行结束或停止后才能创建新会话"
                : "创建独立线程，不会继承当前对话上下文"}
            </p>

            <div className="rail-navigation-controls" role="search">
              <label className="rail-navigation-search">
                <span className="sr-only">搜索会话和项目</span>
                <span aria-hidden="true">⌕</span>
                <input
                  type="search"
                  value={navigationQuery}
                  placeholder="搜索会话或项目"
                  onChange={(event) => setNavigationQuery(event.target.value)}
                />
                {navigationQuery.length > 0 && (
                  <button
                    type="button"
                    aria-label="清除搜索"
                    onClick={() => setNavigationQuery("")}
                  >
                    ×
                  </button>
                )}
              </label>
              <div className="rail-navigation-filters">
                <label>
                  <span className="sr-only">会话范围</span>
                  <select
                    aria-label="会话范围"
                    value={navigationScope}
                    onChange={(event) =>
                      setNavigationScope(
                        event.target.value as NavigationThreadScope,
                      )
                    }
                  >
                    <option value="all">全部会话</option>
                    <option value="running">仅运行中</option>
                    <option value="project">仅项目</option>
                    <option value="standalone">仅普通</option>
                  </select>
                </label>
                <label>
                  <span className="sr-only">会话排序</span>
                  <select
                    aria-label="会话排序"
                    value={navigationSort}
                    onChange={(event) =>
                      setNavigationSort(
                        event.target.value as NavigationThreadSort,
                      )
                    }
                  >
                    <option value="recent">最近更新</option>
                    <option value="oldest">最早更新</option>
                    <option value="title">标题排序</option>
                  </select>
                </label>
              </div>
            </div>

            <div
              className="conversation-rail__scroll-region"
              role="region"
              aria-label="项目与会话"
              tabIndex={0}
              onScroll={loadMoreNearEnd}
            >
              <div
                className="workspace-navigation-slot"
                hidden={navigationActive}
              >
                {workspaceNavigation}
              </div>
              <nav
                className="conversation-list"
                aria-label={navigationActive ? "会话筛选结果" : "最近会话"}
              >
                <p className="conversation-list__label">
                  {navigationActive
                    ? `筛选结果 · ${displayedThreads.length}`
                    : "最近会话"}
                </p>
                {!navigationActive && !hasPersistedCurrentThread && (
                  <div
                    className="conversation-preview conversation-preview--current"
                    aria-current="page"
                  >
                    <span className="conversation-preview__title">
                      {timelineItemCount > 0 ? "当前对话" : "新对话"}
                    </span>
                    <span className="conversation-preview__meta">
                      {PHASE_SUMMARIES[phase]}
                    </span>
                  </div>
                )}
                {displayedThreads.map((thread) => {
                  const isCurrent = thread.threadId === currentThreadId;
                  const isRunning = activeThreadIds.includes(thread.threadId);
                  const displayTitle = titleOfThread(thread);
                  if (confirmingDeleteThreadId === thread.threadId) {
                    return (
                      <div
                        key={thread.threadId}
                        className={`conversation-preview conversation-preview--confirm-delete${isCurrent ? " conversation-preview--current" : ""}`}
                        aria-current={isCurrent ? "page" : undefined}
                      >
                        <span className="conversation-preview__title">
                          删除“{displayTitle}”？
                        </span>
                        <span className="conversation-preview__delete-warning">
                          此操作不可撤销
                        </span>
                        <span className="conversation-preview__actions">
                          <button
                            type="button"
                            aria-label={`确认删除 ${displayTitle}`}
                            disabled={isDeleting}
                            onClick={() => void confirmDelete(thread.threadId)}
                          >
                            {isDeleting ? "删除中…" : "确认删除"}
                          </button>
                          <button
                            type="button"
                            disabled={isDeleting}
                            onClick={cancelDelete}
                          >
                            取消
                          </button>
                        </span>
                        {deleteError !== null && (
                          <span role="alert">{deleteError}</span>
                        )}
                      </div>
                    );
                  }
                  if (editingThreadId === thread.threadId) {
                    return (
                      <form
                        key={thread.threadId}
                        className={`conversation-preview conversation-preview--editing${isCurrent ? " conversation-preview--current" : ""}`}
                        onSubmit={(event) => void submitRename(event)}
                      >
                        <input
                          aria-label="会话标题"
                          value={titleDraft}
                          maxLength={60}
                          disabled={isRenaming}
                          onChange={(event) =>
                            setTitleDraft(event.target.value)
                          }
                          autoFocus
                        />
                        <span className="conversation-preview__actions">
                          <button type="submit" disabled={isRenaming}>
                            {isRenaming ? "保存中…" : "保存标题"}
                          </button>
                          <button
                            type="button"
                            disabled={isRenaming}
                            onClick={cancelRename}
                          >
                            取消
                          </button>
                        </span>
                        {renameError !== null && (
                          <span role="alert">{renameError}</span>
                        )}
                      </form>
                    );
                  }
                  return (
                    <div
                      key={thread.threadId}
                      className={`conversation-preview conversation-preview--persisted${isCurrent ? " conversation-preview--current" : ""}`}
                      aria-current={isCurrent ? "page" : undefined}
                      data-project-thread={thread.projectId !== null}
                    >
                      <button
                        className="conversation-preview__select"
                        type="button"
                        aria-label={`切换到会话 ${displayTitle}`}
                        aria-current={isCurrent ? "page" : undefined}
                        disabled={isThreadSwitchDisabled}
                        onClick={() => {
                          onSelectThread(thread.threadId);
                          onCloseMobile();
                        }}
                      >
                        <span className="conversation-preview__title">
                          {displayTitle}
                        </span>
                        <span className="conversation-preview__meta">
                          {thread.projectId !== null && (
                            <span className="conversation-preview__project">
                              {projectNames.get(thread.projectId) ??
                                `项目 ${thread.projectId.slice(0, 8)}`}
                            </span>
                          )}
                          {isCurrent
                            ? PHASE_SUMMARIES[phase]
                            : isRunning
                              ? "正在后台运行"
                              : `${THREAD_STATUS_SUMMARIES[thread.status]} · ${formatUpdatedAt(thread.updatedAt)}`}
                        </span>
                      </button>
                      <span className="sidebar-tooltip" aria-hidden="true">
                        {displayTitle}
                      </span>
                      <details className="conversation-preview__menu">
                        <summary
                          role="button"
                          aria-label={`会话操作 ${displayTitle}`}
                        >
                          ···
                        </summary>
                        <div className="conversation-preview__menu-popover">
                          <button
                            type="button"
                            aria-label={`重命名会话 ${displayTitle}`}
                            disabled={isRenaming}
                            onClick={() => beginRename(thread)}
                          >
                            改名
                          </button>
                          <button
                            type="button"
                            aria-label={`删除会话 ${displayTitle}`}
                            disabled={
                              isDeleting ||
                              thread.status === "busy" ||
                              (isCurrent && isThreadSwitchDisabled)
                            }
                            onClick={() => beginDelete(thread.threadId)}
                          >
                            删除
                          </button>
                        </div>
                      </details>
                    </div>
                  );
                })}
                {(navigationActive
                  ? navigationIndex.loading
                  : isThreadListLoading && ordinaryThreads.length === 0) && (
                  <div
                    className="navigation-skeleton"
                    role="status"
                    aria-label="正在加载会话"
                  >
                    <span />
                    <span />
                    <span />
                  </div>
                )}
                {!navigationActive &&
                  !isThreadListLoading &&
                  ordinaryThreads.length === 0 &&
                  threadListError === null && (
                    <p className="conversation-list__state" role="status">
                      还没有历史会话
                    </p>
                  )}
                {navigationActive &&
                  !navigationIndex.loading &&
                  indexedResults.length === 0 && (
                    <p className="conversation-list__state" role="status">
                      没有符合条件的会话
                    </p>
                  )}
                {navigationActive && navigationIndex.error !== null && (
                  <div className="conversation-list__error" role="alert">
                    <span>{navigationIndex.error}</span>
                    <button type="button" onClick={navigationIndex.retry}>
                      重试
                    </button>
                  </div>
                )}
                {!navigationActive && threadListError !== null && (
                  <div className="conversation-list__error" role="alert">
                    <span>{threadListError}</span>
                    <button type="button" onClick={onRetryThreadList}>
                      重试
                    </button>
                  </div>
                )}
                {!navigationActive && hasMoreThreads && (
                  <button
                    type="button"
                    className="conversation-list__load-more"
                    disabled={isLoadingMoreThreads}
                    onClick={() => void onLoadMoreThreads()}
                  >
                    {isLoadingMoreThreads ? "正在加载…" : "加载更多会话"}
                  </button>
                )}
              </nav>
            </div>

            <footer className="rail-footer">
              <span className="rail-footer__environment">
                <span className="rail-footer__dot" aria-hidden="true" />
                本地开发环境
              </span>
              <button
                type="button"
                className="rail-settings-button"
                aria-label="打开设置"
                onClick={() => setSettingsOpen(true)}
              >
                <span aria-hidden="true">⚙</span>
              </button>
            </footer>
          </>
        )}
        <div
          className="conversation-rail__resize-handle"
          role="separator"
          aria-label="调整侧边栏宽度"
          aria-orientation="vertical"
          aria-valuemin={minWidth}
          aria-valuemax={maxWidth}
          aria-valuenow={width}
          tabIndex={0}
          onDoubleClick={onResetWidth}
          onKeyDown={resizeWithKeyboard}
          onPointerDown={startResize}
          onPointerMove={resize}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
        />
      </aside>
      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        {...(onStartSkillCreation === undefined
          ? {}
          : { onStartSkillCreation })}
      />
    </Fragment>
  );
}
