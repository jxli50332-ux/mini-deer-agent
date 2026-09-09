import type { ThreadSummary } from "@/entities/thread/model/types";

export type NavigationThreadScope =
  "all" | "running" | "project" | "standalone";

export type NavigationThreadSort = "recent" | "oldest" | "title";

export interface NavigationThreadFilter {
  readonly query: string;
  readonly scope: NavigationThreadScope;
  readonly sort: NavigationThreadSort;
  readonly activeThreadIds: readonly string[];
  readonly projectNames?: ReadonlyMap<string, string>;
}

function normalized(value: string): string {
  return value.trim().toLocaleLowerCase("zh-CN");
}

function titleOf(thread: ThreadSummary): string {
  return thread.title ?? `会话 ${thread.threadId.slice(0, 8)}`;
}

/** 对完整线程索引执行稳定的本地搜索、筛选和排序。 */
export function filterNavigationThreads(
  threads: readonly ThreadSummary[],
  filter: NavigationThreadFilter,
): readonly ThreadSummary[] {
  const query = normalized(filter.query);
  const active = new Set(filter.activeThreadIds);
  return [...threads]
    .filter((thread) => {
      if (filter.scope === "running" && !active.has(thread.threadId)) {
        return false;
      }
      if (filter.scope === "project" && thread.projectId === null) return false;
      if (filter.scope === "standalone" && thread.projectId !== null)
        return false;
      if (query.length === 0) return true;
      const projectName =
        thread.projectId === null
          ? ""
          : (filter.projectNames?.get(thread.projectId) ?? "");
      return normalized(
        `${titleOf(thread)} ${thread.threadId} ${projectName}`,
      ).includes(query);
    })
    .sort((left, right) => {
      if (filter.sort === "title") {
        const titleOrder = titleOf(left).localeCompare(titleOf(right), "zh-CN");
        if (titleOrder !== 0) return titleOrder;
      } else {
        const timeOrder =
          Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
        if (timeOrder !== 0)
          return filter.sort === "oldest" ? -timeOrder : timeOrder;
      }
      return left.threadId.localeCompare(right.threadId);
    });
}

export function countThreadsByProject(
  threads: readonly ThreadSummary[],
): ReadonlyMap<string, number> {
  const counts = new Map<string, number>();
  for (const thread of threads) {
    if (thread.projectId !== null) {
      counts.set(thread.projectId, (counts.get(thread.projectId) ?? 0) + 1);
    }
  }
  return counts;
}
