import { describe, expect, it } from "vitest";

import {
  parseTodoList,
  selectLatestTodoList,
  selectLatestTodoSnapshot,
} from "@/entities/todo/model/todo-list";

describe("write_todos 工具结果解析", () => {
  it("解析合法任务清单", () => {
    const list = parseTodoList(
      JSON.stringify({
        todos: [
          { content: "分析需求", status: "completed" },
          { content: "实现功能", status: "in_progress" },
        ],
      }),
    );

    expect(list).toEqual({
      items: [
        { content: "分析需求", status: "completed" },
        { content: "实现功能", status: "in_progress" },
      ],
    });
  });

  it("非法 JSON 返回 null", () => {
    expect(parseTodoList("not json")).toBeNull();
  });

  it("缺少 todos 字段返回 null", () => {
    expect(parseTodoList(JSON.stringify({}))).toBeNull();
  });

  it("跳过非法状态和空内容的条目", () => {
    const list = parseTodoList(
      JSON.stringify({
        todos: [
          { content: "合法任务", status: "pending" },
          { content: "非法状态", status: "done" },
          { content: "  ", status: "pending" },
        ],
      }),
    );

    expect(list).toEqual({
      items: [{ content: "合法任务", status: "pending" }],
    });
  });

  it("从完整时间线选择最近一份合法快照", () => {
    const latest = selectLatestTodoList([
      {
        kind: "tool",
        id: "todo-old",
        toolCallId: "call-old",
        name: "write_todos",
        input: "{}",
        result: JSON.stringify({
          todos: [{ content: "旧任务", status: "completed" }],
        }),
        status: "completed",
      },
      {
        kind: "tool",
        id: "other-tool",
        toolCallId: "call-other",
        name: "web_search",
        input: "{}",
        result: "{}",
        status: "completed",
      },
      {
        kind: "tool",
        id: "todo-latest",
        toolCallId: "call-latest",
        name: "write_todos",
        input: "{}",
        result: JSON.stringify({
          todos: [{ content: "最新任务", status: "in_progress" }],
        }),
        status: "completed",
      },
    ]);

    expect(latest).toEqual({
      items: [{ content: "最新任务", status: "in_progress" }],
    });
  });

  it("最新合法快照为空时返回空清单，以便隐藏旧 Todo", () => {
    expect(
      selectLatestTodoList([
        {
          kind: "tool",
          id: "todo-old",
          toolCallId: "call-old",
          name: "write_todos",
          input: "{}",
          result: JSON.stringify({
            todos: [{ content: "旧任务", status: "pending" }],
          }),
          status: "completed",
        },
        {
          kind: "tool",
          id: "todo-empty",
          toolCallId: "call-empty",
          name: "write_todos",
          input: "{}",
          result: JSON.stringify({ todos: [] }),
          status: "completed",
        },
      ]),
    ).toEqual({ items: [] });
  });

  it("快照同时返回来源工具步骤 ID", () => {
    expect(
      selectLatestTodoSnapshot([
        {
          kind: "tool",
          id: "todo-source-step",
          toolCallId: "todo-source-call",
          name: "write_todos",
          input: "{}",
          result: JSON.stringify({
            todos: [{ content: "实现定位", status: "in_progress" }],
          }),
          status: "completed",
        },
      ]),
    ).toEqual({
      sourceToolItemId: "todo-source-step",
      list: { items: [{ content: "实现定位", status: "in_progress" }] },
    });
  });
});
