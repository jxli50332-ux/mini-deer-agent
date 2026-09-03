import { describe, expect, it } from "vitest";

import { projectCotSteps } from "@/features/chat/model/project-cot";

describe("COT 步骤投影", () => {
  it("保持 reasoning、模型中间文本和工具调用的原始顺序", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "message",
          id: "assistant-progress",
          role: "assistant",
          reasoning: "先分析问题。",
          content: "准备搜索资料。",
        },
        {
          kind: "tool",
          id: "search",
          toolCallId: "call-search",
          name: "web_search",
          input: '{"query":"Rust Go 对比"}',
          result: JSON.stringify({
            query: "Rust Go 对比",
            total_results: 1,
            results: [
              {
                title: "语言报告",
                url: "https://example.com/report",
                content: "摘要",
              },
            ],
          }),
          status: "completed",
        },
        {
          kind: "message",
          id: "assistant-final",
          role: "assistant",
          reasoning: "整理搜索结果。",
          content: "这是最终回答。",
        },
      ],
      "assistant-final",
    );

    expect(steps.map((step) => [step.kind, step.text])).toEqual([
      ["reasoning", "先分析问题。"],
      ["message", "准备搜索资料。"],
      ["tool", "搜索“Rust Go 对比”"],
      ["reasoning", "整理搜索结果。"],
    ]);
    expect(steps[2]?.links).toEqual([
      { label: "语言报告", url: "https://example.com/report" },
    ]);
  });

  it("工具参数不合法时仍生成稳定的紧凑摘要", () => {
    expect(
      projectCotSteps(
        [
          {
            kind: "tool",
            id: "pending-tool",
            toolCallId: "call-pending",
            name: null,
            input: '{"partial":',
            result: null,
            status: "pending",
          },
        ],
        null,
      ),
    ).toEqual([
      expect.objectContaining({
        kind: "tool",
        text: "调用 未知工具",
        status: "pending",
      }),
    ]);
  });

  it("write_todos 步骤保留清单内容用于双向定位", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "todo-tool-item",
          toolCallId: "todo-call",
          name: "write_todos",
          input: "{}",
          result: JSON.stringify({
            todos: [
              { content: "分析需求", status: "completed" },
              { content: "实现界面", status: "in_progress" },
            ],
          }),
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        id: "todo-tool-item",
        icon: "todo",
        todoContents: ["分析需求", "实现界面"],
      }),
    );
  });
});
