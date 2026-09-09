import { describe, expect, it } from "vitest";

import { projectCotSteps } from "@/features/chat/model/project-cot";
import {
  chatRunReducer,
  createInitialChatRunState,
} from "@/features/chat/model/reducer";
import { parseThreadHistoryPage } from "@/features/threads/api/thread-history";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const THREAD_ID = "22222222-2222-4222-8222-222222222222";
const USER_ID = "user-subagent-observability";

const input = JSON.stringify({
  description: "定位预算实现",
  prompt: "查找 child_scope",
  subagent_type: "project-reader",
});
const result = JSON.stringify({
  version: 1,
  kind: "subagent_result",
  status: "completed",
  subagent_type: "project-reader",
  description: "定位预算实现",
  result: "child_scope 位于 run_budget.py。",
  duration_ms: 860,
  usage: { total_tokens: 420, model_calls: 2 },
});

function liveTaskStep() {
  let state = chatRunReducer(createInitialChatRunState(), {
    type: "run/requested",
    threadId: THREAD_ID,
    userMessage: { id: USER_ID, content: "定位 child_scope" },
  });
  state = chatRunReducer(state, {
    type: "run/event-received",
    event: {
      event: "run_started",
      eventId: `${RUN_ID}:1`,
      version: "1",
      runId: RUN_ID,
      threadId: THREAD_ID,
      sequence: 1,
      messageId: null,
      payload: { createdAt: "2026-09-08T01:00:00Z" },
    },
  });
  state = chatRunReducer(state, {
    type: "run/event-received",
    event: {
      event: "tool_call_delta",
      eventId: `${RUN_ID}:2`,
      version: "1",
      runId: RUN_ID,
      threadId: THREAD_ID,
      sequence: 2,
      messageId: "assistant-task",
      payload: {
        toolCallId: "call-reader",
        name: "task",
        argumentsDelta: input,
        index: 0,
      },
    },
  });
  state = chatRunReducer(state, {
    type: "run/event-received",
    event: {
      event: "tool_result",
      eventId: `${RUN_ID}:3`,
      version: "1",
      runId: RUN_ID,
      threadId: THREAD_ID,
      sequence: 3,
      messageId: "task-result",
      payload: {
        toolCallId: "call-reader",
        name: "task",
        content: result,
      },
    },
  });
  return projectCotSteps(state.timeline, null).find(
    (step) => step.toolName === "task",
  );
}

describe("子 Agent 可观察性恢复", () => {
  it("实时 RunEvent 和刷新后的产品历史生成相同生命周期卡片", () => {
    const history = parseThreadHistoryPage(
      {
        version: "1",
        thread_id: THREAD_ID,
        thread_exists: true,
        items: [
          {
            kind: "message",
            id: USER_ID,
            run_id: RUN_ID,
            thread_sequence: 1,
            role: "user",
            content: "定位 child_scope",
            created_at: "2026-09-08T01:00:00Z",
          },
          {
            kind: "tool",
            id: "tool-history-reader",
            run_id: RUN_ID,
            thread_sequence: 2,
            tool_call_id: "call-reader",
            name: "task",
            input,
            result,
            status: "completed",
            created_at: "2026-09-08T01:00:01Z",
          },
        ],
        has_more: false,
        next_before_sequence: null,
      },
      THREAD_ID,
    );
    const restored = projectCotSteps(history.items, null).find(
      (step) => step.toolName === "task",
    );

    expect(restored?.subagent).toEqual(liveTaskStep()?.subagent);
    expect(restored?.subagent).toMatchObject({
      name: "project-reader",
      status: "completed",
      durationMs: 860,
      totalTokens: 420,
      modelCalls: 2,
      resultSummary: "child_scope 位于 run_budget.py。",
    });
  });
});
