import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationRail } from "@/features/chat/ui/ConversationRail";
import { ThreadHeader } from "@/features/chat/ui/ThreadHeader";

function NavigationHarness({
  onSelect = vi.fn(),
  activeThreadIds = [],
}: {
  onSelect?: () => void;
  activeThreadIds?: readonly string[];
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      <ConversationRail
        phase="idle"
        currentThreadId="thread-current"
        timelineItemCount={0}
        threads={[
          {
            threadId: "thread-other",
            title: "另一段会话",
            status: "idle",
            projectId: null,
            createdAt: "2026-09-01T07:00:00Z",
            updatedAt: "2026-09-01T08:00:00Z",
          },
          {
            threadId: "thread-project",
            title: "项目内会话",
            status: "idle",
            projectId: "11223344-1234-4234-9234-123456789012",
            createdAt: "2026-09-01T07:00:00Z",
            updatedAt: "2026-09-01T08:00:00Z",
          },
        ]}
        isThreadListLoading={false}
        threadListError={null}
        isNewThreadDisabled={false}
        isThreadSwitchDisabled={false}
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onToggleCollapsed={() => setCollapsed((current) => !current)}
        onCloseMobile={() => setMobileOpen(false)}
        onCreateNewThread={vi.fn()}
        onSelectThread={() => onSelect()}
        onBeforeCreateProjectThread={() => Promise.resolve(true)}
        onSelectCreatedProjectThread={vi.fn()}
        discardedProjectThreadId={null}
        projectDraftError={null}
        activeThreadIds={activeThreadIds}
        onRetryThreadList={vi.fn()}
        onRenameThread={vi.fn(() => Promise.resolve())}
        onDeleteThread={vi.fn(() => Promise.resolve())}
      />
      <ThreadHeader
        phase="idle"
        threadId="thread-current"
        runId={null}
        navigationOpen={mobileOpen}
        onOpenNavigation={() => setMobileOpen(true)}
        onOpenBenchmarks={() => undefined}
      />
    </>
  );
}

describe("响应式会话导航", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("项目与最近会话共用唯一的侧栏滚动区域", () => {
    const { container } = render(<NavigationHarness />);
    const scrollRegion = screen.getByRole("region", { name: "项目与会话" });
    const projects = container.querySelector(".project-sidebar");
    const conversations = screen.getByRole("navigation", {
      name: "最近会话",
    });

    expect(projects).not.toBeNull();
    expect(scrollRegion).toContainElement(projects as HTMLElement);
    expect(scrollRegion).toContainElement(conversations);
    expect(scrollRegion).not.toContainElement(screen.getByText("本地开发环境"));
    expect(scrollRegion).not.toContainElement(
      screen.getByRole("button", { name: "新会话" }),
    );
  });

  it("侧栏宽度分隔条支持键盘调节与双击复位", () => {
    const onWidthChange = vi.fn();
    const onResetWidth = vi.fn();
    render(
      <ConversationRail
        phase="idle"
        currentThreadId="thread-current"
        timelineItemCount={0}
        threads={[]}
        isThreadListLoading={false}
        threadListError={null}
        isNewThreadDisabled={false}
        isThreadSwitchDisabled={false}
        collapsed={false}
        mobileOpen={false}
        width={300}
        minWidth={240}
        maxWidth={480}
        onWidthChange={onWidthChange}
        onResetWidth={onResetWidth}
        onToggleCollapsed={vi.fn()}
        onCloseMobile={vi.fn()}
        onCreateNewThread={vi.fn()}
        onSelectThread={vi.fn()}
        onBeforeCreateProjectThread={() => Promise.resolve(true)}
        onSelectCreatedProjectThread={vi.fn()}
        discardedProjectThreadId={null}
        projectDraftError={null}
        activeThreadIds={[]}
        onRetryThreadList={vi.fn()}
        onRenameThread={() => Promise.resolve()}
        onDeleteThread={() => Promise.resolve()}
      />,
    );
    const separator = screen.getByRole("separator", {
      name: "调整侧边栏宽度",
    });
    fireEvent.keyDown(separator, { key: "ArrowRight" });
    expect(onWidthChange).toHaveBeenCalledWith(308);
    fireEvent.doubleClick(separator);
    expect(onResetWidth).toHaveBeenCalledOnce();
  });

  it("桌面会话栏可收起为窄轨并恢复", () => {
    const { container } = render(<NavigationHarness />);

    fireEvent.click(screen.getByRole("button", { name: "收起会话栏" }));
    expect(container.querySelector(".conversation-rail")).toHaveAttribute(
      "data-collapsed",
      "true",
    );
    expect(screen.queryByText("Mini Deer")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "展开会话栏" }));
    expect(container.querySelector(".conversation-rail")).toHaveAttribute(
      "data-collapsed",
      "false",
    );
    expect(screen.getByText("Mini Deer")).toBeInTheDocument();
    expect(screen.queryByText("项目内会话")).not.toBeInTheDocument();
  });

  it("移动端入口打开抽屉，选择会话后自动关闭", () => {
    const onSelect = vi.fn();
    const { container } = render(<NavigationHarness onSelect={onSelect} />);

    fireEvent.click(screen.getByRole("button", { name: "打开会话导航" }));
    expect(container.querySelector(".conversation-rail")).toHaveAttribute(
      "data-mobile-open",
      "true",
    );
    expect(
      screen.getAllByRole("button", { name: "关闭会话导航" }),
    ).toHaveLength(2);

    fireEvent.click(
      screen.getByRole("button", { name: "切换到会话 另一段会话" }),
    );
    expect(onSelect).toHaveBeenCalledOnce();
    expect(container.querySelector(".conversation-rail")).toHaveAttribute(
      "data-mobile-open",
      "false",
    );
  });

  it("切走后仍在侧栏标记后台运行的 Thread", () => {
    render(<NavigationHarness activeThreadIds={["thread-other"]} />);

    expect(screen.getByText("正在后台运行")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "切换到会话 另一段会话" }),
    ).toBeEnabled();
  });

  it("统一搜索普通与项目会话并记住筛选排序", async () => {
    const projectId = "11223344-1234-4234-9234-123456789012";
    const projectThreadId = "99887766-1234-4234-9234-123456789012";
    vi.stubGlobal(
      "fetch",
      vi.fn((url: RequestInfo | URL) => {
        const target =
          typeof url === "string"
            ? url
            : url instanceof URL
              ? url.href
              : url.url;
        if (target.startsWith("/api/v1/threads?")) {
          return Promise.resolve(
            Response.json([
              {
                thread_id: projectThreadId,
                title: "跨项目搜索结果",
                status: "idle",
                project_id: projectId,
                created_at: "2026-09-03T01:00:00Z",
                updated_at: "2026-09-03T01:00:00Z",
              },
            ]),
          );
        }
        return Promise.resolve(
          Response.json({
            items: [
              {
                project_id: projectId,
                name: "Mini Deer 项目",
                root_path: "D:/projects/mini-deer",
                access_mode: "read_write",
                status: "available",
                status_reason: null,
                created_at: "2026-09-03T00:00:00Z",
                updated_at: "2026-09-03T00:00:00Z",
              },
            ],
            next_offset: null,
          }),
        );
      }),
    );
    render(<NavigationHarness />);

    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "Mini Deer" },
    });
    const result = await screen.findByRole("button", {
      name: "切换到会话 跨项目搜索结果",
    });
    expect(result).toBeVisible();
    expect(result).toHaveTextContent("Mini Deer 项目");
    fireEvent.click(
      screen.getByRole("button", {
        name: "会话操作 跨项目搜索结果",
      }),
    );
    expect(
      screen.getByRole("button", { name: "重命名会话 跨项目搜索结果" }),
    ).toBeVisible();

    fireEvent.change(screen.getByRole("combobox", { name: "会话范围" }), {
      target: { value: "standalone" },
    });
    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "切换到会话 跨项目搜索结果",
        }),
      ).not.toBeInTheDocument(),
    );
    fireEvent.change(screen.getByRole("combobox", { name: "会话排序" }), {
      target: { value: "title" },
    });
    expect(
      localStorage.getItem("mini-deer-agent.navigation.filters.v1"),
    ).toContain('"sort":"title"');
  });
});
