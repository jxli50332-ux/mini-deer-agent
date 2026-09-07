import { ProjectFiles } from "./ProjectFiles";
import { useId, useRef, useState } from "react";

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
}) {
  const projects = useProjects();
  const dialog = useRef<HTMLDialogElement>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [showAllFor, setShowAllFor] = useState<string | null>(null);
  const titleId = useId();
  const busy = projects.pending !== null;

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
            <p className="project-sidebar__feedback" role="alert">
              {projects.error}
            </p>
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
            <p className="project-sidebar__feedback" role="status">
              正在加载项目…
            </p>
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
              {projects.items.map((project) => {
                const expanded =
                  projects.selectedProjectId === project.projectId;
                const active = activeProjectId === project.projectId;
                const threads = projects.projectThreads.filter(
                  (thread) => thread.threadId !== discardedProjectThreadId,
                );
                const showAll = showAllFor === project.projectId;
                return (
                  <li
                    key={project.projectId}
                    data-expanded={expanded}
                    data-active={active}
                  >
                    <div className="project-sidebar__project-row">
                      <button
                        type="button"
                        className="project-sidebar__project"
                        aria-label={`${expanded ? "收起" : "展开"}项目 ${project.name}`}
                        aria-expanded={expanded}
                        disabled={busy}
                        title={project.rootPath}
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
                        <i
                          title={PROJECT_STATUS_TEXT[project.status]}
                          data-status={project.status}
                        />
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
                            if (!(await onBeforeCreateProjectThread())) return;
                            const thread = await projects.createProjectThread(
                              project,
                              globalThis.crypto.randomUUID(),
                            );
                            if (thread !== null) {
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
                    {expanded && (
                      <div className="project-sidebar__threads">
                        {threads.length === 0 ? (
                          <p>{busy ? "正在加载…" : "暂无项目会话"}</p>
                        ) : (
                          <ul>
                            {threads
                              .slice(0, showAll ? undefined : 5)
                              .map((thread) => {
                                const current =
                                  thread.threadId === currentThreadId;
                                const running = activeThreadIds.includes(
                                  thread.threadId,
                                );
                                return (
                                  <li key={thread.threadId}>
                                    <button
                                      type="button"
                                      aria-label={`进入项目会话 ${threadTitle(thread)}`}
                                      aria-current={
                                        current ? "page" : undefined
                                      }
                                      disabled={threadSwitchingDisabled}
                                      onClick={() =>
                                        selectThread(thread.threadId)
                                      }
                                    >
                                      <span>{threadTitle(thread)}</span>
                                      {running && <i>运行中</i>}
                                    </button>
                                  </li>
                                );
                              })}
                          </ul>
                        )}
                        {threads.length > 5 && (
                          <button
                            type="button"
                            className="project-sidebar__refresh"
                            onClick={() =>
                              setShowAllFor(showAll ? null : project.projectId)
                            }
                          >
                            {showAll ? "收起显示" : "展开显示"}
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
