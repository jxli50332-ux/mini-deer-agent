import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ToolTimelineItem } from "@/entities/message/model/types";
import { ToolActivity } from "@/features/chat/ui/ToolActivity";

function toolItem(overrides: Partial<ToolTimelineItem> = {}): ToolTimelineItem {
  return {
    kind: "tool",
    id: "tool-1",
    toolCallId: "call-1",
    name: "get_weather",
    input: '{"city":"北京"}',
    result: "北京 24°C",
    status: "completed",
    ...overrides,
  };
}

describe("工具活动卡", () => {
  it("完成后默认收起，并允许用户展开格式化后的参数和结果", () => {
    const { container } = render(<ToolActivity item={toolItem()} />);
    const disclosure = container.querySelector("details");
    const summary = container.querySelector("summary");

    expect(disclosure).not.toHaveAttribute("open");
    expect(summary).not.toBeNull();

    fireEvent.click(summary!);

    expect(disclosure).toHaveAttribute("open");
    expect(
      container.querySelectorAll(".tool-activity__content")[0]?.textContent,
    ).toBe('{\n  "city": "北京"\n}');
    expect(screen.getByText("北京 24°C")).toBeInTheDocument();
  });

  it.each([
    ["pending", "调用中"],
    ["failed", "失败"],
    ["cancelled", "已取消"],
  ] as const)("%s 状态默认展开并显示 %s", (status, statusLabel) => {
    const { container } = render(
      <ToolActivity
        item={toolItem({
          status,
          result: null,
          input: status === "pending" ? "" : "not-json",
        })}
      />,
    );

    expect(container.querySelector("details")).toHaveAttribute("open");
    expect(screen.getByText(statusLabel)).toBeInTheDocument();
    expect(screen.getByText("等待工具返回结果……")).toBeInTheDocument();
  });

  it("明确展示空工具结果，而不是继续显示等待状态", () => {
    render(<ToolActivity item={toolItem({ result: "" })} />);

    expect(screen.getByText("工具返回了空内容")).toBeInTheDocument();
    expect(screen.queryByText("等待工具返回结果……")).not.toBeInTheDocument();
  });

  it("把 web_search 结果展示为可点击标题、域名和摘要", () => {
    const { container } = render(
      <ToolActivity
        item={toolItem({
          name: "web_search",
          input: '{"query":"Mini Deer"}',
          result: JSON.stringify({
            query: "Mini Deer",
            total_results: 2,
            results: [
              {
                title: "第一条结果",
                url: "https://example.com/first",
                content: "第一条搜索摘要。",
              },
              {
                title: "第二条结果",
                url: "https://docs.example.org/second",
                content: "第二条搜索摘要。",
              },
            ],
          }),
        })}
      />,
    );

    fireEvent.click(container.querySelector("summary")!);
    expect(
      screen.getByText("搜索“Mini Deer”得到 2 个来源"),
    ).toBeInTheDocument();
    expect(screen.getByText("第一条搜索摘要。")).toBeInTheDocument();
    expect(screen.getByText("example.com")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "第一条结果" })).toHaveAttribute(
      "href",
      "https://example.com/first",
    );
  });

  it("搜索无结果时显示工具返回的明确错误", () => {
    const { container } = render(
      <ToolActivity
        item={toolItem({
          name: "web_search",
          result: JSON.stringify({
            query: "不存在的查询",
            total_results: 0,
            results: [],
            error: "未找到相关搜索结果。",
          }),
        })}
      />,
    );

    fireEvent.click(container.querySelector("summary")!);
    expect(screen.getByRole("alert")).toHaveTextContent("未找到相关搜索结果。");
  });

  it("把 web_fetch 结果展示为网页标题、域名、正文长度和摘要", () => {
    const { container } = render(
      <ToolActivity
        item={toolItem({
          name: "web_fetch",
          input: '{"url":"https://example.com/article"}',
          result: JSON.stringify({
            requested_url: "https://example.com/article",
            url: "https://example.com/article",
            title: "完整网页标题",
            content: "网页正文的第一段关键信息。",
            characters: 14,
            truncated: false,
          }),
        })}
      />,
    );

    fireEvent.click(container.querySelector("summary")!);
    expect(
      screen.getByText("已读取 example.com · 14 个字符"),
    ).toBeInTheDocument();
    expect(screen.getByText("网页正文的第一段关键信息。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "完整网页标题" })).toHaveAttribute(
      "href",
      "https://example.com/article",
    );
  });

  it("网页读取失败时显示稳定错误而不是展开原始 JSON", () => {
    const { container } = render(
      <ToolActivity
        item={toolItem({
          name: "web_fetch",
          input: '{"url":"http://127.0.0.1/private"}',
          result: JSON.stringify({
            requested_url: "http://127.0.0.1/private",
            url: "http://127.0.0.1/private",
            title: "",
            content: "",
            characters: 0,
            truncated: false,
            error: "该地址被网页读取安全策略拒绝。",
          }),
        })}
      />,
    );

    fireEvent.click(container.querySelector("summary")!);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "该地址被网页读取安全策略拒绝。",
    );
  });

  it("write_todos 结果显示为任务清单", () => {
    const { container } = render(
      <ToolActivity
        item={toolItem({
          name: "write_todos",
          input: '{"todos":[{"content":"分析","status":"completed"}]}',
          result: JSON.stringify({
            todos: [
              { content: "分析需求", status: "completed" },
              { content: "实现功能", status: "in_progress" },
              { content: "验证结果", status: "pending" },
            ],
          }),
        })}
      />,
    );

    fireEvent.click(container.querySelector("summary")!);
    expect(screen.getByText("分析需求")).toBeInTheDocument();
    expect(screen.getByText("实现功能")).toBeInTheDocument();
    expect(screen.getByText("进行中")).toBeInTheDocument();
  });

  it("ask_clarification 完成后仍展开通用工具卡并显示问题", () => {
    const { container } = render(
      <ToolActivity
        item={toolItem({
          name: "ask_clarification",
          input:
            '{"question":"报告的主题和用途是什么？","clarification_type":"missing_info"}',
          result: JSON.stringify({
            version: 1,
            kind: "human_input_request",
            source: "ask_clarification",
            request_id: "clarification:call-1",
            clarification_type: "missing_info",
            question: "报告的主题和用途是什么？",
            input_mode: "free_text",
          }),
        })}
      />,
    );

    expect(container.querySelector("details")).toHaveAttribute("open");
    const questionCopies = screen.getAllByText(/报告的主题和用途是什么/);
    expect(questionCopies).toHaveLength(2);
    expect(questionCopies[1]).toBeVisible();
  });
});
