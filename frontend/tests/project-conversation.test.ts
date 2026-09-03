import { describe, expect, it } from "vitest";

import type { ChatTimelineItem } from "@/entities/message/model/types";
import { projectConversation } from "@/features/chat/model/project-conversation";

const TIMELINE: readonly ChatTimelineItem[] = [
  {
    kind: "message",
    id: "user-1",
    role: "user",
    content: "第一问",
  },
  {
    kind: "message",
    id: "assistant-1",
    role: "assistant",
    content: "先查询",
  },
  {
    kind: "tool",
    id: "tool-1",
    toolCallId: "call-1",
    name: "get_weather",
    input: "{}",
    result: "晴",
    status: "completed",
  },
  {
    kind: "message",
    id: "assistant-2",
    role: "assistant",
    content: "查询完成",
  },
  {
    kind: "message",
    id: "user-2",
    role: "user",
    content: "第二问",
  },
  {
    kind: "message",
    id: "assistant-3",
    role: "assistant",
    content: "第二答",
  },
];

describe("对话展示投影", () => {
  it("按用户边界分组，并保持 Assistant 与工具的原始顺序", () => {
    const turns = projectConversation(TIMELINE, "completed");

    expect(turns).toHaveLength(2);
    expect(turns[0]).toMatchObject({
      id: "turn:user-1",
      user: { id: "user-1" },
      status: "final",
    });
    expect(turns[0]?.steps.map((item) => item.id)).toEqual([
      "assistant-1",
      "tool-1",
      "assistant-2",
    ]);
    expect(turns[1]).toMatchObject({
      id: "turn:user-2",
      user: { id: "user-2" },
      status: "final",
    });
    expect(turns[1]?.steps.map((item) => item.id)).toEqual(["assistant-3"]);
  });

  it("只把活动中的最后一轮标记为 streaming", () => {
    const turns = projectConversation(TIMELINE, "streaming");

    expect(turns.map((turn) => turn.status)).toEqual(["final", "streaming"]);
  });

  it.each([
    ["failed", "failed"],
    ["cancelled", "cancelled"],
    ["idle", "final"],
  ] as const)("把 %s 页面阶段投影为最后一轮 %s", (phase, status) => {
    const turns = projectConversation(TIMELINE, phase);

    expect(turns.at(-1)?.status).toBe(status);
    expect(turns[0]?.status).toBe("final");
  });

  it("兼容历史分页从 Assistant 项目开始，并生成稳定轮次 ID", () => {
    const orphanTimeline = TIMELINE.slice(1, 4);

    expect(projectConversation(orphanTimeline, "completed")).toEqual([
      {
        id: "turn:assistant-1",
        user: null,
        steps: orphanTimeline,
        status: "final",
      },
    ]);
  });

  it("空时间线不会制造占位轮次", () => {
    expect(projectConversation([], "streaming")).toEqual([]);
  });

  it("隐藏的结构化回答不产生重复用户气泡，但后续回答仍接在当前轮次", () => {
    const hiddenAnswer: ChatTimelineItem = {
      kind: "message",
      id: "hidden-answer",
      role: "user",
      content: "针对澄清问题，我选择 Markdown",
      hiddenFromUi: true,
      humanInputResponse: {
        version: 1,
        kind: "human_input_response",
        request_id: "clarification:call-1",
        response_kind: "text",
        value: "Markdown",
      },
    };
    const continuation: ChatTimelineItem = {
      kind: "message",
      id: "assistant-after-answer",
      role: "assistant",
      content: "收到，我将使用 Markdown。",
    };

    const turns = projectConversation(
      [...TIMELINE.slice(0, 4), hiddenAnswer, continuation],
      "completed",
    );

    expect(turns).toHaveLength(1);
    expect(turns[0]?.steps.map((item) => item.id)).toContain(
      "assistant-after-answer",
    );
    expect(turns[0]?.steps.map((item) => item.id)).not.toContain(
      "hidden-answer",
    );
  });

  it("只把服务端开始时间投影到最后一个活动轮次", () => {
    const startedAt = "2026-08-29T08:00:00+00:00";
    const turns = projectConversation(TIMELINE, "streaming", startedAt);

    expect(turns[0]).not.toHaveProperty("timing");
    expect(turns.at(-1)?.timing).toEqual({
      kind: "active",
      startedAt,
    });
    expect(
      projectConversation(TIMELINE, "completed", startedAt).at(-1),
    ).not.toHaveProperty("timing");
  });

  it.each([
    ["completed", "completed"],
    ["failed", "failed"],
    ["cancelled", "cancelled"],
    ["interrupted", "cancelled"],
  ] as const)("把持久化 %s Run 的耗时归属为 %s", (status, outcome) => {
    const turns = projectConversation(TIMELINE, "completed", null, [
      {
        runId: "run-2",
        userMessageId: "user-2",
        status,
        startedAt: "2026-08-29T08:00:00.200Z",
        finishedAt: "2026-08-29T08:01:05.900Z",
      },
    ]);

    expect(turns[0]).not.toHaveProperty("timing");
    expect(turns[1]?.timing).toEqual({
      kind: "settled",
      outcome,
      durationSeconds: 65,
    });
  });

  it("不为运行中或缺少服务端时间的历史 Run 猜测耗时", () => {
    const runs = [
      {
        runId: "run-1",
        userMessageId: "user-1",
        status: "running" as const,
        startedAt: "2026-08-29T08:00:00Z",
        finishedAt: null,
      },
      {
        runId: "run-2",
        userMessageId: "user-2",
        status: "completed" as const,
        startedAt: null,
        finishedAt: "2026-08-29T08:00:03Z",
      },
    ];

    expect(
      projectConversation(TIMELINE, "completed", null, runs).every(
        (turn) => turn.timing === undefined,
      ),
    ).toBe(true);
  });
});
