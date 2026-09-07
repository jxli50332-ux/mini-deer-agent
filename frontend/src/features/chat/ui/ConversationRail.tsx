import { Fragment, useEffect, useState, type FormEvent } from "react";

import type { ThreadSummary } from "@/entities/thread/model/types";
import type { ChatRunPhase } from "@/features/chat/model/reducer";
import { WorkspaceLauncher } from "@/features/workspace/ui/WorkspaceLauncher";

interface ConversationRailProps {
  readonly phase: ChatRunPhase;
  readonly currentThreadId: string;
  readonly timelineItemCount: number;
  readonly threads: readonly ThreadSummary[];
  readonly isThreadListLoading: boolean;
  readonly threadListError: string | null;
  readonly isNewThreadDisabled: boolean;
  readonly isThreadSwitchDisabled: boolean;
  readonly collapsed: boolean;
  readonly mobileOpen: boolean;
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
  readonly onRenameThread: (threadId: string, title: string) => Promise<void>;
  readonly onDeleteThread: (threadId: string) => Promise<void>;
  readonly onReferenceProjectFile?: (path: string) => void;
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
  timelineItemCount,
  threads,
  isThreadListLoading,
  threadListError,
  isNewThreadDisabled,
  isThreadSwitchDisabled,
  collapsed,
  mobileOpen,
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
  onRenameThread,
  onDeleteThread,
  onReferenceProjectFile = () => undefined,
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
  const hasPersistedCurrentThread = threads.some(
    (thread) => thread.threadId === currentThreadId,
  );
  const currentProjectId =
    threads.find((thread) => thread.threadId === currentThreadId)?.projectId ??
    null;
  const ordinaryThreads = threads.filter((thread) => thread.projectId == null);
  const isCompact = collapsed && !mobileOpen;

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
      setConfirmingDeleteThreadId(null);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "无法删除会话");
    } finally {
      setIsDeleting(false);
    }
  };

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
        />

        {isCompact ? (
          <button
            className="new-thread-button new-thread-button--compact"
            type="button"
            disabled={isNewThreadDisabled}
            onClick={onCreateNewThread}
            aria-label="新会话"
          >
            <span aria-hidden="true">＋</span>
          </button>
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

            <nav className="conversation-list" aria-label="最近会话">
              <p className="conversation-list__label">最近会话</p>
              {!hasPersistedCurrentThread && (
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
              {ordinaryThreads.map((thread) => {
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
                        onChange={(event) => setTitleDraft(event.target.value)}
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
                    title={`thread_id: ${thread.threadId}`}
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
                        {isCurrent
                          ? PHASE_SUMMARIES[phase]
                          : isRunning
                            ? "正在后台运行"
                            : `${THREAD_STATUS_SUMMARIES[thread.status]} · ${formatUpdatedAt(thread.updatedAt)}`}
                      </span>
                    </button>
                    <button
                      className="conversation-preview__rename"
                      type="button"
                      aria-label={`重命名会话 ${displayTitle}`}
                      disabled={isRenaming}
                      onClick={() => beginRename(thread)}
                    >
                      改名
                    </button>
                    <button
                      className="conversation-preview__delete"
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
                );
              })}
              {isThreadListLoading && ordinaryThreads.length === 0 && (
                <p className="conversation-list__state" role="status">
                  正在加载最近会话……
                </p>
              )}
              {threadListError !== null && (
                <div className="conversation-list__error" role="alert">
                  <span>{threadListError}</span>
                  <button type="button" onClick={onRetryThreadList}>
                    重试
                  </button>
                </div>
              )}
            </nav>

            <footer className="rail-footer">
              <span className="rail-footer__dot" aria-hidden="true" />
              本地开发环境
            </footer>
          </>
        )}
      </aside>
    </Fragment>
  );
}
