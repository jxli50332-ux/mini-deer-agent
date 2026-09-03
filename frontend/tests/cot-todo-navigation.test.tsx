import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CotStep } from "@/features/chat/model/project-cot";
import { CotTimeline } from "@/features/chat/ui/CotTimeline";
import { TodoPanel } from "@/features/chat/ui/TodoPanel";

describe("Todo 与 COT 双向定位", () => {
  it("Todo 可展开隐藏 COT，COT 也可展开并定位当前 Todo", () => {
    const sourceStepId = "tool-write-todos-1";
    const steps: readonly CotStep[] = [
      {
        id: sourceStepId,
        kind: "tool",
        icon: "todo",
        text: "更新任务清单",
        toolName: "write_todos",
        status: "completed",
        todoContents: ["分析需求", "实现界面"],
      },
      {
        id: "reasoning-after-todos",
        kind: "reasoning",
        icon: "reasoning",
        text: "按照清单继续实现。",
      },
    ];

    const { container } = render(
      <>
        <CotTimeline steps={steps} />
        <TodoPanel
          sourceStepId={sourceStepId}
          todoList={{
            items: [
              { content: "分析需求", status: "completed" },
              { content: "实现界面", status: "in_progress" },
            ],
          }}
        />
      </>,
    );

    expect(screen.queryByText("更新任务清单")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Todos/ }));
    fireEvent.click(screen.getByText("实现界面").closest("button")!);

    expect(screen.getByText("更新任务清单")).toBeInTheDocument();
    expect(
      container.querySelector(`#cot-step\\:${sourceStepId}`),
    ).toHaveAttribute("data-highlighted", "true");

    fireEvent.click(screen.getByRole("button", { name: /Todos/ }));
    expect(screen.getByRole("button", { name: /Todos/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    fireEvent.click(screen.getByRole("button", { name: /更新任务清单/ }));

    expect(screen.getByRole("button", { name: /Todos/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("实现界面").closest("li")).toHaveAttribute(
      "data-highlighted",
      "true",
    );
  });
});
