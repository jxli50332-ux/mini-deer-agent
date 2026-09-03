import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/features/chat/ui/Composer";

describe("输入框上方 Todo 面板", () => {
  it("默认收起，展示进度并可展开完整任务清单", () => {
    const { container } = render(
      <Composer
        isActive={false}
        todoList={{
          items: [
            { content: "分析需求", status: "completed" },
            { content: "实现界面", status: "in_progress" },
            { content: "验证结果", status: "pending" },
          ],
        }}
        onSubmit={vi.fn(() => Promise.resolve(true))}
        onCancel={vi.fn(() => Promise.resolve(true))}
      />,
    );

    const footer = container.querySelector(".composer-region");
    expect(footer?.firstElementChild).toHaveClass("todo-panel");
    expect(footer?.lastElementChild).toHaveClass("composer");
    expect(screen.getByText("1/3")).toBeInTheDocument();
    expect(screen.queryByText("实现界面")).not.toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /Todos/ }));
    expect(screen.getByText("分析需求")).toBeVisible();
    expect(screen.getByText("实现界面")).toBeVisible();
    expect(screen.getByText("验证结果")).toBeVisible();
  });

  it("空清单不占用输入区空间", () => {
    const { container } = render(
      <Composer
        isActive={false}
        todoList={{ items: [] }}
        onSubmit={vi.fn(() => Promise.resolve(true))}
        onCancel={vi.fn(() => Promise.resolve(true))}
      />,
    );

    expect(container.querySelector(".todo-panel")).toBeNull();
  });

  it("Todo 状态改变时只标记发生变化的条目", async () => {
    const onSubmit = vi.fn(() => Promise.resolve(true));
    const onCancel = vi.fn(() => Promise.resolve(true));
    const { rerender } = render(
      <Composer
        isActive={false}
        todoList={{
          items: [
            { content: "分析需求", status: "in_progress" },
            { content: "验证结果", status: "pending" },
          ],
        }}
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    );

    rerender(
      <Composer
        isActive={false}
        todoList={{
          items: [
            { content: "分析需求", status: "completed" },
            { content: "验证结果", status: "pending" },
          ],
        }}
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("分析需求").closest("li")).toHaveAttribute(
        "data-updated",
        "true",
      ),
    );
    expect(screen.getByText("验证结果").closest("li")).toHaveAttribute(
      "data-updated",
      "false",
    );
  });
});
