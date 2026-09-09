import { describe, expect, it } from "vitest";

import {
  decodeChatRunEvent,
  RunEventDecodeError,
} from "@/features/chat/model/events";
import type { SseFrame } from "@/shared/api/sse-parser";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const THREAD_ID = "22222222-2222-4222-8222-222222222222";

interface FrameOptions {
  readonly messageId?: string | null;
  readonly version?: string;
  readonly eventId?: string;
  readonly runId?: string;
  readonly extraData?: Record<string, unknown>;
}

function runFrame(
  event: string,
  sequence: number,
  payload: Record<string, unknown>,
  options: FrameOptions = {},
): SseFrame {
  const runId = options.runId ?? RUN_ID;
  return {
    event,
    id: options.eventId ?? `${runId}:${sequence}`,
    data: JSON.stringify({
      version: options.version ?? "1",
      run_id: runId,
      thread_id: THREAD_ID,
      sequence,
      message_id: options.messageId ?? null,
      payload,
      ...options.extraData,
    }),
  };
}

describe("v1 ChatRunEvent 校验器", () => {
  it("校验 run_started envelope 并规范化为 camelCase", () => {
    const event = decodeChatRunEvent(
      runFrame("run_started", 1, {
        created_at: "2026-08-25T15:00:00+00:00",
      }),
    );

    expect(event).toEqual({
      event: "run_started",
      eventId: `${RUN_ID}:1`,
      version: "1",
      runId: RUN_ID,
      threadId: THREAD_ID,
      sequence: 1,
      messageId: null,
      payload: { createdAt: "2026-08-25T15:00:00+00:00" },
    });
  });

  it("分别校验模型、工具、失败和完成事件的 payload", () => {
    const events = [
      decodeChatRunEvent(
        runFrame(
          "ai_delta",
          2,
          { text: "北京" },
          { messageId: "message-ai-1" },
        ),
      ),
      decodeChatRunEvent(
        runFrame(
          "tool_call_delta",
          3,
          {
            tool_call_id: "call-weather-1",
            name: null,
            arguments_delta: "{",
            index: 0,
          },
          { messageId: "message-ai-1" },
        ),
      ),
      decodeChatRunEvent(
        runFrame(
          "tool_result",
          4,
          {
            tool_call_id: "call-weather-1",
            name: "get_weather",
            content: "北京 24°C",
          },
          { messageId: "message-tool-1" },
        ),
      ),
      decodeChatRunEvent(
        runFrame("run_error", 5, {
          code: "agent_execution_failed",
          message: "Agent execution failed",
          retryable: true,
        }),
      ),
      decodeChatRunEvent(
        runFrame("run_interrupted", 6, { reason: "user_cancelled" }),
      ),
      decodeChatRunEvent(
        runFrame("run_completed", 7, { finish_reason: "stop" }),
      ),
    ];

    expect(events.map((event) => event.event)).toEqual([
      "ai_delta",
      "tool_call_delta",
      "tool_result",
      "run_error",
      "run_interrupted",
      "run_completed",
    ]);
    expect(events[1]?.payload).toEqual({
      toolCallId: "call-weather-1",
      name: null,
      argumentsDelta: "{",
      index: 0,
    });
    expect(events[2]?.payload).toEqual({
      toolCallId: "call-weather-1",
      name: "get_weather",
      content: "北京 24°C",
    });
  });

  it("解码 reasoning_delta 事件并规范化为 camelCase", () => {
    const event = decodeChatRunEvent(
      runFrame(
        "reasoning_delta",
        2,
        { text: "先分析问题。" },
        { messageId: "message-ai-1" },
      ),
    );

    expect(event.event).toBe("reasoning_delta");
    expect(event.payload).toEqual({ text: "先分析问题。" });
    expect(event.messageId).toBe("message-ai-1");
  });

  it("解码 Goal 评估阶段事件并拒绝未知阶段", () => {
    const event = decodeChatRunEvent(
      runFrame("goal_status", 2, { phase: "evaluating" }),
    );
    expect(event).toMatchObject({
      event: "goal_status",
      messageId: null,
      payload: { phase: "evaluating" },
    });
    expect(() =>
      decodeChatRunEvent(runFrame("goal_status", 2, { phase: "guessing" })),
    ).toThrowError(expect.objectContaining({ code: "invalid_payload" }));
  });

  it("校验并公开统一工具结果元数据", () => {
    const event = decodeChatRunEvent(
      runFrame(
        "tool_result",
        4,
        {
          tool_call_id: "call-search-1",
          name: "web_search",
          content: "[]",
          result_meta: {
            status: "no_results",
            recoverable_by_model: true,
            recommended_next_action: "rewrite_parameters",
            error_summary: null,
          },
        },
        { messageId: "message-tool-1" },
      ),
    );

    expect(event.payload).toMatchObject({
      resultMeta: {
        status: "no_results",
        recoverableByModel: true,
        recommendedNextAction: "rewrite_parameters",
        errorSummary: null,
      },
    });
  });

  it("拒绝无法解析的 JSON，且错误中不复制原始数据", () => {
    const secret = "sk-sensitive-value";
    const decode = () =>
      decodeChatRunEvent({
        event: "run_error",
        id: `${RUN_ID}:1`,
        data: `{${secret}`,
      });

    expect(decode).toThrowError(RunEventDecodeError);
    expect(decode).toThrowError(
      expect.objectContaining({ code: "invalid_json" }),
    );
    expect(decode).not.toThrowError(expect.stringContaining(secret));
  });

  it("拒绝未知事件名和不支持的协议版本", () => {
    expect(() =>
      decodeChatRunEvent(runFrame("future_event", 1, {})),
    ).toThrowError(expect.objectContaining({ code: "unknown_event" }));

    expect(() =>
      decodeChatRunEvent(
        runFrame(
          "run_started",
          1,
          { created_at: "2026-08-25T15:00:00+00:00" },
          { version: "2" },
        ),
      ),
    ).toThrowError(expect.objectContaining({ code: "unsupported_version" }));
  });

  it("拒绝与 run_id、sequence 不一致的 SSE id", () => {
    expect(() =>
      decodeChatRunEvent(
        runFrame(
          "run_started",
          1,
          { created_at: "2026-08-25T15:00:00+00:00" },
          { eventId: `${RUN_ID}:9` },
        ),
      ),
    ).toThrowError(expect.objectContaining({ code: "event_id_mismatch" }));
  });

  it("拒绝非法 sequence、UUID 和终止事件 message_id", () => {
    const invalidSequence = runFrame("run_completed", 0, {
      finish_reason: "stop",
    });
    expect(() => decodeChatRunEvent(invalidSequence)).toThrowError(
      expect.objectContaining({ code: "invalid_envelope" }),
    );

    const invalidUuid = runFrame(
      "run_completed",
      1,
      { finish_reason: "stop" },
      { runId: "not-a-uuid" },
    );
    expect(() => decodeChatRunEvent(invalidUuid)).toThrowError(
      expect.objectContaining({ code: "invalid_envelope" }),
    );

    expect(() =>
      decodeChatRunEvent(
        runFrame(
          "run_completed",
          1,
          { finish_reason: "stop" },
          { messageId: "unexpected-message" },
        ),
      ),
    ).toThrowError(expect.objectContaining({ code: "invalid_envelope" }));
  });

  it("严格校验事件 payload，但不会把敏感正文写入错误", () => {
    const secret = "sk-sensitive-tool-output";
    const decode = () =>
      decodeChatRunEvent(
        runFrame("run_error", 1, {
          code: "failed",
          message: secret,
          retryable: "true",
        }),
      );

    expect(decode).toThrowError(
      expect.objectContaining({ code: "invalid_payload" }),
    );
    expect(decode).not.toThrowError(expect.stringContaining(secret));
  });

  it("忽略未知附加字段，为 v1 向后兼容扩展保留空间", () => {
    const event = decodeChatRunEvent(
      runFrame(
        "run_completed",
        1,
        { finish_reason: "stop", future_payload_field: true },
        { extraData: { future_envelope_field: "allowed" } },
      ),
    );

    expect(event.event).toBe("run_completed");
    expect(event.payload).toEqual({ finishReason: "stop" });
  });
});
