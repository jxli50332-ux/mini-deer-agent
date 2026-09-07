import { describe, expect, it, vi } from "vitest";

import {
  deleteThread,
  fetchThreadList,
  parseThreadList,
  type ThreadDeleteFetchLike,
  type ThreadListClientError,
  type ThreadListFetchLike,
  type ThreadTitleFetchLike,
  updateThreadTitle,
} from "@/features/threads/api/thread-list";

const THREAD_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_THREAD_ID = "22222222-2222-4222-8222-222222222222";

function wireThread(
  threadId: string,
  updatedAt: string,
  title: string | null = "北京天气",
) {
  return {
    thread_id: threadId,
    title,
    status: "idle",
    project_id: null,
    created_at: "2026-08-26T08:00:00+00:00",
    updated_at: updatedAt,
  };
}

describe("最近 Thread 列表 client", () => {
  it("把服务端 snake_case 数组校验为前端领域对象", () => {
    const parsed = parseThreadList([
      wireThread(OTHER_THREAD_ID, "2026-08-26T09:00:00+00:00"),
      wireThread(THREAD_ID, "2026-08-26T08:30:00+00:00"),
    ]);

    expect(parsed).toEqual([
      {
        threadId: OTHER_THREAD_ID,
        title: "北京天气",
        status: "idle",
        projectId: null,
        createdAt: "2026-08-26T08:00:00+00:00",
        updatedAt: "2026-08-26T09:00:00+00:00",
      },
      {
        threadId: THREAD_ID,
        title: "北京天气",
        status: "idle",
        projectId: null,
        createdAt: "2026-08-26T08:00:00+00:00",
        updatedAt: "2026-08-26T08:30:00+00:00",
      },
    ]);
  });

  it("接受旧 Thread 的空标题，并拒绝非法标题类型", () => {
    expect(
      parseThreadList([
        wireThread(THREAD_ID, "2026-08-26T09:00:00+00:00", null),
      ])[0]?.title,
    ).toBeNull();
    expect(() =>
      parseThreadList([
        {
          ...wireThread(THREAD_ID, "2026-08-26T09:00:00+00:00"),
          title: 42,
        },
      ]),
    ).toThrow("title 必须是非空字符串或 null");
  });

  it("校验 nullable 项目归属，并保留普通聊天的 null", () => {
    expect(
      parseThreadList([wireThread(THREAD_ID, "2026-08-26T09:00:00+00:00")])[0]
        ?.projectId,
    ).toBeNull();
    expect(
      parseThreadList([
        {
          ...wireThread(THREAD_ID, "2026-08-26T09:00:00+00:00"),
          project_id: OTHER_THREAD_ID,
        },
      ])[0]?.projectId,
    ).toBe(OTHER_THREAD_ID);
    expect(() =>
      parseThreadList([
        {
          ...wireThread(THREAD_ID, "2026-08-26T09:00:00+00:00"),
          project_id: "string",
        },
      ]),
    ).toThrow("project_id 必须是 UUID 或 null");
  });

  it("拒绝重复身份、非法状态和无效时间", () => {
    expect(() =>
      parseThreadList([
        wireThread(THREAD_ID, "2026-08-26T09:00:00+00:00"),
        wireThread(THREAD_ID, "2026-08-26T08:00:00+00:00"),
      ]),
    ).toThrow("Thread 列表包含重复 ID");
    expect(() =>
      parseThreadList([
        { ...wireThread(THREAD_ID, "invalid"), status: "deleted" },
      ]),
    ).toThrow("Thread status 不受支持");
    expect(() => parseThreadList([wireThread(THREAD_ID, "invalid")])).toThrow(
      "updated_at 必须是有效日期时间",
    );
  });

  it("使用受限 limit 请求正式版本化接口", async () => {
    const fetcher = vi.fn<ThreadListFetchLike>(() =>
      Promise.resolve(
        Response.json([wireThread(THREAD_ID, "2026-08-26T09:00:00+00:00")]),
      ),
    );

    const result = await fetchThreadList({ limit: 20 }, { fetcher });

    expect(result[0]?.threadId).toBe(THREAD_ID);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/threads?limit=20",
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
  });

  it("在发出请求前拒绝越界 limit", async () => {
    await expect(fetchThreadList({ limit: 101 })).rejects.toMatchObject({
      name: "ThreadListClientError",
      code: "invalid_request",
      retryable: false,
    } satisfies Partial<ThreadListClientError>);
  });

  it("通过 PATCH 更新标题，并使用服务端返回值作为新事实", async () => {
    const fetcher = vi.fn<ThreadTitleFetchLike>((_input, init) => {
      expect(init?.body).toBe(JSON.stringify({ title: "新的 会话标题" }));
      return Promise.resolve(
        Response.json(
          wireThread(THREAD_ID, "2026-08-26T10:00:00+00:00", "新的会话标题"),
        ),
      );
    });

    const updated = await updateThreadTitle(
      { threadId: THREAD_ID, title: "  新的   会话标题  " },
      { fetcher },
    );

    expect(updated.title).toBe("新的会话标题");
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/threads/${THREAD_ID}`,
      expect.objectContaining({ method: "PATCH" }),
    );
  });

  it("通过 DELETE 删除规范 UUID，并只接受 204 空响应", async () => {
    const fetcher = vi.fn<ThreadDeleteFetchLike>(() =>
      Promise.resolve(new Response(null, { status: 204 })),
    );

    await deleteThread({ threadId: THREAD_ID }, { fetcher });

    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/threads/${THREAD_ID}`,
      expect.objectContaining({ method: "DELETE", cache: "no-store" }),
    );
  });

  it("把活动 Thread 的 409 映射为可理解的删除错误", async () => {
    const fetcher = vi.fn<ThreadDeleteFetchLike>(() =>
      Promise.resolve(Response.json({}, { status: 409 })),
    );

    await expect(
      deleteThread({ threadId: THREAD_ID }, { fetcher }),
    ).rejects.toThrow("会话正在运行，结束后才能删除");
  });
});
