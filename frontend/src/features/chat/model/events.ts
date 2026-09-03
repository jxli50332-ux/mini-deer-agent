import type { SseFrame } from "@/shared/api/sse-parser";

export interface RunStartedPayload {
  readonly createdAt: string;
}

export interface AiDeltaPayload {
  readonly text: string;
}

export interface ReasoningDeltaPayload {
  readonly text: string;
}

export interface ToolCallDeltaPayload {
  readonly toolCallId: string;
  readonly name: string | null;
  readonly argumentsDelta: string;
  readonly index: number;
}

export interface ToolResultPayload {
  readonly toolCallId: string;
  readonly name: string | null;
  readonly content: string;
}

export interface RunErrorPayload {
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
}

export interface RunCompletedPayload {
  readonly finishReason: string;
}

export interface RunInterruptedPayload {
  readonly reason: string;
}

interface ChatRunEventBase<TEvent extends string, TPayload> {
  readonly event: TEvent;
  readonly eventId: string;
  readonly version: "1";
  readonly runId: string;
  readonly threadId: string;
  readonly sequence: number;
  readonly messageId: string | null;
  readonly payload: TPayload;
}

export type RunStartedEvent = ChatRunEventBase<
  "run_started",
  RunStartedPayload
>;
export type AiDeltaEvent = ChatRunEventBase<"ai_delta", AiDeltaPayload>;
export type ReasoningDeltaEvent = ChatRunEventBase<
  "reasoning_delta",
  ReasoningDeltaPayload
>;
export type ToolCallDeltaEvent = ChatRunEventBase<
  "tool_call_delta",
  ToolCallDeltaPayload
>;
export type ToolResultEvent = ChatRunEventBase<
  "tool_result",
  ToolResultPayload
>;
export type RunErrorEvent = ChatRunEventBase<"run_error", RunErrorPayload>;
export type RunInterruptedEvent = ChatRunEventBase<
  "run_interrupted",
  RunInterruptedPayload
>;
export type RunCompletedEvent = ChatRunEventBase<
  "run_completed",
  RunCompletedPayload
>;

// reducer 只接收这个判别联合，不再重复处理 unknown JSON 和 snake_case wire 字段。
export type ChatRunEvent =
  | RunStartedEvent
  | AiDeltaEvent
  | ReasoningDeltaEvent
  | ToolCallDeltaEvent
  | ToolResultEvent
  | RunErrorEvent
  | RunInterruptedEvent
  | RunCompletedEvent;

export type RunEventDecodeErrorCode =
  | "invalid_json"
  | "unknown_event"
  | "unsupported_version"
  | "invalid_envelope"
  | "event_id_mismatch"
  | "invalid_payload";

export class RunEventDecodeError extends Error {
  readonly code: RunEventDecodeErrorCode;

  constructor(code: RunEventDecodeErrorCode, message: string) {
    super(message);
    this.name = "RunEventDecodeError";
    this.code = code;
  }
}

type UnknownRecord = Record<string, unknown>;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function fail(code: RunEventDecodeErrorCode, message: string): never {
  throw new RunEventDecodeError(code, message);
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(
  value: unknown,
  label: string,
  code: RunEventDecodeErrorCode,
): UnknownRecord {
  if (!isRecord(value)) {
    fail(code, `${label} 必须是 JSON object`);
  }
  return value;
}

function requireString(
  record: UnknownRecord,
  field: string,
  code: RunEventDecodeErrorCode,
  allowEmpty = false,
): string {
  const value = record[field];
  if (typeof value !== "string" || (!allowEmpty && value.length === 0)) {
    fail(code, `${field} 必须是${allowEmpty ? "" : "非空"}字符串`);
  }
  return value;
}

function requireNullableString(
  record: UnknownRecord,
  field: string,
  code: RunEventDecodeErrorCode,
): string | null {
  const value = record[field];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string" || value.length === 0) {
    fail(code, `${field} 必须是 null 或非空字符串`);
  }
  return value;
}

function requireBoolean(
  record: UnknownRecord,
  field: string,
  code: RunEventDecodeErrorCode,
): boolean {
  const value = record[field];
  if (typeof value !== "boolean") {
    fail(code, `${field} 必须是 boolean`);
  }
  return value;
}

function requireInteger(
  record: UnknownRecord,
  field: string,
  code: RunEventDecodeErrorCode,
  minimum: number,
): number {
  const value = record[field];
  if (
    typeof value !== "number" ||
    !Number.isSafeInteger(value) ||
    value < minimum
  ) {
    fail(code, `${field} 必须是大于等于 ${minimum} 的安全整数`);
  }
  return value;
}

function requireUuid(record: UnknownRecord, field: string): string {
  const value = requireString(record, field, "invalid_envelope");
  if (!UUID_PATTERN.test(value)) {
    fail("invalid_envelope", `${field} 必须是规范 UUID`);
  }
  return value;
}

function requireIsoDateTime(record: UnknownRecord, field: string): string {
  const value = requireString(record, field, "invalid_payload");
  if (Number.isNaN(Date.parse(value))) {
    fail("invalid_payload", `${field} 必须是有效日期时间`);
  }
  return value;
}

function isRunEventName(value: string): value is ChatRunEvent["event"] {
  return (
    value === "run_started" ||
    value === "ai_delta" ||
    value === "reasoning_delta" ||
    value === "tool_call_delta" ||
    value === "tool_result" ||
    value === "run_error" ||
    value === "run_interrupted" ||
    value === "run_completed"
  );
}

function requireNoMessageId(eventName: string, messageId: string | null): void {
  if (messageId !== null) {
    fail("invalid_envelope", `${eventName} 的 message_id 必须是 null`);
  }
}

function parseJsonObject(data: string): UnknownRecord {
  let parsed: unknown;
  try {
    parsed = JSON.parse(data) as unknown;
  } catch {
    // 不把原始 data 或 JSON 异常正文带入错误，避免泄露模型与工具内容。
    fail("invalid_json", "SSE data 不是合法 JSON");
  }
  return requireRecord(parsed, "SSE data", "invalid_envelope");
}

/**
 * 校验后端 v1 SSE frame，并把 wire 层 snake_case 字段规范化为前端 camelCase。
 * 返回后 reducer 可以信任字段类型，但仍不能把正文当成可信 HTML。
 */
export function decodeChatRunEvent(frame: SseFrame): ChatRunEvent {
  if (!isRunEventName(frame.event)) {
    fail("unknown_event", "SSE event 不是受支持的 run 事件");
  }
  if (frame.id === undefined || frame.id.length === 0) {
    fail("invalid_envelope", "v1 run 事件必须携带 SSE id");
  }

  const data = parseJsonObject(frame.data);
  if (data.version !== "1") {
    fail("unsupported_version", "不支持该 run 事件协议版本");
  }

  const runId = requireUuid(data, "run_id");
  const threadId = requireUuid(data, "thread_id");
  const sequence = requireInteger(data, "sequence", "invalid_envelope", 1);
  const messageId = requireNullableString(
    data,
    "message_id",
    "invalid_envelope",
  );
  const payload = requireRecord(data.payload, "payload", "invalid_payload");

  if (frame.id !== `${runId}:${sequence}`) {
    fail("event_id_mismatch", "SSE id 与 run_id、sequence 不一致");
  }

  const base = {
    eventId: frame.id,
    version: "1" as const,
    runId,
    threadId,
    sequence,
    messageId,
  };

  switch (frame.event) {
    case "run_started":
      requireNoMessageId(frame.event, messageId);
      return {
        ...base,
        event: frame.event,
        payload: {
          createdAt: requireIsoDateTime(payload, "created_at"),
        },
      };
    case "ai_delta":
      return {
        ...base,
        event: frame.event,
        payload: {
          text: requireString(payload, "text", "invalid_payload"),
        },
      };
    case "reasoning_delta":
      return {
        ...base,
        event: frame.event,
        payload: {
          text: requireString(payload, "text", "invalid_payload"),
        },
      };
    case "tool_call_delta":
      return {
        ...base,
        event: frame.event,
        payload: {
          toolCallId: requireString(payload, "tool_call_id", "invalid_payload"),
          name: requireNullableString(payload, "name", "invalid_payload"),
          argumentsDelta: requireString(
            payload,
            "arguments_delta",
            "invalid_payload",
            true,
          ),
          index: requireInteger(payload, "index", "invalid_payload", 0),
        },
      };
    case "tool_result":
      return {
        ...base,
        event: frame.event,
        payload: {
          toolCallId: requireString(payload, "tool_call_id", "invalid_payload"),
          name: requireNullableString(payload, "name", "invalid_payload"),
          content: requireString(payload, "content", "invalid_payload", true),
        },
      };
    case "run_error":
      requireNoMessageId(frame.event, messageId);
      return {
        ...base,
        event: frame.event,
        payload: {
          code: requireString(payload, "code", "invalid_payload"),
          message: requireString(payload, "message", "invalid_payload"),
          retryable: requireBoolean(payload, "retryable", "invalid_payload"),
        },
      };
    case "run_interrupted":
      requireNoMessageId(frame.event, messageId);
      return {
        ...base,
        event: frame.event,
        payload: {
          reason: requireString(payload, "reason", "invalid_payload"),
        },
      };
    case "run_completed":
      requireNoMessageId(frame.event, messageId);
      return {
        ...base,
        event: frame.event,
        payload: {
          finishReason: requireString(
            payload,
            "finish_reason",
            "invalid_payload",
          ),
        },
      };
  }
}
