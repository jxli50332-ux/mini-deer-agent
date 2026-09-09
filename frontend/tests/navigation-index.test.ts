import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ThreadSummary } from "@/entities/thread/model/types";
import {
  countThreadsByProject,
  filterNavigationThreads,
} from "@/features/threads/model/navigation-index";
import { useNavigationThreadIndex } from "@/features/threads/model/use-navigation-thread-index";

const projectId = "11111111-1111-4111-8111-111111111111";

function thread(
  threadId: string,
  title: string,
  updatedAt: string,
  project: string | null = null,
): ThreadSummary {
  return {
    threadId,
    title,
    status: "idle",
    projectId: project,
    createdAt: updatedAt,
    updatedAt,
  };
}

const items = [
  thread(
    "00000001-0000-4000-8000-000000000001",
    "普通会话",
    "2026-09-01T00:00:00Z",
  ),
  thread(
    "00000002-0000-4000-8000-000000000002",
    "项目对话",
    "2026-09-02T00:00:00Z",
    projectId,
  ),
];

describe("侧栏线程索引", () => {
  it("可按项目名搜索并筛选运行中会话", () => {
    expect(
      filterNavigationThreads(items, {
        query: "mini deer",
        scope: "all",
        sort: "recent",
        activeThreadIds: [],
        projectNames: new Map([[projectId, "Mini Deer"]]),
      }).map((item) => item.title),
    ).toEqual(["项目对话"]);
    expect(
      filterNavigationThreads(items, {
        query: "",
        scope: "running",
        sort: "recent",
        activeThreadIds: [items[0]!.threadId],
      }).map((item) => item.title),
    ).toEqual(["普通会话"]);
  });

  it("支持时间与标题排序并统计项目会话", () => {
    expect(
      filterNavigationThreads(items, {
        query: "",
        scope: "all",
        sort: "oldest",
        activeThreadIds: [],
      }).map((item) => item.title),
    ).toEqual(["普通会话", "项目对话"]);
    expect(countThreadsByProject(items).get(projectId)).toBe(1);
  });

  it("按页建立完整索引而不截断第一百条之后的会话", async () => {
    const hundred = Array.from({ length: 100 }, (_, index) =>
      thread(
        `10000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
        `会话 ${index}`,
        "2026-09-01T00:00:00Z",
      ),
    );
    const last = thread(
      "20000000-0000-4000-8000-000000000001",
      "第一百零一个会话",
      "2026-09-02T00:00:00Z",
    );
    const loader = vi
      .fn()
      .mockResolvedValueOnce(hundred)
      .mockResolvedValueOnce([last]);
    const { result } = renderHook(() => useNavigationThreadIndex(true, loader));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(101);
    expect(loader).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ limit: 100, offset: 100, scope: "all" }),
    );
  });
});
