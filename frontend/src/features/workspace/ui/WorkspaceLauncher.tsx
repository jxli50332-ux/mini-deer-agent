import { ProjectFiles } from "./ProjectFiles";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import type { ProjectSummary } from "@/entities/project/model/types";
import type { ThreadSummary } from "@/entities/thread/model/types";
import { useProjects } from "@/features/workspace/model/use-projects";
import { ProjectManager } from "@/features/workspace/ui/ProjectManager";
import "@/features/workspace/ui/workspace.css";

const PROJECT_STATUS_TEXT: Record<ProjectSummary["status"], string> = {
  available: "可用",
  missing: "目录缺失",
  unavailable: "无法访问",
  changed: "目录已替换",
};

function threadTitle(thread: ThreadSummary): string {
  return thread.title ?? `会话 ${thread.threadId.slice(0, 8)}`;
}

const PINNED_PROJECTS_KEY = "mini-deer-agent.navigation.pinned-projects.v1";

function readPinnedProjects(): readonly string[] {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(PINNED_PROJECTS_KEY) ?? "[]",
    );
    return Array.isArray(value)
      ? value.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
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

/** 项目与会话直接投影在左侧栏；弹窗只负责登记管理，项目随页面自动加载。 */
export function WorkspaceLauncher({
  compact,
  currentThreadId = "",
  activeProjectId = null,
  threadSwitchingDisabled = false,
  onSelectThread = () => undefined,
  onBeforeCreateProjectThread = () => Promise.resolve(true),
  onProjectThreadCreated = () => undefined,
  discardedProjectThreadId = null,
  projectDraftError = null,
  activeThreadIds = [],
  projectFileTreeRevision = 0,
  onCloseNavigation = () => undefined,
  onReferenceProjectFile = () => undefined,
  onRenameThread = () => Promise.resolve(),
  onDeleteThread = () => Promise.resolve(),
  indexedThreads = [],
  onProjectsChanged = () => undefined,
  loadAllProjects = false,
  onThreadIndexInvalidated = () => undefined,
}: {
  readonly compact: boolean;
  readonly currentThreadId?: string;
  readonly activeProjectId?: string | null;
  readonly threadSwitchingDisabled?: boolean;
  readonly onSelectThread?: (threadId: string) => void;
  readonly onBeforeCreateProjectThread?: () => Promise<boolean>;
  readonly onProjectThreadCreated?: (threadId: string) => void;
  readonly discardedProjectThreadId?: string | null;
  readonly projectDraftError?: string | null;
  readonly activeThreadIds?: readonly string[];
  readonly projectFileTreeRevision?: number;
  readonly onCloseNavigation?: () => void;
  readonly onReferenceProjectFile?: (path: string) => void;
  readonly onRenameThread?: (threadId: string, title: string) => Promise<void>;
  readonly onDeleteThread?: (threadId: string) => Promise<void>;
  readonly indexedThreads?: readonly ThreadSummary[];
  readonly onProjectsChanged?: (projects: readonly ProjectSummary[]) => void;
  readonly loadAllProjects?: boolean;
  readonly onThreadIndexInvalidated?: () => void;
}) {
  const projects = useProjects();
  const dialog = useRef<HTMLDialogElement>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const loadMoreProjectsRef = useRef<HTMLButtonElement>(null);
  const loadMoreThreadsRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [threadTitleDraft, setThreadTitleDraft] = useState("");
  const [confirmingDeleteThreadId, setConfirmingDeleteThreadId] = useState<
    string | null
  >(null);
  const [threadActionError, setThreadActionError] = useState<string | null>(
    null,
  );
  const [threadActionPending, setThreadActionPending] = useState(false);
  const [pinnedProjectIds, setPinnedProjectIds] =
    useState<readonly string[]>(readPinnedProjects);
  const busy = projects.pending !== null;
  const projectThreadCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const thread of indexedThreads) {
      if (thread.projectId !== null) {
        counts.set(thread.projectId, (counts.get(thread.projectId) ?? 0) + 1);
      }
    }
    return counts;
  }, [indexedThreads]);
  const projectRunningCounts = useMemo(() => {
    const active = new Set(activeThreadIds);
    const counts = new Map<string, number>();
    for (const thread of indexedThreads) {
      if (thread.projectId !== null && active.has(thread.threadId)) {
        counts.set(thread.projectId, (counts.get(thread.projectId) ?? 0) + 1);
      }
    }
    return counts;
  }, [activeThreadIds, indexedThreads]);
  const orderedProjects = useMemo(() => {
    const pinned = new Set(pinnedProjectIds);
    return [...projects.items].sort((left, right) => {
      const pinOrder =
        Number(pinned.has(right.projectId)) -
        Number(pinned.has(left.projectId));
      if (pinOrder !== 0) return pinOrder;
      const timeOrder =
        Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
      return timeOrder || left.name.localeCompare(right.name, "zh-CN");
    });
  }, [pinnedProjectIds, projects.items]);

  useEffect(
    () => onProjectsChanged(projects.items),
    [onProjectsChanged, projects.items],
  );

  useEffect(() => {
    if (
      loadAllProjects &&
      projects.pending === null &&
      projects.nextOffset !== null
    ) {
      void projects.loadMore();
    }
  }, [loadAllProjects, projects]);

  const toggleProjectPin = (projectId: string) => {
    setPinnedProjectIds((current) => {
      const next = current.includes(projectId)
        ? current.filter((item) => item !== projectId)
        : [projectId, ...current];
      try {
        localStorage.setItem(PINNED_PROJECTS_KEY, JSON.stringify(next));
      } catch {
        // 无持久存储时仍允许在当前页面置顶。
      }
      return next;
    });
  };

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        const projectButton = loadMoreProjectsRef.current;
        const threadButton = loadMoreThreadsRef.current;
        if (projectButton !== null && !projectButton.disabled)
          projectButton.click();
        if (threadButton !== null && !threadButton.disabled)
          threadButton.click();
      },
      { rootMargin: "160px 0px" },
    );
    if (loadMoreProjectsRef.current !== null)
      observer.observe(loadMoreProjectsRef.current);
    if (loadMoreThreadsRef.current !== null)
      observer.observe(loadMoreThreadsRef.current);
    return () => observer.disconnect();
  }, [
    projects.nextOffset,
    projects.nextProjectThreadOffset,
    projects.selectedProjectId,
  ]);

  const openManager = () => {
    dialog.current?.showModal();
    setDialogOpen(true);
  };
  const closeManager = () => {
    dialog.current?.close();
    setDialogOpen(false);
  };
  const pickDirectory = () => {
    void projects.pickDirectory();
  };
  const selectThread = (threadId: string) => {
    onSelectThread(threadId);
    onCloseNavigation();
    closeManager();
  };

  const submitThreadRename = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (editingThreadId === null || threadActionPending) return;
    const title = threadTitleDraft.trim().replace(/\s+/g, " ");
    if (title.length < 1 || title.length > 60) {
      setThreadActionError("标题必须包含 1 到 60 个字符");
      return;
    }
    setThreadActionPending(true);
    setThreadActionError(null);
    try {
      await onRenameThread(editingThreadId, title);
      projects.syncProjectThreadTitle(editingThreadId, title);
      setEditingThreadId(null);
    } catch (error) {
      setThreadActionError(
        error instanceof Error ? error.message : "无法更新会话标题",
      );
    } finally {
      setThreadActionPending(false);
    }
  };

  const confirmThreadDelete = async (threadId: string) => {
    if (threadActionPending) return;
    setThreadActionPending(true);
    setThreadActionError(null);
    try {
      await onDeleteThread(threadId);
      projects.removeProjectThread(threadId);
      setConfirmingDeleteThreadId(null);
    } catch (error) {
      setThreadActionError(
        error instanceof Error ? error.message : "无法删除会话",
      );
    } finally {
      setThreadActionPending(false);
    }
  };

  return (
    <section className="project-sidebar" data-compact={compact}>
      {compact ? (
        <button
          type="button"
          className="project-launcher"
          aria-label="项目"
          title="项目"
          data-compact={compact}
          onClick={openManager}
        >
          <svg
            viewBox="0 0 24 24"
            width="19"
            height="19"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            aria-hidden="true"
          >
            <path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z" />
            <path d="M3 9h18" />
          </svg>
        </button>
      ) : (
        <>
          <div className="project-sidebar__heading">
            <span>项目</span>
            <div className="project-sidebar__heading-actions">
              <button
                type="button"
                aria-label="选择项目文件夹"
                title="选择项目文件夹"
                disabled={busy}
                onClick={pickDirectory}
              >
                ＋
              </button>
              <button
                type="button"
                aria-label="项目"
                title="管理项目"
                onClick={openManager}
              >
                ···
              </button>
            </div>
          </div>
          {!dialogOpen &&
            (projects.pending === "project_threads" ||
              projects.pending === "create_thread" ||
              projects.pending === "pick") && (
              <p className="project-sidebar__feedback" role="status">
                {projects.pending === "create_thread"
                  ? "正在创建项目会话…"
                  : projects.pending === "pick"
                    ? "请选择一个本地文件夹…"
                    : "正在加载项目会话…"}
              </p>
            )}
          {!dialogOpen && projects.error !== null && (
            <div className="project-sidebar__feedback" role="alert">
              <span>{projects.error}</span>
              <button type="button" onClick={() => void projects.refresh()}>
                重试
              </button>
            </div>
          )}
          {!dialogOpen && projectDraftError !== null && (
            <p className="project-sidebar__feedback" role="alert">
              {projectDraftError}
            </p>
          )}
          {!dialogOpen && projects.notice !== null && (
            <p className="project-sidebar__feedback" role="status">
              {projects.notice}
            </p>
          )}
          {projects.pending === "refresh" && projects.items.length === 0 ? (
            <div
              className="navigation-skeleton navigation-skeleton--projects"
              role="status"
              aria-label="正在加载项目"
            >
              <span />
              <span />
              <span />
            </div>
          ) : projects.items.length === 0 ? (
            <button
              type="button"
              className="project-sidebar__empty"
              disabled={busy}
              onClick={pickDirectory}
            >
              选择项目文件夹
            </button>
          ) : (
            <ul className="project-sidebar__projects">
              {orderedProjects.map((project) => {
                const expanded =
                  projects.selectedProjectId === project.projectId;
                const active = activeProjectId === project.projectId;
                const pinned = pinnedProjectIds.includes(project.projectId);
                const projectThreadCount = projectThreadCounts.get(
                  project.projectId,
                );
                const projectRunningCount =
                  projectRunningCounts.get(project.projectId) ?? 0;
                const threads = projects.projectThreads.filter(
                  (thread) => thread.threadId !== discardedProjectThreadId,
                );
                return (
                  <li
                    key={project.projectId}
                    data-expanded={expanded}
                    data-active={active}
                    data-pinned={pinned}
                  >
                    <div className="project-sidebar__project-row">
                      <button
                        type="button"
                        className="project-sidebar__project"
                        aria-label={`${expanded ? "收起" : "展开"}项目 ${project.name}`}
                        aria-expanded={expanded}
                        disabled={busy}
                        onClick={() => {
                          if (expanded) projects.closeProject();
                          else void projects.openProject(project);
                        }}
                      >
                        <svg
                          viewBox="0 0 24 24"
                          width="16"
                          height="16"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.6"
                          aria-hidden="true"
                        >
                          <path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z" />
                          <path d="M3 9h18" />
                        </svg>
                        <strong>{project.name}</strong>
                        {projectThreadCount !== undefined && (
                          <span className="project-sidebar__count">
                            {projectThreadCount}
                          </span>
                        )}
                        <i
                          aria-label={
                            projectRunningCount > 0
                              ? `${projectRunningCount} 个会话正在运行`
                              : PROJECT_STATUS_TEXT[project.status]
                          }
                          data-status={project.status}
                          data-running={projectRunningCount > 0}
                        />
                      </button>
                      <span className="sidebar-tooltip" aria-hidden="true">
                        {project.name}
                        {"\n"}
                        {project.rootPath}
                      </span>
                      <div className="project-sidebar__project-actions">
                        <button
                          type="button"
                          className="project-sidebar__pin"
                          aria-label={`${pinned ? "取消置顶" : "置顶"}项目 ${project.name}`}
                          aria-pressed={pinned}
                          data-visible={pinned}
                          onClick={() => toggleProjectPin(project.projectId)}
                        >
                          {pinned ? "★" : "☆"}
                        </button>
                        <button
                          type="button"
                          className="project-sidebar__new-thread"
                          aria-label={`在项目 ${project.name} 中新建会话`}
                          title="新建项目会话"
                          disabled={
                            busy ||
                            threadSwitchingDisabled ||
                            project.status !== "available"
                          }
                          onClick={() => {
                            void (async () => {
                              if (!(await onBeforeCreateProjectThread()))
                                return;
                              const thread = await projects.createProjectThread(
                                project,
                                globalThis.crypto.randomUUID(),
                              );
                              if (thread !== null) {
                                onThreadIndexInvalidated();
                                onProjectThreadCreated(thread.threadId);
                                onCloseNavigation();
                                closeManager();
                              }
                            })();
                          }}
                        >
                          ＋
                        </button>
                      </div>
                    </div>
                    {expanded && (
                      <div className="project-sidebar__threads">
                        {threads.length === 0 ? (
                          <p>{busy ? "正在加载…" : "暂无项目会话"}</p>
                        ) : (
                          <ul>
                            {threads.map((thread) => {
                              const current =
                                thread.threadId === currentThreadId;
                              const running = activeThreadIds.includes(
                                thread.threadId,
                              );
                              if (
                                confirmingDeleteThreadId === thread.threadId
                              ) {
                                return (
                                  <li
                                    key={thread.threadId}
                                    className="project-thread project-thread--confirm"
                                  >
                                    <span>
                                      删除“{threadTitle(thread)}
                                      ”？此操作不可撤销
                                    </span>
                                    <div className="project-thread__actions">
                                      <button
                                        type="button"
                                        disabled={threadActionPending}
                                        onClick={() =>
                                          void confirmThreadDelete(
                                            thread.threadId,
                                          )
                                        }
                                      >
                                        {threadActionPending
                                          ? "删除中…"
                                          : "确认"}
                                      </button>
                                      <button
                                        type="button"
                                        disabled={threadActionPending}
                                        onClick={() =>
                                          setConfirmingDeleteThreadId(null)
                                        }
                                      >
                                        取消
                                      </button>
                                    </div>
                                    {threadActionError !== null && (
                                      <small role="alert">
                                        {threadActionError}
                                      </small>
                                    )}
                                  </li>
                                );
                              }
                              if (editingThreadId === thread.threadId) {
                                return (
                                  <li
                                    key={thread.threadId}
                                    className="project-thread project-thread--editing"
                                  >
                                    <form
                                      onSubmit={(event) =>
                                        void submitThreadRename(event)
                                      }
                                    >
                                      <input
                                        aria-label="项目会话标题"
                                        value={threadTitleDraft}
                                        maxLength={60}
                                        disabled={threadActionPending}
                                        autoFocus
                                        onChange={(event) =>
                                          setThreadTitleDraft(
                                            event.target.value,
                                          )
                                        }
                                      />
                                      <div className="project-thread__actions">
                                        <button
                                          type="submit"
                                          disabled={threadActionPending}
                                        >
                                          保存
                                        </button>
                                        <button
                                          type="button"
                                          disabled={threadActionPending}
                                          onClick={() =>
                                            setEditingThreadId(null)
                                          }
                                        >
                                          取消
                                        </button>
                                      </div>
                                      {threadActionError !== null && (
                                        <small role="alert">
                                          {threadActionError}
                                        </small>
                                      )}
                                    </form>
                                  </li>
                                );
                              }
                              return (
                                <li
                                  key={thread.threadId}
                                  className="project-thread"
                                >
                                  <button
                                    type="button"
                                    className="project-thread__select"
                                    aria-label={`进入项目会话 ${threadTitle(thread)}`}
                                    aria-current={current ? "page" : undefined}
                                    disabled={threadSwitchingDisabled}
                                    onClick={() =>
                                      selectThread(thread.threadId)
                                    }
                                  >
                                    <span className="project-thread__copy">
                                      <strong>{threadTitle(thread)}</strong>
                                      <small>
                                        {running
                                          ? "正在后台运行"
                                          : `${thread.status === "error" ? "上次运行失败" : "可继续"} · ${formatUpdatedAt(thread.updatedAt)}`}
                                      </small>
                                    </span>
                                  </button>
                                  <span
                                    className="sidebar-tooltip"
                                    aria-hidden="true"
                                  >
                                    {threadTitle(thread)}
                                  </span>
                                  <details className="project-thread__menu">
                                    <summary
                                      role="button"
                                      aria-label={`项目会话操作 ${threadTitle(thread)}`}
                                    >
                                      ···
                                    </summary>
                                    <div className="project-thread__menu-popover">
                                      <button
                                        type="button"
                                        aria-label={`重命名项目会话 ${threadTitle(thread)}`}
                                        disabled={threadActionPending}
                                        onClick={() => {
                                          setEditingThreadId(thread.threadId);
                                          setThreadTitleDraft(
                                            threadTitle(thread),
                                          );
                                          setThreadActionError(null);
                                        }}
                                      >
                                        改名
                                      </button>
                                      <button
                                        type="button"
                                        aria-label={`删除项目会话 ${threadTitle(thread)}`}
                                        disabled={
                                          threadActionPending || running
                                        }
                                        onClick={() => {
                                          setConfirmingDeleteThreadId(
                                            thread.threadId,
                                          );
                                          setThreadActionError(null);
                                        }}
                                      >
                                        删除
                                      </button>
                                    </div>
                                  </details>
                                </li>
                              );
                            })}
                          </ul>
                        )}
                        {projects.nextProjectThreadOffset !== null && (
                          <button
                            ref={loadMoreThreadsRef}
                            type="button"
                            className="project-sidebar__refresh"
                            disabled={busy}
                            onClick={() =>
                              void projects.loadMoreProjectThreads(project)
                            }
                          >
                            {projects.pending === "more_project_threads"
                              ? "正在加载…"
                              : "加载更多项目会话"}
                          </button>
                        )}
                        {project.status === "available" ? (
                          <>
                            <p
                              className="project-sidebar__root-path"
                              title={project.rootPath}
                            >
                              {project.rootPath}
                            </p>
                            <ProjectFiles
                              key={project.projectId}
                              projectId={project.projectId}
                              rootName={project.name}
                              initiallyOpen={
                                projects.autoOpenProjectId === project.projectId
                              }
                              refreshRevision={projectFileTreeRevision}
                              loadDirectory={projects.loadDirectory}
                              loadFile={projects.loadFile}
                              canReferenceCurrentThread={active}
                              onReferenceFile={onReferenceProjectFile}
                            />
                          </>
                        ) : (
                          <p>项目目录不可用，请在管理中刷新状态。</p>
                        )}
                        <button
                          type="button"
                          className="project-sidebar__refresh"
                          disabled={busy}
                          onClick={() => void projects.openProject(project)}
                        >
                          刷新会话
                        </button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {projects.nextOffset !== null && (
            <button
              ref={loadMoreProjectsRef}
              type="button"
              className="project-sidebar__load-more"
              disabled={busy}
              onClick={() => void projects.loadMore()}
            >
              {projects.pending === "more" ? "正在加载…" : "加载更多项目"}
            </button>
          )}
        </>
      )}

      <dialog
        className="project-dialog"
        ref={dialog}
        aria-labelledby={titleId}
        onClose={() => setDialogOpen(false)}
      >
        <header className="project-dialog__header">
          <div>
            <span>MINI DEER</span>
            <h2 id={titleId}>项目工作区</h2>
          </div>
          <button
            type="button"
            className="project-dialog__close"
            aria-label="关闭项目工作区"
            onClick={closeManager}
          >
            ×
          </button>
        </header>
        <ProjectManager projects={projects} />
      </dialog>
    </section>
  );
}
