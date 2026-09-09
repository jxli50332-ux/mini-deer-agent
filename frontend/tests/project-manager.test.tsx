import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterAll,
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { useProjects } from "@/features/workspace/model/use-projects";
import { WorkspaceLauncher } from "@/features/workspace/ui/WorkspaceLauncher";

const record = {
  project_id: "11223344-1234-4234-9234-123456789012",
  name: "验收项目",
  root_path: "D:/projects/sample",
  access_mode: "read_write",
  status: "available",
  status_reason: null,
  created_at: "2026-09-03T00:00:00Z",
  updated_at: "2026-09-03T00:00:00Z",
};
const existingThreadId = "55667788-1234-4234-9234-123456789012";
const newThreadId = "66778899-1234-4234-9234-123456789012";

function threadRecord(threadId: string, title: string | null) {
  return {
    thread_id: threadId,
    title,
    status: "idle",
    project_id: record.project_id,
    created_at: "2026-09-03T01:00:00Z",
    updated_at: "2026-09-03T01:00:00Z",
  };
}

/** 自动加载结束后才操作管理表单，模拟用户看到的可用状态。 */
async function loaded() {
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "刷新项目" })).not.toBeDisabled(),
  );
}

describe("项目登记面板", () => {
  const originalShow = Object.getOwnPropertyDescriptor(
    HTMLDialogElement.prototype,
    "showModal",
  );
  const originalClose = Object.getOwnPropertyDescriptor(
    HTMLDialogElement.prototype,
    "close",
  );
  beforeAll(() => {
    // jsdom 尚未实现 dialog 顶层模态机制；这里仅模拟开关，焦点与 Esc 在真实浏览器验证。
    Object.defineProperties(HTMLDialogElement.prototype, {
      showModal: {
        configurable: true,
        value(this: HTMLDialogElement) {
          this.open = true;
        },
      },
      close: {
        configurable: true,
        value(this: HTMLDialogElement) {
          this.open = false;
        },
      },
    });
  });
  afterAll(() => {
    for (const [key, descriptor] of [
      ["showModal", originalShow],
      ["close", originalClose],
    ] as const) {
      if (descriptor)
        Object.defineProperty(HTMLDialogElement.prototype, key, descriptor);
      else Reflect.deleteProperty(HTMLDialogElement.prototype, key);
    }
  });
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("标题加号选择文件夹后自动展开真实根路径和文件树", async () => {
    const picked = {
      ...record,
      name: "project-test",
      root_path: "D:/project/agentstudy/project-test",
    };
    const fetcher = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      const target =
        typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
      if (target === "/api/v1/projects/pick-directory") {
        expect(init?.method).toBe("POST");
        return Promise.resolve(Response.json(picked, { status: 201 }));
      }
      if (target.includes("/directory")) {
        return Promise.resolve(
          Response.json({
            project_id: picked.project_id,
            path: "",
            items: [
              {
                name: "src",
                path: "src",
                kind: "directory",
                status: "available",
                reason: null,
              },
              {
                name: "README.md",
                path: "README.md",
                kind: "file",
                status: "available",
                reason: null,
              },
            ],
            truncated: false,
            truncation_reason: null,
            limit: 200,
          }),
        );
      }
      return Promise.resolve(Response.json({ items: [], next_offset: null }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceLauncher compact={false} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "选择项目文件夹" }),
    );

    expect(
      (await screen.findAllByText(picked.root_path)).some((item) =>
        item.classList.contains("project-sidebar__root-path"),
      ),
    ).toBe(true);
    expect(
      screen.getByRole("button", { name: "收起目录 根目录" }),
    ).toHaveTextContent("project-test");
    expect(
      await screen.findByRole("button", { name: "预览文件 README.md" }),
    ).toBeVisible();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/pick-directory",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("页面自动加载项目，刷新重挂载后仍无需密码", async () => {
    const fetcher = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(Response.json({ items: [record], next_offset: null })),
      );
    vi.stubGlobal("fetch", fetcher);
    const { unmount } = render(<WorkspaceLauncher compact={false} />);
    expect(
      await screen.findByRole("button", { name: "展开项目 验收项目" }),
    ).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(
      JSON.stringify(fetcher.mock.calls[0]).includes(
        "X-Mini-Deer-Workspace-Token",
      ),
    ).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "项目" }));
    expect(screen.queryByLabelText("工作区访问凭据")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "锁定工作区" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("项目目录")).toBeVisible();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    unmount();
    render(<WorkspaceLauncher compact={false} />);
    expect(
      await screen.findByRole("button", { name: "展开项目 验收项目" }),
    ).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("登记成功显示服务器项目，刷新能看到目录缺失", async () => {
    let registered = false;
    const fetcher = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        registered = true;
        return Promise.resolve(Response.json(record, { status: 201 }));
      }
      return Promise.resolve(
        Response.json({
          items: registered
            ? [
                {
                  ...record,
                  status: "missing",
                  status_reason: "project_root_missing",
                },
              ]
            : [],
          next_offset: null,
        }),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceLauncher compact={false} />);
    fireEvent.click(screen.getByRole("button", { name: "项目" }));
    await loaded();
    fireEvent.change(screen.getByLabelText("项目名称"), {
      target: { value: "验收项目" },
    });
    fireEvent.change(screen.getByLabelText("项目目录"), {
      target: { value: record.root_path },
    });
    fireEvent.click(screen.getByRole("button", { name: "登记项目" }));
    expect(await screen.findByText("已登记“验收项目”。")).toBeVisible();
    expect(screen.getByLabelText("项目名称")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "刷新项目" }));
    expect(await screen.findByText("目录缺失")).toBeVisible();
  });

  it("登记拒绝保留输入，请求失败显示重试提示", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ items: [], next_offset: null }))
      .mockResolvedValueOnce(Response.json({}, { status: 409 }))
      .mockResolvedValueOnce(Response.json({}, { status: 403 }));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceLauncher compact={false} />);
    fireEvent.click(screen.getByRole("button", { name: "项目" }));
    await loaded();
    fireEvent.change(screen.getByLabelText("项目名称"), {
      target: { value: "验收项目" },
    });
    fireEvent.change(screen.getByLabelText("项目目录"), {
      target: { value: record.root_path },
    });
    fireEvent.click(screen.getByRole("button", { name: "登记项目" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("已登记");
    expect(screen.getByLabelText("项目名称")).toHaveValue("验收项目");
    fireEvent.click(screen.getByRole("button", { name: "刷新项目" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("本地项目请求被拒绝"),
    );
    expect(screen.getByLabelText("项目名称")).toHaveValue("验收项目");
    expect(screen.queryByText("已登记“验收项目”。")).not.toBeInTheDocument();
  });

  it("卸载时取消自动加载，迟到结果不恢复旧状态", async () => {
    let finish: ((response: Response) => void) | undefined;
    let requestSignal: AbortSignal | undefined;
    const fetcher = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      requestSignal = init?.signal ?? undefined;
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    });
    vi.stubGlobal("fetch", fetcher);
    const { result, unmount } = renderHook(() => useProjects());
    unmount();
    expect(requestSignal?.aborted).toBe(true);
    await act(async () => {
      finish?.(Response.json({ items: [record], next_offset: null }));
      await Promise.resolve();
    });
    expect(result.current.items).toEqual([]);
  });

  it("解除先确认，取消不请求；失败保留项目，204 后才从列表移除", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ items: [record], next_offset: null }),
      )
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetcher);
    render(<WorkspaceLauncher compact={false} />);
    fireEvent.click(screen.getByRole("button", { name: "项目" }));
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "解除登记" }));
    expect(screen.getByRole("group")).toHaveTextContent("原目录及文件会保留");
    expect(fetcher).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "解除登记" }));
    fireEvent.click(screen.getByRole("button", { name: "确认解除登记" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "解除登记结果尚未确认",
    );
    expect(screen.getAllByText("验收项目")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "确认解除登记" }));
    expect(
      await screen.findByText("已解除“验收项目”的登记，原目录及文件已保留。"),
    ).toBeVisible();
    expect(screen.queryByText("验收项目")).not.toBeInTheDocument();
    expect(screen.getByText("还没有登记项目")).toBeVisible();
  });

  it("解除等待期间禁止重复提交，续页位置随已加载项移除前移", async () => {
    let finish: ((response: Response) => void) | undefined;
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ items: [record], next_offset: 20 }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValueOnce(Response.json({ items: [], next_offset: null }));
    vi.stubGlobal("fetch", fetcher);
    const { result } = renderHook(() => useProjects());
    await waitFor(() => expect(result.current.pending).toBeNull());
    const project = result.current.items[0]!;
    let removal: Promise<boolean>;
    act(() => {
      removal = result.current.unregister(project);
    });
    expect(result.current.items).toHaveLength(1);
    expect(result.current.pending).toBe("unregister");
    await act(async () => {
      expect(await result.current.unregister(project)).toBe(false);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => {
      finish?.(new Response(null, { status: 204 }));
      await removal;
    });
    await act(async () => {
      await result.current.loadMore();
    });
    expect(fetcher.mock.calls[2]?.[0]).toBe(
      "/api/v1/projects?limit=20&offset=19",
    );
  });

  it("查看项目会话、创建持久归属后切换，并可再次进入已有会话", async () => {
    const onSelectThread = vi.fn();
    const onBeforeCreateProjectThread = vi.fn(() => Promise.resolve(true));
    const onProjectThreadCreated = vi.fn();
    const fetcher = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      const target =
        typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
      if (target.includes("/threads") && init?.method === "POST") {
        expect(init.body).toBe(JSON.stringify({ thread_id: newThreadId }));
        return Promise.resolve(Response.json(threadRecord(newThreadId, null)));
      }
      if (target.includes("/threads")) {
        return Promise.resolve(
          Response.json([threadRecord(existingThreadId, "已有项目会话")]),
        );
      }
      return Promise.resolve(
        Response.json({ items: [record], next_offset: null }),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(newThreadId);
    render(
      <WorkspaceLauncher
        compact={false}
        currentThreadId=""
        onSelectThread={onSelectThread}
        onBeforeCreateProjectThread={onBeforeCreateProjectThread}
        onProjectThreadCreated={onProjectThreadCreated}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "项目" }));
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "关闭项目工作区" }));
    fireEvent.click(screen.getByRole("button", { name: "展开项目 验收项目" }));
    expect(
      await screen.findByRole("button", {
        name: "进入项目会话 已有项目会话",
      }),
    ).toBeVisible();

    fireEvent.click(
      screen.getByRole("button", { name: "在项目 验收项目 中新建会话" }),
    );
    await waitFor(() =>
      expect(onProjectThreadCreated).toHaveBeenCalledWith(newThreadId),
    );
    expect(onBeforeCreateProjectThread).toHaveBeenCalledOnce();
    expect(onSelectThread).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("dialog", { name: "项目工作区" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "进入项目会话 已有项目会话" }),
    );
    expect(onSelectThread).toHaveBeenLastCalledWith(existingThreadId);
  });
  it("项目展开后直接展示当前已加载的全部会话", async () => {
    const threads = Array.from({ length: 6 }, (_, index) =>
      threadRecord(
        `0000000${index}-1234-4234-9234-123456789012`,
        `样例会话${index + 1}`,
      ),
    );
    const onSelectThread = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: RequestInfo | URL) =>
        Promise.resolve(
          Response.json(
            (typeof url === "string"
              ? url
              : url instanceof URL
                ? url.href
                : url.url
            ).includes("/threads")
              ? threads
              : { items: [record], next_offset: null },
          ),
        ),
      ),
    );
    render(
      <WorkspaceLauncher compact={false} onSelectThread={onSelectThread} />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "展开项目 验收项目" }),
    );
    await screen.findByRole("button", { name: "进入项目会话 样例会话1" });
    fireEvent.click(
      screen.getByRole("button", { name: "进入项目会话 样例会话6" }),
    );
    expect(onSelectThread).toHaveBeenCalledWith(threads[5]?.thread_id);
  });

  it("项目会话长标题随侧栏收缩省略且不挤占操作区", async () => {
    const longTitle =
      "先列出项目根目录，再读取 README.md，解释这个目录中所有模块的职责与依赖关系";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: RequestInfo | URL) =>
        Promise.resolve(
          Response.json(
            (typeof url === "string"
              ? url
              : url instanceof URL
                ? url.href
                : url.url
            ).includes("/threads")
              ? [threadRecord(existingThreadId, longTitle)]
              : { items: [record], next_offset: null },
          ),
        ),
      ),
    );
    render(<WorkspaceLauncher compact={false} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "展开项目 验收项目" }),
    );

    const threadButton = await screen.findByRole("button", {
      name: `进入项目会话 ${longTitle}`,
    });
    const title = threadButton.querySelector("strong");
    const actions = screen
      .getByRole("button", { name: `项目会话操作 ${longTitle}` })
      .closest(".project-thread__menu");

    expect(
      threadButton.parentElement?.querySelector(".sidebar-tooltip"),
    ).toHaveTextContent(longTitle);
    expect(getComputedStyle(threadButton).minWidth).toBe("0px");
    expect(getComputedStyle(title as HTMLElement).textOverflow).toBe(
      "ellipsis",
    );
    expect(getComputedStyle(title as HTMLElement).minWidth).toBe("0px");
    expect(getComputedStyle(actions as HTMLDivElement).flexShrink).toBe("0");
    expect(
      screen.getByRole("button", { name: "在项目 验收项目 中新建会话" }),
    ).toBeVisible();
  });

  it("项目会话支持改名与二次确认删除", async () => {
    const onRenameThread = vi.fn(() => Promise.resolve());
    const onDeleteThread = vi.fn(() => Promise.resolve());
    vi.stubGlobal(
      "fetch",
      vi.fn((url: RequestInfo | URL) => {
        const target =
          typeof url === "string"
            ? url
            : url instanceof URL
              ? url.href
              : url.url;
        return Promise.resolve(
          Response.json(
            target.includes("/threads")
              ? [threadRecord(existingThreadId, "已有项目会话")]
              : { items: [record], next_offset: null },
          ),
        );
      }),
    );
    render(
      <WorkspaceLauncher
        compact={false}
        onRenameThread={onRenameThread}
        onDeleteThread={onDeleteThread}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "展开项目 验收项目" }),
    );
    await screen.findByRole("button", {
      name: "进入项目会话 已有项目会话",
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "项目会话操作 已有项目会话",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "重命名项目会话 已有项目会话",
      }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "项目会话标题" }), {
      target: { value: "新的项目会话" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(onRenameThread).toHaveBeenCalledWith(
        existingThreadId,
        "新的项目会话",
      ),
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "项目会话操作 新的项目会话",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "删除项目会话 新的项目会话" }),
    );
    expect(screen.getByText(/此操作不可撤销/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    await waitFor(() =>
      expect(onDeleteThread).toHaveBeenCalledWith(existingThreadId),
    );
    expect(
      screen.queryByRole("button", { name: "删除项目会话 新的项目会话" }),
    ).not.toBeInTheDocument();
  });

  it("只展开一个项目并在重挂载后恢复最后展开项", async () => {
    const fetcher = vi.fn((url: RequestInfo | URL) => {
      const target =
        typeof url === "string" ? url : url instanceof URL ? url.href : url.url;
      return Promise.resolve(
        Response.json(
          target.includes("/threads")
            ? [threadRecord(existingThreadId, "恢复的项目会话")]
            : { items: [record], next_offset: null },
        ),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    const first = render(<WorkspaceLauncher compact={false} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "展开项目 验收项目" }),
    );
    expect(
      await screen.findByRole("button", {
        name: "进入项目会话 恢复的项目会话",
      }),
    ).toBeVisible();
    expect(
      localStorage.getItem("mini-deer-agent.navigation.expanded-project.v1"),
    ).toBe(record.project_id);
    first.unmount();

    render(<WorkspaceLauncher compact={false} />);
    expect(
      await screen.findByRole("button", { name: "收起项目 验收项目" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      await screen.findByRole("button", {
        name: "进入项目会话 恢复的项目会话",
      }),
    ).toBeVisible();
  });

  it("项目可置顶并持久保持排序", async () => {
    const second = {
      ...record,
      project_id: "22334455-1234-4234-9234-123456789012",
      name: "第二项目",
      root_path: "D:/projects/second",
      updated_at: "2026-09-02T00:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: RequestInfo | URL) =>
        Promise.resolve(
          Response.json(
            (typeof url === "string"
              ? url
              : url instanceof URL
                ? url.href
                : url.url
            ).includes("/threads")
              ? []
              : { items: [record, second], next_offset: null },
          ),
        ),
      ),
    );
    render(<WorkspaceLauncher compact={false} />);
    const pin = await screen.findByRole("button", {
      name: "置顶项目 第二项目",
    });
    fireEvent.click(pin);
    expect(pin).toHaveAttribute("aria-pressed", "true");
    const projectRows = document.querySelectorAll(
      ".project-sidebar__projects > li",
    );
    expect(projectRows[0]).toHaveTextContent("第二项目");
    expect(
      localStorage.getItem("mini-deer-agent.navigation.pinned-projects.v1"),
    ).toContain(second.project_id);
  });
});
