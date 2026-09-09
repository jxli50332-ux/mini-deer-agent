import { useCallback, useEffect, useRef, useState } from "react";

import type { ProjectSummary } from "@/entities/project/model/types";
import type { ThreadSummary } from "@/entities/thread/model/types";
import {
  createProjectThread as requestProjectThreadCreation,
  fetchProjectThreads,
  fetchProjectDirectory,
  fetchProjectFile,
  fetchProjects,
  ProjectClientError,
  pickProjectDirectory,
  registerProject,
  unregisterProject,
} from "@/features/workspace/api/projects";

const EXPANDED_PROJECT_KEY = "mini-deer-agent.navigation.expanded-project.v1";

function readExpandedProject(): string | null {
  try {
    return localStorage.getItem(EXPANDED_PROJECT_KEY);
  } catch {
    return null;
  }
}

function writeExpandedProject(projectId: string | null): void {
  try {
    if (projectId === null) localStorage.removeItem(EXPANDED_PROJECT_KEY);
    else localStorage.setItem(EXPANDED_PROJECT_KEY, projectId);
  } catch {
    // 浏览器禁用存储时保持当前会话内的展开状态即可。
  }
}

interface ProjectState {
  readonly items: readonly ProjectSummary[];
  readonly nextOffset: number | null;
  readonly selectedProjectId: string | null;
  readonly autoOpenProjectId: string | null;
  readonly projectThreads: readonly ThreadSummary[];
  readonly nextProjectThreadOffset: number | null;
  readonly pending:
    | "refresh"
    | "more"
    | "register"
    | "pick"
    | "unregister"
    | "project_threads"
    | "more_project_threads"
    | "create_thread"
    | null;
  readonly error: string | null;
  readonly notice: string | null;
}
const INITIAL_STATE: ProjectState = {
  items: [],
  nextOffset: null,
  selectedProjectId: null,
  autoOpenProjectId: null,
  projectThreads: [],
  nextProjectThreadOffset: null,
  pending: "refresh",
  error: null,
  notice: null,
};

/** 页面挂载自动加载项目；所有请求仍受取消与迟到响应校验保护。 */
export function useProjects() {
  const [state, setState] = useState<ProjectState>(INITIAL_STATE);
  const active = useRef<AbortController | null>(null);
  const restoreAttempted = useRef(false);

  useEffect(() => {
    // StrictMode 重挂载时取消旧请求，迟到结果不能覆盖新的页面状态。
    const controller = new AbortController();
    active.current = controller;
    void fetchProjects({ signal: controller.signal })
      .then(
        (page) => {
          if (active.current !== controller || controller.signal.aborted)
            return;
          setState((current) => ({
            ...current,
            items: page.items,
            nextOffset: page.nextOffset,
            error: null,
          }));
        },
        (error: unknown) => {
          if (active.current !== controller || controller.signal.aborted)
            return;
          setState((current) => ({
            ...current,
            error:
              error instanceof ProjectClientError
                ? error.message
                : "无法加载项目，请重试。",
          }));
        },
      )
      .finally(() => {
        if (active.current === controller) {
          active.current = null;
          setState((current) => ({ ...current, pending: null }));
        }
      });
    return () => {
      controller.abort();
      active.current?.abort();
      active.current = null;
    };
  }, []);

  /** 一次只允许一个请求；ref 门闩避免连续点击在 React 更新前重复提交。 */
  const execute = useCallback(async function execute<T>(
    kind: NonNullable<ProjectState["pending"]>,
    operation: (signal: AbortSignal) => Promise<T>,
    accept: (result: T) => void,
  ): Promise<boolean> {
    if (active.current !== null) return false;
    const controller = new AbortController();
    active.current = controller;
    setState((current) => ({
      ...current,
      pending: kind,
      error: null,
      notice: null,
    }));
    try {
      const result = await operation(controller.signal);
      if (active.current !== controller || controller.signal.aborted)
        return false;
      accept(result);
      return true;
    } catch (error) {
      if (active.current !== controller || controller.signal.aborted)
        return false;
      setState((current) => ({
        ...current,
        error:
          error instanceof ProjectClientError
            ? error.message
            : "无法完成项目请求，请重试。",
      }));
      return false;
    } finally {
      if (active.current === controller) {
        active.current = null;
        setState((current) => ({ ...current, pending: null }));
      }
    }
  }, []);

  /** 显式刷新从第一页重建状态，续页合并按项目 ID 去重。 */
  async function load(offset: number, kind: "refresh" | "more"): Promise<void> {
    await execute(
      kind,
      (signal) => fetchProjects({ offset, signal }),
      (page) =>
        setState((current) => ({
          ...current,
          items:
            kind === "more"
              ? [
                  ...new Map(
                    [...current.items, ...page.items].map((item) => [
                      item.projectId,
                      item,
                    ]),
                  ).values(),
                ]
              : page.items,
          nextOffset: page.nextOffset,
        })),
    );
  }

  /** 仅在服务器确认 201 后加入列表；失败保留表单供用户纠正。 */
  async function register(name: string, rootPath: string): Promise<boolean> {
    return execute(
      "register",
      (signal) => registerProject({ name, rootPath, signal }),
      (project) =>
        setState((current) => ({
          ...current,
          items: [
            project,
            ...current.items.filter(
              (item) => item.projectId !== project.projectId,
            ),
          ],
          // 新登记排在最前，续页位置同步后移；用户可显式刷新重建列表。
          nextOffset:
            current.nextOffset === null ? null : current.nextOffset + 1,
          notice: `已登记“${project.name}”。`,
        })),
    );
  }

  /** 原生选择完成后直接展开新项目；取消选择不改变当前项目。 */
  async function pickDirectory(): Promise<ProjectSummary | null> {
    let selected: ProjectSummary | null = null;
    await execute(
      "pick",
      (signal) => pickProjectDirectory({ signal }),
      (project) => {
        if (project === null) {
          setState((current) => ({
            ...current,
            notice: "已取消选择文件夹。",
          }));
          return;
        }
        selected = project;
        setState((current) => ({
          ...current,
          items: [
            project,
            ...current.items.filter(
              (item) => item.projectId !== project.projectId,
            ),
          ],
          nextOffset:
            current.nextOffset === null ? null : current.nextOffset + 1,
          selectedProjectId: project.projectId,
          autoOpenProjectId: project.projectId,
          projectThreads: [],
          nextProjectThreadOffset: null,
          notice: `已添加文件夹“${project.name}”。`,
        }));
      },
    );
    return selected;
  }

  /** 收到 204 才移除项目；失败保留列表，不把网络中断当作成功。 */
  async function unregister(project: ProjectSummary): Promise<boolean> {
    return execute(
      "unregister",
      (signal) =>
        unregisterProject({
          projectId: project.projectId,
          signal,
        }),
      () =>
        setState((current) => ({
          ...current,
          items: current.items.filter(
            (item) => item.projectId !== project.projectId,
          ),
          // 只删除已加载项，续页向前移动一位，避免跳过下一条登记。
          nextOffset:
            current.nextOffset === null
              ? null
              : Math.max(0, current.nextOffset - 1),
          selectedProjectId:
            current.selectedProjectId === project.projectId
              ? null
              : current.selectedProjectId,
          autoOpenProjectId:
            current.autoOpenProjectId === project.projectId
              ? null
              : current.autoOpenProjectId,
          projectThreads:
            current.selectedProjectId === project.projectId
              ? []
              : current.projectThreads,
          nextProjectThreadOffset:
            current.selectedProjectId === project.projectId
              ? null
              : current.nextProjectThreadOffset,
          notice: `已解除“${project.name}”的登记，原目录及文件已保留。`,
        })),
    );
  }

  /** 选择项目时从受保护接口重读会话，切换项目不会复用上一项目的数组。 */
  const openProject = useCallback(
    (project: ProjectSummary): Promise<boolean> =>
      execute(
        "project_threads",
        (signal) =>
          fetchProjectThreads({
            projectId: project.projectId,
            limit: 50,
            offset: 0,
            signal,
          }),
        (threads) => {
          writeExpandedProject(project.projectId);
          setState((current) => ({
            ...current,
            selectedProjectId: project.projectId,
            autoOpenProjectId: null,
            projectThreads: threads,
            nextProjectThreadOffset: threads.length === 50 ? 50 : null,
          }));
        },
      ),
    [execute],
  );

  useEffect(() => {
    if (
      restoreAttempted.current ||
      state.pending !== null ||
      state.items.length === 0
    ) {
      return;
    }
    restoreAttempted.current = true;
    const projectId = readExpandedProject();
    const project = state.items.find((item) => item.projectId === projectId);
    if (project !== undefined) void openProject(project);
  }, [openProject, state.items, state.pending]);

  async function loadMoreProjectThreads(
    project: ProjectSummary,
  ): Promise<void> {
    const offset = state.nextProjectThreadOffset;
    if (offset === null || state.selectedProjectId !== project.projectId)
      return;
    await execute(
      "more_project_threads",
      (signal) =>
        fetchProjectThreads({
          projectId: project.projectId,
          limit: 50,
          offset,
          signal,
        }),
      (threads) =>
        setState((current) => ({
          ...current,
          projectThreads: [
            ...new Map(
              [...current.projectThreads, ...threads].map((thread) => [
                thread.threadId,
                thread,
              ]),
            ).values(),
          ],
          nextProjectThreadOffset:
            threads.length === 50 ? offset + threads.length : null,
        })),
    );
  }

  /** 服务端确认 200 和归属身份后，才把新 Thread 放入当前项目列表。 */
  async function createProjectThread(
    project: ProjectSummary,
    threadId: string,
  ): Promise<ThreadSummary | null> {
    let created: ThreadSummary | null = null;
    await execute(
      "create_thread",
      (signal) =>
        requestProjectThreadCreation({
          projectId: project.projectId,
          threadId,
          signal,
        }),
      (thread) => {
        created = thread;
        setState((current) => ({
          ...current,
          selectedProjectId: project.projectId,
          projectThreads: [
            thread,
            ...(current.selectedProjectId === project.projectId
              ? current.projectThreads
              : []
            ).filter((item) => item.threadId !== thread.threadId),
          ],
          nextProjectThreadOffset:
            current.selectedProjectId === project.projectId
              ? current.nextProjectThreadOffset === null
                ? null
                : current.nextProjectThreadOffset + 1
              : null,
          notice: `已在“${project.name}”中新建会话。`,
        }));
      },
    );
    return created;
  }

  /** 文件树请求独立取消，不阻塞会话列表。 */
  const loadDirectory = useCallback(
    (projectId: string, path: string, signal: AbortSignal) =>
      fetchProjectDirectory({ projectId, path, signal }),
    [],
  );

  /** 文件预览拥有自己的取消生命周期。 */
  const loadFile = useCallback(
    (projectId: string, path: string, startLine: number, signal: AbortSignal) =>
      fetchProjectFile({ projectId, path, startLine, signal }),
    [],
  );

  return {
    ...state,
    loadFile,
    loadDirectory,
    register,
    pickDirectory,
    unregister,
    openProject,
    closeProject: () => {
      writeExpandedProject(null);
      setState((current) => ({
        ...current,
        selectedProjectId: null,
        autoOpenProjectId: null,
        projectThreads: [],
        nextProjectThreadOffset: null,
        error: null,
        notice: null,
      }));
    },
    createProjectThread,
    loadMoreProjectThreads,
    syncProjectThreadTitle: (threadId: string, title: string) =>
      setState((current) => {
        const existing = current.projectThreads.find(
          (thread) => thread.threadId === threadId,
        );
        if (existing === undefined) return current;
        const updated = {
          ...existing,
          title,
          updatedAt: new Date().toISOString(),
        };
        return {
          ...current,
          projectThreads: [
            updated,
            ...current.projectThreads.filter(
              (thread) => thread.threadId !== threadId,
            ),
          ],
        };
      }),
    removeProjectThread: (threadId: string) =>
      setState((current) => ({
        ...current,
        projectThreads: current.projectThreads.filter(
          (thread) => thread.threadId !== threadId,
        ),
        nextProjectThreadOffset:
          current.nextProjectThreadOffset === null
            ? null
            : Math.max(0, current.nextProjectThreadOffset - 1),
      })),
    refresh: () => load(0, "refresh"),
    loadMore: () =>
      state.nextOffset === null
        ? Promise.resolve()
        : load(state.nextOffset, "more"),
  };
}

export type UseProjectsResult = ReturnType<typeof useProjects>;
