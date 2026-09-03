import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ConversationTurnView } from "@/features/chat/model/project-conversation";
import { ConversationTurn } from "@/features/chat/ui/ConversationTurn";

describe("ConversationTurn 附件查看", () => {
  it("历史用户消息展示附件文件名与可查看正文", () => {
    const turn: ConversationTurnView = {
      id: "turn-1",
      user: {
        kind: "message",
        id: "user-1",
        role: "user",
        content: "读取附件",
        attachments: [
          {
            filename: "brief.md",
            mediaType: "text/markdown",
            sizeBytes: 15,
            content: "代号：云杉",
          },
        ],
      },
      steps: [],
      status: "final",
    };

    render(<ConversationTurn turn={turn} />);

    expect(screen.getByText("brief.md")).toBeInTheDocument();
    expect(screen.getByText("代号：云杉")).toBeInTheDocument();
  });

  it("默认只显示最后一步，点击后展示完整 COT，最终回复直接可见", () => {
    const turn: ConversationTurnView = {
      id: "turn-1",
      user: {
        kind: "message",
        id: "user-1",
        role: "user",
        content: "查询北京天气",
      },
      steps: [
        {
          kind: "message",
          id: "assistant-progress-1",
          role: "assistant",
          reasoning: "先确认查询城市和天气指标。",
          content: "正在查询可靠天气数据。",
        },
        {
          kind: "tool",
          id: "tool-1",
          toolCallId: "call-1",
          name: "web_search",
          input: '{"query":"北京天气"}',
          result: "北京 24°C",
          status: "completed",
        },
        {
          kind: "message",
          id: "assistant-1",
          role: "assistant",
          reasoning: "已经拿到结果，准备组织最终回答。",
          content: "北京今天 24 度。",
        },
      ],
      status: "final",
    };

    const { container } = render(<ConversationTurn turn={turn} />);

    const toggle = screen.getByRole("button", { name: "查看其他 3 个步骤" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("北京今天 24 度。")).toBeInTheDocument();
    expect(
      screen.getByText("已经拿到结果，准备组织最终回答。"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("正在查询可靠天气数据。"),
    ).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("先确认查询城市和天气指标。")).toBeInTheDocument();
    expect(screen.getByText("正在查询可靠天气数据。")).toBeInTheDocument();
    expect(screen.getByText("搜索“北京天气”")).toBeInTheDocument();
    expect(container.querySelector(".tool-activity")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "收起步骤" }));
    expect(screen.queryByText("搜索“北京天气”")).not.toBeInTheDocument();
  });

  it("无中间步骤的简单问答不显示折叠块", () => {
    const turn: ConversationTurnView = {
      id: "turn-1",
      user: {
        kind: "message",
        id: "user-1",
        role: "user",
        content: "你好",
      },
      steps: [
        {
          kind: "message",
          id: "assistant-1",
          role: "assistant",
          content: "你好！",
        },
      ],
      status: "final",
    };

    const { container } = render(<ConversationTurn turn={turn} />);

    expect(container.querySelector("details.turn-process")).toBeNull();
    expect(screen.getByText("你好！")).toBeInTheDocument();
  });

  it("单条超长 reasoning 默认独立折叠且不影响同轮其他步骤", () => {
    const longReasoning = Array.from(
      { length: 14 },
      (_, index) => `第 ${index + 1} 行分析：继续核对边界条件与证据。`,
    ).join("\n\n");
    const turn: ConversationTurnView = {
      id: "turn-long-reasoning",
      user: {
        kind: "message",
        id: "user-long-reasoning",
        role: "user",
        content: "做一次深入分析",
      },
      steps: [
        {
          kind: "message",
          id: "assistant-long-reasoning",
          role: "assistant",
          reasoning: longReasoning,
          content: "分析完成。",
        },
      ],
      status: "final",
    };

    const { container } = render(<ConversationTurn turn={turn} />);

    const toggle = screen.getByRole("button", { name: "展开完整思考" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".cot-step__reasoning")).toHaveAttribute(
      "data-expanded",
      "false",
    );
    expect(screen.getByText("分析完成。")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector(".cot-step__reasoning")).toHaveAttribute(
      "data-expanded",
      "true",
    );
    expect(
      screen.getByRole("button", { name: "收起思考" }),
    ).toBeInTheDocument();
  });
});
