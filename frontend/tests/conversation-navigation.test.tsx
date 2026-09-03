import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConversationRail } from "@/features/chat/ui/ConversationRail";
import { ThreadHeader } from "@/features/chat/ui/ThreadHeader";

function NavigationHarness({ onSelect = vi.fn() }: { onSelect?: () => void }) {
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
});
