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

  it("文件 glob 显示模式与虚拟搜索目录", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "glob-tool-item",
          toolCallId: "glob-call",
          name: "glob_files",
          input: '{"pattern":"**/*.py","path":"workspace-1"}',
          result: '{"ok":true,"matches":["workspace-1/main.py"]}',
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "file",
        text: "查找文件：**/*.py",
        detail: "workspace-1",
      }),
    );
  });

  it("正文搜索显示字面量查询与虚拟搜索目录", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "content-search-tool-item",
          toolCallId: "content-search-call",
          name: "search_files",
          input:
            '{"query":"greet","path":"workspace-1/project-test","file_pattern":"**/*.py"}',
          result:
            '{"ok":true,"matches":[{"path":"workspace-1/project-test/src/main.py","line_number":1,"line":"def greet"}]}',
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "file",
        text: "搜索正文：greet",
        detail: "workspace-1/project-test",
      }),
    );
  });

  it("创建文件显示目标路径", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "create-file-tool-item",
          toolCallId: "create-file-call",
          name: "create_file",
          input: '{"path":"agent-created.txt","content":"created by agent\\n"}',
          result:
            '{"ok":true,"path":"agent-created.txt","created":true,"size_bytes":17}',
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "file",
        text: "创建文件",
        detail: "agent-created.txt",
      }),
    );
  });

  it("精确编辑显示目标路径", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "replace-file-tool-item",
          toolCallId: "replace-file-call",
          name: "str_replace",
          input:
            '{"path":"agent-created.txt","old_str":"创建文件能力","new_str":"精确编辑能力"}',
          result:
            '{"ok":true,"path":"agent-created.txt","replaced":true,"occurrences":1}',
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "file",
        text: "更新文件",
        detail: "agent-created.txt",
      }),
    );
  });

  it("完整更新显示目标路径", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "write-file-tool-item",
          toolCallId: "write-file-call",
          name: "write_file",
          input: '{"path":"agent-created.txt","content":"rewritten\\n"}',
          result:
            '{"ok":true,"path":"agent-created.txt","written":true,"created":false}',
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "file",
        text: "更新文件",
        detail: "agent-created.txt",
      }),
    );
  });

  it("执行环境诊断显示 Docker 服务端版本", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "execution-environment-tool-item",
          toolCallId: "execution-environment-call",
          name: "inspect_execution_environment",
          input: "{}",
          result: JSON.stringify({
            ok: true,
            provider: "docker",
            available: true,
            server_version: "29.6.2",
            diagnostic_only: true,
            message: "Docker 隔离执行环境可连接。",
          }),
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "tool",
        text: "检查执行环境",
        detail: "Docker 29.6.2 可用",
      }),
    );
  });

  it("沙箱生命周期诊断显示临时容器已回收", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "sandbox-lifecycle-tool-item",
          toolCallId: "sandbox-lifecycle-call",
          name: "inspect_execution_environment",
          input: '{"verify_lifecycle":true}',
          result: JSON.stringify({
            ok: true,
            provider: "docker",
            available: true,
            lifecycle_ready: true,
            created: true,
            retrieved: true,
            released: true,
            diagnostic_only: true,
            message: "Docker 临时沙箱已创建、执行固定探针并销毁。",
          }),
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "tool",
        text: "验证沙箱生命周期",
        detail: "Docker 临时容器已创建并销毁",
      }),
    );
  });

  it("项目沙箱挂载诊断显示容器路径、根条目数和回收状态", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "project-sandbox-tool-item",
          toolCallId: "project-sandbox-call",
          name: "inspect_project_sandbox",
          input: "{}",
          result: JSON.stringify({
            ok: true,
            provider: "docker",
            mount_ready: true,
            container_path: "/workspace",
            access: "read_only",
            entries: ["README.md", "notes.txt", "src"],
            truncated: false,
            released: true,
          }),
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "tool",
        text: "检查项目沙箱挂载",
        detail: "/workspace · 3 个根条目 · 容器已销毁",
      }),
    );
  });

  it("项目命令显示执行说明、真实退出码和输出摘要", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "project-command-tool-item",
          toolCallId: "project-command-call",
          name: "run_project_command",
          input: JSON.stringify({
            description: "运行 Python 入口",
            command: "python src/main.py",
          }),
          result: JSON.stringify({
            ok: true,
            provider: "docker",
            command_completed: true,
            exit_code: 0,
            stdout: "Hello, Mini Deer!\n",
            stderr: "",
            released: true,
          }),
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "tool",
        text: "运行 Python 入口",
        detail: "python src/main.py · exit 0 · stdout: Hello, Mini Deer!",
      }),
    );
  });

  it("失败的项目命令显示非零退出码和 stderr 摘要", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "failed-project-command-tool-item",
          toolCallId: "failed-project-command-call",
          name: "run_project_command",
          input: JSON.stringify({
            description: "验证失败命令",
            command: "python missing-file.py",
          }),
          result: JSON.stringify({
            ok: true,
            provider: "docker",
            command_completed: true,
            exit_code: 2,
            stdout: "",
            stderr: "python: can't open file '/workspace/missing-file.py'",
            released: true,
          }),
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "tool",
        text: "验证失败命令",
        detail:
          "python missing-file.py · exit 2 · stderr: python: can't open file '/workspace/missing-file.py'",
      }),
    );
  });

  it("超时项目命令显示时限和容器回收结果", () => {
    const steps = projectCotSteps(
      [
        {
          kind: "tool",
          id: "timed-out-project-command-tool-item",
          toolCallId: "timed-out-project-command-call",
          name: "run_project_command",
          input: JSON.stringify({
            description: "验证命令超时",
            command: "sleep 5",
            timeout_seconds: 1,
          }),
          result: JSON.stringify({
            ok: true,
            provider: "docker",
            command_completed: false,
            reason: "project_command_timeout",
            timed_out: true,
            timeout_seconds: 1,
            released: true,
            message: "项目命令运行超过 1 秒，已终止并回收容器。",
          }),
          status: "completed",
        },
      ],
      null,
    );

    expect(steps[0]).toEqual(
      expect.objectContaining({
        icon: "tool",
        text: "验证命令超时",
        detail:
          "sleep 5 · timeout 1s · 项目命令运行超过 1 秒，已终止并回收容器。",
      }),
    );
  });
});

it("创建目录显示目录路径", () => {
  const steps = projectCotSteps(
    [
      {
        kind: "tool",
        id: "mkdir-item",
        toolCallId: "mkdir-call",
        name: "create_directory",
        input: '{"path":"generated"}',
        result: '{"ok":true,"path":"generated","created":true}',
        status: "completed",
      },
    ],
    null,
  );
  expect(steps[0]).toEqual(
    expect.objectContaining({
      text: "创建目录",
      detail: "generated",
      icon: "file",
    }),
  );
});

it("重命名文件显示原文件路径", () => {
  const steps = projectCotSteps(
    [
      {
        kind: "tool",
        id: "rename-item",
        toolCallId: "rename-call",
        name: "rename_file",
        input: '{"path":"hello.txt","new_name":"greeting.txt"}',
        result: '{"ok":true,"path":"greeting.txt","renamed":true}',
        status: "completed",
      },
    ],
    null,
  );
  expect(steps[0]).toEqual(
    expect.objectContaining({
      text: "重命名文件",
      detail: "hello.txt",
      icon: "file",
    }),
  );
});

it("移动文件显示原路径和新路径", () => {
  const steps = projectCotSteps(
    [
      {
        kind: "tool",
        id: "move-item",
        toolCallId: "move-call",
        name: "move_file",
        input:
          '{"path":"agent-generated/greeting.txt","new_path":"archive/greeting.txt"}',
        result:
          '{"ok":true,"previous_path":"agent-generated/greeting.txt","path":"archive/greeting.txt","moved":true}',
        status: "completed",
      },
    ],
    null,
  );
  expect(steps[0]).toEqual(
    expect.objectContaining({
      text: "移动文件",
      detail: "agent-generated/greeting.txt → archive/greeting.txt",
      icon: "file",
    }),
  );
});

it("删除文件显示被删除的路径", () => {
  const steps = projectCotSteps(
    [
      {
        kind: "tool",
        id: "delete-item",
        toolCallId: "delete-call",
        name: "delete_file",
        input: '{"path":"archive/greeting.txt"}',
        result: '{"ok":true,"path":"archive/greeting.txt","deleted":true}',
        status: "completed",
      },
    ],
    null,
  );
  expect(steps[0]).toEqual(
    expect.objectContaining({
      text: "删除文件",
      detail: "archive/greeting.txt",
      icon: "file",
    }),
  );
});
