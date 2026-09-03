import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ChatTimelineItem } from "@/entities/message/model/types";
import { MessageList } from "@/features/chat/ui/MessageList";

const ITEMS: readonly ChatTimelineItem[] = [
  {
    kind: "message",
    id: "user-1",
    role: "user",
    content: "帮我生成报告",
  },
  {
    kind: "tool",
    id: "tool-clarification",
    toolCallId: "call-1",
    name: "ask_clarification",
    input: "{}",
    result: JSON.stringify({
      version: 1,
      kind: "human_input_request",
      source: "ask_clarification",
      request_id: "clarification:call-1",
      clarification_type: "approach_choice",
      question: "请选择输出格式",
      input_mode: "choice_with_other",
      options: [
        { id: "option-1", label: "Markdown", value: "Markdown" },
        { id: "option-2", label: "纯文本", value: "纯文本" },
      ],
    }),
    status: "completed",
  },
];

describe("MessageList Human Input 集成", () => {
  it("把 ask_clarification 工具替换为专用卡片并上传精确响应", async () => {
    const onSubmitHumanInput = vi.fn(() => Promise.resolve(true));
    render(
      <MessageList
        items={ITEMS}
        phase="completed"
        onSubmitHumanInput={onSubmitHumanInput}
      />,
    );

    expect(
      screen.getByRole("group", { name: "需要你确认" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /工具 ask_clarification/ }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));

    await waitFor(() =>
      expect(onSubmitHumanInput).toHaveBeenCalledWith(
        expect.objectContaining({
          requestId: "clarification:call-1",
          question: "请选择输出格式",
        }),
        expect.objectContaining({
          request_id: "clarification:call-1",
          response_kind: "option",
          option_id: "option-1",
          value: "Markdown",
        }),
      ),
    );
  });
});
