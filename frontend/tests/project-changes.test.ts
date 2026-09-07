import { describe, expect, it } from "vitest";

import type { ToolTimelineItem } from "@/entities/message/model/types";
import {
  projectChanges,
  projectChecks,
  projectToolResultChangesTree,
} from "@/features/chat/model/project-changes";

function tool(
  id: string,
  name: string,
  result: Record<string, unknown>,
  input: Record<string, unknown> = {},
): ToolTimelineItem {
  return {
    kind: "tool",
    id,
    toolCallId: `call-${id}`,
    name,
    input: JSON.stringify(input),
    result: JSON.stringify(result),
    status: "completed",
  };
}

describe("本轮文件改动投影", () => {
  it("按工具完成顺序汇总真实发生的文件变化", () => {
    expect(
      projectChanges([
        tool(
          "create",
          "create_file",
          {
            ok: true,
            created: true,
            path: "src/new.py",
          },
          { content: "answer = 1\r\n" },
        ),
        tool(
          "replace",
          "str_replace",
          {
            ok: true,
            replaced: true,
            path: "src/main.py",
          },
          { old_str: "answer = 1", new_str: "answer = 2" },
        ),
        tool(
          "write",
          "write_file",
          {
            ok: true,
            written: true,
            changed: true,
            path: "README.md",
            previous_content_preview: "old title\r\nold body",
            previous_content_truncated: false,
          },
          { content: "new title\nnew body" },
        ),
        tool("move", "move_file", {
          ok: true,
          moved: true,
          previous_path: "src/old.py",
          path: "archive/old.py",
        }),
        tool("delete", "delete_file", {
          ok: true,
          deleted: true,
          path: "tmp.txt",
          deleted_content_preview: "temporary\r\ncontent",
          deleted_content_truncated: false,
        }),
      ]),
    ).toEqual([
      {
        id: "create",
        kind: "created",
        path: "src/new.py",
        diff: {
          after: "answer = 1\n",
          truncated: false,
        },
      },
      {
        id: "replace",
        kind: "modified",
        path: "src/main.py",
        diff: {
          before: "answer = 1",
          after: "answer = 2",
          truncated: false,
        },
      },
      {
        id: "write",
        kind: "modified",
        path: "README.md",
        diff: {
          before: "old title\nold body",
          after: "new title\nnew body",
          truncated: false,
        },
      },
      {
        id: "move",
        kind: "moved",
        previousPath: "src/old.py",
        path: "archive/old.py",
      },
      {
        id: "delete",
        kind: "deleted",
        path: "tmp.txt",
        diff: {
          before: "temporary\ncontent",
          truncated: false,
        },
      },
    ]);
  });

  it("忽略失败、无变化、未完成和不可解析的工具结果", () => {
    const pending = tool("pending", "create_file", {
      ok: true,
      created: true,
      path: "pending.txt",
    });
    expect(
      projectChanges([
        tool("failed", "create_file", {
          ok: false,
          created: false,
          path: "failed.txt",
        }),
        tool("unchanged", "write_file", {
          ok: true,
          written: true,
          changed: false,
          path: "same.txt",
        }),
        { ...pending, status: "pending" },
        { ...pending, id: "invalid", result: "not-json" },
      ]),
    ).toEqual([]);
  });

  it("限制精确替换差异的展示长度", () => {
    const [change] = projectChanges([
      tool(
        "large",
        "str_replace",
        { ok: true, replaced: true, path: "large.txt" },
        { old_str: "a".repeat(5000), new_str: "b".repeat(5000) },
      ),
    ]);
    expect(change?.diff?.before).toHaveLength(4000);
    expect(change?.diff?.after).toHaveLength(4000);
    expect(change?.diff?.truncated).toBe(true);
  });

  it("限制新建文件正文差异的展示长度", () => {
    const [change] = projectChanges([
      tool(
        "create-large",
        "create_file",
        { ok: true, created: true, path: "large.txt" },
        { content: "新".repeat(5000) },
      ),
    ]);
    expect(change?.diff?.before).toBeUndefined();
    expect(change?.diff?.after).toHaveLength(4000);
    expect(change?.diff?.truncated).toBe(true);
  });

  it("完整写入差异继承服务端旧正文截断标记", () => {
    const [change] = projectChanges([
      tool(
        "write-large",
        "write_file",
        {
          ok: true,
          written: true,
          changed: true,
          path: "large.txt",
          previous_content_preview: "a".repeat(4000),
          previous_content_truncated: true,
        },
        { content: "b".repeat(5000) },
      ),
    ]);
    expect(change?.diff?.before).toHaveLength(4000);
    expect(change?.diff?.after).toHaveLength(4000);
    expect(change?.diff?.truncated).toBe(true);
  });

  it("删除差异继承服务端正文截断标记", () => {
    const [change] = projectChanges([
      tool("delete-large", "delete_file", {
        ok: true,
        deleted: true,
        path: "large.txt",
        deleted_content_preview: "旧".repeat(4000),
        deleted_content_truncated: true,
      }),
    ]);
    expect(change?.diff?.before).toHaveLength(4000);
    expect(change?.diff?.after).toBeUndefined();
    expect(change?.diff?.truncated).toBe(true);
  });

  it("只让成功的目录结构变化触发项目文件树刷新", () => {
    expect(
      projectToolResultChangesTree(
        "create_file",
        JSON.stringify({ ok: true, created: true, path: "new.txt" }),
      ),
    ).toBe(true);
    expect(
      projectToolResultChangesTree(
        "str_replace",
        JSON.stringify({ ok: true, replaced: true, path: "same.txt" }),
      ),
    ).toBe(false);
    expect(
      projectToolResultChangesTree(
        "delete_file",
        JSON.stringify({ ok: false, deleted: false, path: "keep.txt" }),
      ),
    ).toBe(false);
  });
});

describe("本轮检查结果投影", () => {
  it("按执行顺序保留失败、通过、超时和取消事实", () => {
    const pending = tool(
      "cancelled",
      "run_project_command",
      {},
      { command: "sleep 30" },
    );
    expect(
      projectChecks([
        tool(
          "failed-check",
          "run_project_command",
          { ok: true, command_completed: true, exit_code: 1 },
          { command: "python -m unittest" },
        ),
        tool(
          "passed-check",
          "run_project_command",
          { ok: true, command_completed: true, exit_code: 0 },
          { command: "python -m unittest" },
        ),
        tool(
          "timeout-check",
          "run_project_command",
          { ok: true, command_completed: false, timed_out: true },
          { command: "sleep 5" },
        ),
        { ...pending, status: "cancelled", result: null },
        tool("unrelated", "read_file", { ok: true }, { path: "main.py" }),
      ]),
    ).toEqual([
      {
        id: "failed-check",
        command: "python -m unittest",
        status: "failed",
        exitCode: 1,
      },
      {
        id: "passed-check",
        command: "python -m unittest",
        status: "passed",
        exitCode: 0,
      },
      { id: "timeout-check", command: "sleep 5", status: "timed_out" },
      { id: "cancelled", command: "sleep 30", status: "cancelled" },
    ]);
  });
});
