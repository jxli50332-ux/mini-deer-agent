import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MessageContent } from "@/features/chat/ui/MessageContent";
import { MessageList } from "@/features/chat/ui/MessageList";

describe("对话正文渲染", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("在真实消息列表中把 Assistant Markdown 渲染为富文本，并保留用户纯文本", () => {
    const userContent = "# 用户标题\n<b>不要解释我</b>";

    render(
      <MessageList
        phase="completed"
        items={[
          {
            kind: "message",
            id: "user-1",
            role: "user",
            content: userContent,
          },
          {
            kind: "message",
            id: "assistant-1",
            role: "assistant",
            content:
              "# Assistant 标题\n\n- 第一项\n- 第二项\n\n[官方文档](https://example.com/docs)\n\n| 列 | 值 |\n| --- | --- |\n| A | B |",
          },
        ]}
      />,
    );

    const userMessage = screen.getByRole("article", { name: "你的消息" });
    expect(
      userMessage.querySelector(".message__content--plain")?.textContent,
    ).toBe(userContent);
    expect(within(userMessage).queryByRole("heading")).not.toBeInTheDocument();

    expect(
      screen.getByRole("heading", { name: "Assistant 标题" }),
    ).toBeInTheDocument();
    const assistantMessage = screen.getByRole("article", {
      name: "Mini Deer的消息",
    });
    expect(within(assistantMessage).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "官方文档" })).toHaveAttribute(
      "target",
      "_blank",
    );
    expect(screen.getByRole("link", { name: "官方文档" })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });

  it("显示代码语言并阻止原始 HTML、不安全链接与远程图片进入 DOM", () => {
    const { container } = render(
      <MessageContent
        role="assistant"
        content={
          "```ts\nconst answer = 42;\n```\n\n<script>alert('xss')</script>\n\n[危险链接](javascript:alert('xss'))\n\n![追踪图片](https://example.com/track.png)"
        }
      />,
    );

    expect(screen.getByText("ts")).toBeInTheDocument();
    expect(screen.getByText("const answer = 42;")).toBeInTheDocument();
    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(screen.getByText("[图片：追踪图片]")).toBeInTheDocument();
    const unsafeLink = screen.getByText("危险链接").closest("a");
    expect(unsafeLink).not.toBeNull();
    expect(unsafeLink?.getAttribute("href") ?? "").not.toContain("javascript:");
  });

  it("只为 final Assistant 回答开放整条复制和代码复制", async () => {
    const writeText = vi
      .fn<(text: string) => Promise<void>>()
      .mockResolvedValue();
    vi.stubGlobal("navigator", { clipboard: { writeText } });

    const { rerender } = render(
      <MessageList
        phase="streaming"
        items={[
          {
            kind: "message",
            id: "user-copy",
            role: "user",
            content: "给我代码",
          },
          {
            kind: "message",
            id: "assistant-copy",
            role: "assistant",
            content: "```ts\nconst answer = 42;\n```",
          },
        ]}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "复制回答" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "复制代码" }),
    ).not.toBeInTheDocument();

    rerender(
      <MessageList
        phase="completed"
        items={[
          {
            kind: "message",
            id: "user-copy",
            role: "user",
            content: "给我代码",
          },
          {
            kind: "message",
            id: "assistant-copy",
            role: "assistant",
            content: "```ts\nconst answer = 42;\n```",
          },
        ]}
      />,
    );

    expect(
      screen.getByRole("button", { name: "复制回答" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "复制代码" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("const answer = 42;"),
    );
    writeText.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "复制回答" }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("```ts\nconst answer = 42;\n```"),
    );
  });

  it("工具前说明不冒充最终回答，只给轮次最后一条 Assistant 消息复制入口", () => {
    render(
      <MessageList
        phase="completed"
        items={[
          {
            kind: "message",
            id: "user-final",
            role: "user",
            content: "查询天气",
          },
          {
            kind: "message",
            id: "assistant-processing",
            role: "assistant",
            content: "我先查询。",
          },
          {
            kind: "tool",
            id: "tool-final",
            toolCallId: "call-final",
            name: "get_weather",
            input: "{}",
            result: "晴",
            status: "completed",
          },
          {
            kind: "message",
            id: "assistant-final",
            role: "assistant",
            content: "今天晴朗。",
          },
        ]}
      />,
    );

    const assistantMessages = screen.getAllByRole("article", {
      name: "Mini Deer的消息",
    });
    expect(assistantMessages).toHaveLength(1);
    const cot = screen.getByRole("region", { name: "思考与执行步骤" });
    expect(
      within(cot).queryByRole("button", {
        name: "复制回答",
      }),
    ).not.toBeInTheDocument();
    expect(
      within(assistantMessages[0]!).getByRole("button", {
        name: "复制回答",
      }),
    ).toBeInTheDocument();
  });

  it("把 Assistant citation 渲染为行内来源，并提供去重后的参考来源面板", () => {
    render(
      <MessageContent
        role="assistant"
        content={
          "关键事实来自 [citation:示例研究](https://example.com/research)，" +
          "补充事实仍见 [citation:示例研究](https://example.com/research)。"
        }
      />,
    );

    expect(screen.getAllByRole("link", { name: "示例研究" })).toHaveLength(2);
    expect(screen.getByText("参考来源（1）")).toBeInTheDocument();
    fireEvent.click(screen.getByText("参考来源（1）"));
    const panel = screen.getByRole("list", { name: "参考来源" });
    const sourceLink = within(panel).getByRole("link", { name: /示例研究/ });
    expect(sourceLink).toHaveAttribute("href", "https://example.com/research");
    expect(sourceLink).toHaveAttribute("rel", "noopener noreferrer");
    expect(within(panel).getByText("引用 2 次")).toBeInTheDocument();
  });

  it("不从用户纯文本提取 citation 来源", () => {
    render(
      <MessageContent
        role="user"
        content="[citation:不要解析](https://example.com)"
      />,
    );

    expect(screen.queryByText(/参考来源/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
