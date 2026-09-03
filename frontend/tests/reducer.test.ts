import { describe, expect, it } from "vitest";

import type { ChatRunEvent } from "@/features/chat/model/events";
import {
  chatRunReducer,
  createInitialChatRunState,
  type ChatRunState,
} from "@/features/chat/model/reducer";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_RUN_ID = "33333333-3333-4333-8333-333333333333";
const THREAD_ID = "22222222-2222-4222-8222-222222222222";
const OTHER_THREAD_ID = "44444444-4444-4444-8444-444444444444";

function requestRun(state = createInitialChatRunState()): ChatRunState {
  return chatRunReducer(state, {
    type: "run/requested",
    threadId: THREAD_ID,
    userMessage: {
      id: "user-1",
      content: "查询北京天气",
      attachments: [
        {
          filename: "weather.csv",
          mediaType: "text/csv",
          sizeBytes: 28,
          content: "city,temp",
        },
      ],
    },
  });
}

function baseEvent(sequence: number) {
  return {
    eventId: `${RUN_ID}:${sequence}`,
    version: "1" as const,
    runId: RUN_ID,
    threadId: THREAD_ID,
    sequence,
  };
}

function started(sequence = 1): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "run_started",
    messageId: null,
    payload: { createdAt: "2026-08-25T15:00:00+00:00" },
  };
}

function aiDelta(
  sequence: number,
  text: string,
  messageId: string | null = "assistant-1",
): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "ai_delta",
    messageId,
    payload: { text },
  };
}

function reasoningDelta(
  sequence: number,
  text: string,
  messageId: string | null = "assistant-1",
): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "reasoning_delta",
    messageId,
    payload: { text },
  };
}

function toolCall(
  sequence: number,
  argumentsDelta: string,
  name: string | null = "get_weather",
): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "tool_call_delta",
    messageId: "assistant-tool-1",
    payload: {
      toolCallId: "call-weather-1",
      name,
      argumentsDelta,
      index: 0,
    },
  };
}

function toolResult(sequence: number): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "tool_result",
    messageId: "tool-message-1",
    payload: {
      toolCallId: "call-weather-1",
      name: "get_weather",
      content: "北京 24°C",
    },
  };
}

function interrupted(sequence: number): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "run_interrupted",
    messageId: null,
    payload: { reason: "user_cancelled" },
  };
}

function completed(sequence: number): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "run_completed",
    messageId: null,
    payload: { finishReason: "stop" },
  };
}

function receive(state: ChatRunState, event: ChatRunEvent): ChatRunState {
  return chatRunReducer(state, { type: "run/event-received", event });
}

describe("Chat run reducer", () => {
  it("提交时立即加入用户消息，并在 run_started 后进入 streaming", () => {
    const connecting = requestRun();
    const streaming = receive(connecting, started());

    expect(connecting).toMatchObject({
      phase: "connecting",
      threadId: THREAD_ID,
      runId: null,
      lastSequence: 0,
    });
    expect(connecting.timeline).toEqual([
      {
        kind: "message",
        id: "user-1",
        role: "user",
        content: "查询北京天气",
        attachments: [
          {
            filename: "weather.csv",
            mediaType: "text/csv",
            sizeBytes: 28,
            content: "city,temp",
          },
        ],
      },
    ]);
    expect(streaming).toMatchObject({
      phase: "streaming",
      runId: RUN_ID,
      lastSequence: 1,
      startedAt: "2026-08-25T15:00:00+00:00",
    });
  });

  it("按 messageId 把多个 AI delta 合并到同一条消息", () => {
    let state = receive(requestRun(), started());
    state = receive(state, aiDelta(2, "北"));
    state = receive(state, aiDelta(3, "京天气"));

    expect(state.timeline.at(-1)).toEqual({
      kind: "message",
      id: "assistant-1",
      role: "assistant",
      content: "北京天气",
    });
    expect(state.lastSequence).toBe(3);
  });

  it("把 reasoning delta 与最终回答合并到同一条 assistant 消息", () => {
    let state = receive(requestRun(), started());
    state = receive(state, reasoningDelta(2, "先分析。"));
    state = receive(state, reasoningDelta(3, "再回答。"));
    state = receive(state, aiDelta(4, "结论。"));

    const assistant = state.timeline.find(
      (item) => item.kind === "message" && item.role === "assistant",
    );
    expect(assistant).toMatchObject({
      reasoning: "先分析。再回答。",
      content: "结论。",
    });
  });

  it("messageId 缺失时使用 run 内稳定回退 ID", () => {
    let state = receive(requestRun(), started());
    state = receive(state, aiDelta(2, "北", null));
    state = receive(state, aiDelta(3, "京", null));

    expect(state.timeline.at(-1)).toMatchObject({
      id: `${RUN_ID}:assistant`,
      content: "北京",
    });
  });

  it("按 toolCallId 累积参数，并把工具结果更新到同一张卡片", () => {
    let state = receive(requestRun(), started());
    state = receive(state, toolCall(2, "{", null));
    state = receive(state, toolCall(3, '"city":"北京"}'));
    state = receive(state, toolResult(4));

    expect(state.timeline.at(-1)).toEqual({
      kind: "tool",
      id: `tool:${RUN_ID}:call-weather-1`,
      toolCallId: "call-weather-1",
      name: "get_weather",
      input: '{"city":"北京"}',
      result: "北京 24°C",
      status: "completed",
    });
  });

  it("并发 task 使用各自 toolCallId 独立收敛，不会覆盖兄弟工具卡", () => {
    let state = receive(requestRun(), started());
    state = receive(state, {
      ...baseEvent(2),
      event: "tool_call_delta",
      messageId: "assistant-parallel-task",
      payload: {
        toolCallId: "call-task-1",
        name: "task",
        argumentsDelta: '{"description":"任务一"}',
        index: 0,
      },
    });
    state = receive(state, {
      ...baseEvent(3),
      event: "tool_call_delta",
      messageId: "assistant-parallel-task",
      payload: {
        toolCallId: "call-task-2",
        name: "task",
        argumentsDelta: '{"description":"任务二"}',
        index: 1,
      },
    });
    // 即使第二个任务先返回，也只能结束自己的卡片。
    state = receive(state, {
      ...baseEvent(4),
      event: "tool_result",
      messageId: "tool-task-2",
      payload: {
        toolCallId: "call-task-2",
        name: "task",
        content: '{"status":"completed","result":"结果二"}',
      },
    });
    state = receive(state, {
      ...baseEvent(5),
      event: "tool_result",
      messageId: "tool-task-1",
      payload: {
        toolCallId: "call-task-1",
        name: "task",
        content: '{"status":"completed","result":"结果一"}',
      },
    });
    state = receive(state, completed(6));

    const taskItems = state.timeline.filter((item) => item.kind === "tool");
    expect(taskItems).toMatchObject([
      {
        toolCallId: "call-task-1",
        result: '{"status":"completed","result":"结果一"}',
        status: "completed",
      },
      {
        toolCallId: "call-task-2",
        result: '{"status":"completed","result":"结果二"}',
        status: "completed",
      },
    ]);
    expect(state.phase).toBe("completed");
  });

  it("忽略已经处理的重复 sequence，但拒绝 sequence 缺口", () => {
    let state = receive(requestRun(), started());
    state = receive(state, aiDelta(2, "北京"));

    const duplicate = receive(state, aiDelta(2, "不应重复"));
    expect(duplicate).toBe(state);

    const gap = receive(state, aiDelta(4, "跳过了 3"));
    expect(gap).toMatchObject({
      phase: "failed",
      lastSequence: 4,
      error: { source: "protocol", code: "sequence_gap" },
    });
  });

  it("拒绝错误 thread、错误 run，以及缺失 run_started", () => {
    const connecting = requestRun();
    const wrongThreadEvent = { ...started(), threadId: OTHER_THREAD_ID };
    expect(receive(connecting, wrongThreadEvent)).toMatchObject({
      phase: "failed",
      error: { code: "thread_id_mismatch" },
    });

    const withoutStart = receive(connecting, aiDelta(1, "提前到达"));
    expect(withoutStart).toMatchObject({
      phase: "failed",
      error: { code: "missing_run_started" },
    });

    const streaming = receive(connecting, started());
    const wrongRunEvent = { ...aiDelta(2, "错误 run"), runId: OTHER_RUN_ID };
    expect(receive(streaming, wrongRunEvent)).toMatchObject({
      phase: "failed",
      error: { code: "run_id_mismatch" },
    });
  });

  it("run_error 进入 failed，并把未完成工具标记为失败", () => {
    let state = receive(requestRun(), started());
    state = receive(state, toolCall(2, "{"));
    state = receive(state, {
      ...baseEvent(3),
      event: "run_error",
      messageId: null,
      payload: {
        code: "agent_execution_failed",
        message: "Agent execution failed",
        retryable: true,
      },
    });

    expect(state).toMatchObject({
      phase: "failed",
      error: {
        source: "server",
        code: "agent_execution_failed",
        retryable: true,
      },
    });
    expect(state.timeline.at(-1)).toMatchObject({ status: "failed" });
  });

  it("只有工具已结束时才能完成 run，终止后的新事件会成为协议错误", () => {
    let state = receive(requestRun(), started());
    state = receive(state, toolCall(2, "{}"));
    const prematureCompletion = receive(state, completed(3));
    expect(prematureCompletion).toMatchObject({
      phase: "failed",
      error: { code: "unsettled_tool_call" },
    });

    state = receive(state, toolResult(3));
    state = receive(state, completed(4));
    expect(state).toMatchObject({
      phase: "completed",
      finishReason: "stop",
      error: null,
    });

    const eventAfterCompletion = receive(state, aiDelta(5, "不应出现"));
    expect(eventAfterCompletion).toMatchObject({
      phase: "failed",
      error: { code: "event_after_terminal_state" },
    });
  });

  it("停止请求等待服务端终态，并由 run_interrupted 收束 pending 工具", () => {
    let state = receive(requestRun(), started());
    state = receive(state, toolCall(2, "{"));

    expect(requestRun(state)).toBe(state);

    state = chatRunReducer(state, { type: "run/cancel-requested" });
    expect(state.phase).toBe("stopping");
    const cancelled = receive(state, interrupted(3));
    expect(cancelled).toMatchObject({
      phase: "cancelled",
      finishReason: "user_cancelled",
      error: null,
    });
    expect(cancelled.timeline.at(-1)).toMatchObject({ status: "cancelled" });

    // 响应头尚未返回时只能断开连接，保留本地取消动作作为早期兜底。
    const earlyCancelled = chatRunReducer(state, { type: "run/cancelled" });
    expect(earlyCancelled.phase).toBe("cancelled");

    const failed = chatRunReducer(state, {
      type: "run/client-failed",
      error: {
        code: "network_error",
        message: "无法连接后端",
        retryable: true,
      },
    });
    expect(failed).toMatchObject({
      phase: "failed",
      error: { source: "client", code: "network_error" },
    });
    expect(failed.timeline.at(-1)).toMatchObject({ status: "failed" });
  });

  it("同线程下一轮保留时间线，切换线程时清空旧消息", () => {
    let state = receive(requestRun(), started());
    state = receive(state, aiDelta(2, "第一轮"));
    state = receive(state, completed(3));

    const sameThread = chatRunReducer(state, {
      type: "run/requested",
      threadId: THREAD_ID,
      userMessage: { id: "user-2", content: "继续" },
    });
    expect(sameThread.timeline).toHaveLength(3);

    const otherThread = chatRunReducer(state, {
      type: "run/requested",
      threadId: OTHER_THREAD_ID,
      userMessage: { id: "other-user-1", content: "新线程" },
    });
    expect(otherThread.timeline).toEqual([
      {
        kind: "message",
        id: "other-user-1",
        role: "user",
        content: "新线程",
      },
    ]);
  });

  it("按稳定 ID 合并历史与实时项目，并拒绝旧 Thread 的迟到历史", () => {
    const connecting = requestRun();
    const hydrated = chatRunReducer(connecting, {
      type: "thread/history-loaded",
      threadId: THREAD_ID,
      timeline: [
        {
          kind: "message",
          id: "history-user-1",
          role: "user",
          content: "历史问题",
        },
        {
          kind: "message",
          id: "user-1",
          role: "user",
          content: "服务端重复副本",
        },
      ],
    });

    expect(hydrated.timeline).toEqual([
      {
        kind: "message",
        id: "history-user-1",
        role: "user",
        content: "历史问题",
      },
      {
        kind: "message",
        id: "user-1",
        role: "user",
        content: "查询北京天气",
        attachments: [
          {
            filename: "weather.csv",
            mediaType: "text/csv",
            sizeBytes: 28,
            content: "city,temp",
          },
        ],
      },
    ]);
    expect(
      chatRunReducer(hydrated, {
        type: "thread/history-loaded",
        threadId: OTHER_THREAD_ID,
        timeline: [],
      }),
    ).toBe(hydrated);
  });
});
