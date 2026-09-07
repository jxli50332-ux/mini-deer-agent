import { describe, expect, it, vi } from "vitest";

import {
  createProjectThread,
  fetchProjectThreads,
  fetchProjects,
  pickProjectDirectory,
  registerProject,
  unregisterProject,
} from "@/features/workspace/api/projects";

const token = "offline-project-ui-test-token-12345678";
const record = {
  project_id: "11223344-1234-4234-9234-123456789012",
  name: "中文项目",
  root_path: "D:\\projects\\中文项目",
  access_mode: "read_write",
  status: "available",
  status_reason: null,
  created_at: "2026-09-03T00:00:00Z",
  updated_at: "2026-09-03T00:00:00Z",
};
const threadId = "55667788-1234-4234-9234-123456789012";
const threadRecord = {
  thread_id: threadId,
  title: null,
  status: "idle",
  project_id: record.project_id,
  created_at: "2026-09-03T01:00:00Z",
  updated_at: "2026-09-03T01:00:00Z",
};

describe("项目 API 客户端", () => {
  it("原生文件夹选择使用专用接口，并把取消作为空结果", async () => {
    const selected = vi
      .fn()
      .mockResolvedValue(Response.json(record, { status: 201 }));
    await expect(
      pickProjectDirectory({}, { fetcher: selected }),
    ).resolves.toMatchObject({
      projectId: record.project_id,
      rootPath: record.root_path,
    });
    expect(selected).toHaveBeenCalledWith(
      "/api/v1/projects/pick-directory",
      expect.objectContaining({ method: "POST", redirect: "error" }),
    );
    await expect(
      pickProjectDirectory(
        {},
        {
          fetcher: vi
            .fn()
            .mockResolvedValue(new Response(null, { status: 204 })),
        },
      ),
    ).resolves.toBeNull();
  });

  it("无需凭据调用同源项目接口，并校验真实只读登记响应", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(Response.json(record, { status: 201 }));
    const result = await registerProject(
      { name: "中文项目", rootPath: record.root_path },
      { fetcher },
    );
    expect(result.projectId).toBe(record.project_id);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        redirect: "error",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name: "中文项目", root_path: record.root_path }),
      }),
    );
    expect(JSON.stringify(result)).not.toContain(token);
  });

  it.each([
    { ...record, project_id: "string" },
    { ...record, access_mode: "write" },
    { ...record, status: "unknown" },
    { ...record, created_at: "string" },
    { ...record, status_reason: 123 },
  ])("拒绝占位示例、非法权限和损坏的响应", async (invalid) => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(Response.json(invalid, { status: 201 }));
    await expect(
      registerProject({ name: "sample", rootPath: "D:/sample" }, { fetcher }),
    ).rejects.toMatchObject({ code: "invalid_response" });
  });

  it("分页必须前进，重复 ID 不能进入项目列表", async () => {
    for (const page of [
      { items: [record], next_offset: 0 },
      { items: [record, record], next_offset: null },
    ]) {
      const fetcher = vi.fn().mockResolvedValue(Response.json(page));
      await expect(
        fetchProjects({ offset: 0 }, { fetcher }),
      ).rejects.toMatchObject({ code: "invalid_response" });
    }
  });

  it("从下一页游标续读，并保留失效目录状态", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({
        items: [
          {
            ...record,
            status: "missing",
            status_reason: "project_root_missing",
          },
        ],
        next_offset: null,
      }),
    );
    const result = await fetchProjects({ offset: 20 }, { fetcher });
    expect(result.items[0]?.status).toBe("missing");
    expect(fetcher.mock.calls[0]?.[0]).toBe(
      "/api/v1/projects?limit=20&offset=20",
    );
  });

  it.each([
    [403, "access_denied"],
    [503, "not_configured"],
    [409, "duplicate"],
  ])("HTTP %s 映射为安全提示，不回显服务端正文", async (status, code) => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        Response.json(
          { detail: { message: token } },
          { status: Number(status) },
        ),
      );
    const promise = registerProject(
      { name: "sample", rootPath: "D:/sample" },
      { fetcher },
    );
    await expect(promise).rejects.toMatchObject({ code });
    await expect(promise).rejects.not.toHaveProperty("message", token);
  });

  it("登记网络失败不自动重试，明确结果尚未确认", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("network"));
    await expect(
      registerProject({ name: "sample", rootPath: "D:/sample" }, { fetcher }),
    ).rejects.toMatchObject({ code: "unconfirmed" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("解除只发送项目 ID，接受无正文 204", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }));
    await expect(
      unregisterProject({ projectId: record.project_id }, { fetcher }),
    ).resolves.toBeUndefined();
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/projects/${record.project_id}`,
      expect.objectContaining({
        method: "DELETE",
        cache: "no-store",
        redirect: "error",
        headers: {
          Accept: "application/json",
        },
      }),
    );
    expect(fetcher.mock.calls[0]?.[1]).not.toHaveProperty("body");
  });

  it("解除的错误成功码或网络中断均不算成功，非法身份不发请求", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ success: true }))
      .mockRejectedValueOnce(new TypeError("network"));
    await expect(
      unregisterProject({ projectId: record.project_id }, { fetcher }),
    ).rejects.toMatchObject({ code: "invalid_response" });
    await expect(
      unregisterProject({ projectId: record.project_id }, { fetcher }),
    ).rejects.toMatchObject({
      code: "unconfirmed",
      message: "解除登记结果尚未确认，请先刷新项目列表核对，避免重复提交。",
    });
    await expect(
      unregisterProject({ projectId: "../../threads" }, { fetcher }),
    ).rejects.toMatchObject({ code: "invalid_request" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("按项目读取会话，并校验每条响应都属于请求项目", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json([threadRecord]));
    const result = await fetchProjectThreads(
      { projectId: record.project_id },
      { fetcher },
    );
    expect(result).toEqual([
      expect.objectContaining({ threadId, projectId: record.project_id }),
    ]);
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/projects/${record.project_id}/threads?limit=100`,
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );

    fetcher.mockResolvedValueOnce(
      Response.json([{ ...threadRecord, project_id: threadId }]),
    );
    await expect(
      fetchProjectThreads({ projectId: record.project_id }, { fetcher }),
    ).rejects.toMatchObject({ code: "invalid_response" });
  });

  it("只在 200 响应身份匹配时确认项目会话创建", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json(threadRecord))
      .mockResolvedValueOnce(
        Response.json({ ...threadRecord, thread_id: record.project_id }),
      );
    await expect(
      createProjectThread(
        { projectId: record.project_id, threadId },
        { fetcher },
      ),
    ).resolves.toMatchObject({ threadId, projectId: record.project_id });
    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      `/api/v1/projects/${record.project_id}/threads`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ thread_id: threadId }),
      }),
    );
    await expect(
      createProjectThread(
        { projectId: record.project_id, threadId },
        { fetcher },
      ),
    ).rejects.toMatchObject({ code: "invalid_response" });
  });

  it("项目会话 404 与 409 使用对应的安全提示", async () => {
    for (const [status, code] of [
      [404, "project_not_found"],
      [409, "thread_conflict"],
    ] as const) {
      const fetcher = vi
        .fn()
        .mockResolvedValue(Response.json({ detail: token }, { status }));
      await expect(
        createProjectThread(
          { projectId: record.project_id, threadId },
          { fetcher },
        ),
      ).rejects.toMatchObject({ code });
    }
  });
});
