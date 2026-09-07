import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

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
      />
    </>
  );
}

describe("响应式会话导航", () => {
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
});
