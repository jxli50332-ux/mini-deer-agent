import type { ThreadHistoryItem } from "@/entities/message/model/types";
import {
  isSupportedTextAttachmentMediaType,
  type TextAttachmentContent,
} from "@/entities/attachment/model/text-attachments";
import { parseHumanInputResponse } from "@/features/chat/model/human-input";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type UnknownRecord = Record<string, unknown>;

export interface ThreadHistoryPage {
  readonly version: "1";
  readonly threadId: string;
  readonly threadExists: boolean;
  readonly items: readonly ThreadHistoryItem[];
  readonly hasMore: boolean;
  readonly nextBeforeSequence: number | null;
}

export interface ThreadHistoryPageRequest {
  readonly threadId: string;
  readonly limit?: number;
  readonly beforeSequence?: number;
  readonly signal?: AbortSignal;
}

export type ThreadHistoryPageLoader = (
  request: ThreadHistoryPageRequest,
) => Promise<ThreadHistoryPage>;

export type HistoryFetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export class ThreadHistoryClientError extends Error {
  readonly code:
    | "invalid_request"
    | "http_error"
    | "invalid_response"
    | "network_error"
    | "aborted";
  readonly retryable: boolean;

  constructor(
    code: ThreadHistoryClientError["code"],
    message: string,
    retryable: boolean,
  ) {
    super(message);
    this.name = "ThreadHistoryClientError";
    this.code = code;
    this.retryable = retryable;
  }
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalidResponse(message: string): never {
  throw new ThreadHistoryClientError("invalid_response", message, false);
}

function requiredString(record: UnknownRecord, field: string): string {
  const value = record[field];
  if (typeof value !== "string" || value.length === 0) {
    invalidResponse(`${field} 必须是非空字符串`);
  }
  return value;
}

function stringField(record: UnknownRecord, field: string): string {
  const value = record[field];
  if (typeof value !== "string") {
    invalidResponse(`${field} 必须是字符串`);
  }
  return value;
}

function nullableString(record: UnknownRecord, field: string): string | null {
  const value = record[field];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string") {
    invalidResponse(`${field} 必须是字符串或 null`);
  }
  return value;
}

function positiveInteger(record: UnknownRecord, field: string): number {
  const value = record[field];
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1) {
    invalidResponse(`${field} 必须是正整数`);
  }
  return value;
}

function parseTextAttachments(
  value: unknown,
): readonly TextAttachmentContent[] {
  if (value === undefined) {
    return [];
  }
  if (!Array.isArray(value)) {
    invalidResponse("消息 attachments 必须是数组");
  }
  return value.map((item) => {
    if (!isRecord(item)) {
      invalidResponse("附件元数据必须是 JSON object");
    }
    const mediaType = item.media_type;
    if (
      typeof mediaType !== "string" ||
      !isSupportedTextAttachmentMediaType(mediaType)
    ) {
      invalidResponse("附件 media_type 不受支持");
    }
    return {
      filename: requiredString(item, "filename"),
      mediaType,
      sizeBytes: positiveInteger(item, "size_bytes"),
      content: requiredString(item, "content"),
    };
  });
}

function parseHistoryItem(value: unknown): ThreadHistoryItem {
  if (!isRecord(value)) {
    invalidResponse("历史项目必须是 JSON object");
  }
  const id = requiredString(value, "id");
  const runId = requiredString(value, "run_id").toLowerCase();
  if (!UUID_PATTERN.test(runId)) {
    invalidResponse("run_id 必须是 UUID");
  }
  const threadSequence = positiveInteger(value, "thread_sequence");
  const createdAt = requiredString(value, "created_at");
  if (Number.isNaN(Date.parse(createdAt))) {
    invalidResponse("created_at 必须是有效日期时间");
  }

  if (value.kind === "message") {
    if (value.role !== "user" && value.role !== "assistant") {
      invalidResponse("消息 role 不受支持");
    }
    const attachments = parseTextAttachments(value.attachments);
    const hiddenFromUi = value.hidden_from_ui ?? false;
    if (typeof hiddenFromUi !== "boolean") {
      invalidResponse("消息 hidden_from_ui 必须是 boolean");
    }
    const humanInputResponse =
      value.human_input_response === null ||
      value.human_input_response === undefined
        ? null
        : parseHumanInputResponse(value.human_input_response);
    if (
      value.human_input_response !== null &&
      value.human_input_response !== undefined &&
      humanInputResponse === null
    ) {
      invalidResponse("消息 human_input_response 不受支持");
    }
    const reasoning =
      value.reasoning === null || value.reasoning === undefined
        ? undefined
        : requiredString(value, "reasoning");
    const content = stringField(value, "content");
    if (
      content.length === 0 &&
      (value.role === "user" || reasoning === undefined)
    ) {
      invalidResponse("content 必须是非空字符串");
    }
    return {
      kind: "message",
      id,
      role: value.role,
      content,
      runId,
      threadSequence,
      createdAt,
      ...(reasoning === undefined ? {} : { reasoning }),
      ...(attachments.length > 0 ? { attachments } : {}),
      ...(hiddenFromUi ? { hiddenFromUi: true } : {}),
      ...(humanInputResponse === null ? {} : { humanInputResponse }),
    };
  }

  if (value.kind === "tool") {
    const status = value.status;
    if (
      status !== "pending" &&
      status !== "completed" &&
      status !== "failed" &&
      status !== "cancelled"
    ) {
      invalidResponse("工具 status 不受支持");
    }
    return {
      kind: "tool",
      id,
      toolCallId: requiredString(value, "tool_call_id"),
      name: nullableString(value, "name"),
      input: stringField(value, "input"),
      result: nullableString(value, "result"),
      status,
      runId,
      threadSequence,
      createdAt,
    };
  }

  return invalidResponse("历史项目 kind 不受支持");
}

export function parseThreadHistoryPage(
  value: unknown,
  expectedThreadId: string,
): ThreadHistoryPage {
  if (!isRecord(value) || value.version !== "1") {
    invalidResponse("历史响应版本无效");
  }
  const threadId = requiredString(value, "thread_id").toLowerCase();
  if (threadId !== expectedThreadId) {
    invalidResponse("历史响应不属于请求的 Thread");
  }
  if (typeof value.thread_exists !== "boolean") {
    invalidResponse("thread_exists 必须是 boolean");
  }
  if (!Array.isArray(value.items) || typeof value.has_more !== "boolean") {
    invalidResponse("历史响应缺少 items 或 has_more");
  }

  const items = value.items.map(parseHistoryItem);
  const identities = new Set<string>();
  let previousSequence = 0;
  for (const item of items) {
    if (identities.has(item.id) || item.threadSequence <= previousSequence) {
      invalidResponse("历史项目 ID 重复或顺序不严格递增");
    }
    identities.add(item.id);
    previousSequence = item.threadSequence;
  }

  const nextBeforeSequence =
    value.next_before_sequence === null
      ? null
      : positiveInteger(value, "next_before_sequence");
  if (
    value.has_more === true &&
    (items.length === 0 || nextBeforeSequence !== items[0]?.threadSequence)
  ) {
    invalidResponse("历史分页游标与最早项目不一致");
  }
  if (value.has_more === false && nextBeforeSequence !== null) {
    invalidResponse("没有更早历史时游标必须为 null");
  }
  if (
    value.thread_exists === false &&
    (items.length > 0 || value.has_more === true)
  ) {
    invalidResponse("不存在的 Thread 不能返回历史项目");
  }

  return {
    version: "1",
    threadId,
    threadExists: value.thread_exists,
    items,
    hasMore: value.has_more,
    nextBeforeSequence,
  };
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

/**
 * 查询一页产品消息历史，并在返回 UI 前校验版本、身份、顺序和分页游标。
 */
export async function fetchThreadHistoryPage(
  request: ThreadHistoryPageRequest,
  options: { readonly fetcher?: HistoryFetchLike } = {},
): Promise<ThreadHistoryPage> {
  const threadId = request.threadId.trim().toLowerCase();
  const limit = request.limit ?? 100;
  if (
    !UUID_PATTERN.test(threadId) ||
    !Number.isSafeInteger(limit) ||
    limit < 1 ||
    limit > 200 ||
    (request.beforeSequence !== undefined &&
      (!Number.isSafeInteger(request.beforeSequence) ||
        request.beforeSequence < 1))
  ) {
    throw new ThreadHistoryClientError(
      "invalid_request",
      "历史查询参数无效",
      false,
    );
  }

  const query = new URLSearchParams({ limit: String(limit) });
  if (request.beforeSequence !== undefined) {
    query.set("before_sequence", String(request.beforeSequence));
  }
  try {
    const response = await (options.fetcher ?? globalThis.fetch)(
      `/api/v1/threads/${encodeURIComponent(threadId)}/messages?${query}`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        ...(request.signal === undefined ? {} : { signal: request.signal }),
      },
    );
    if (!response.ok) {
      await response.body?.cancel();
      throw new ThreadHistoryClientError(
        "http_error",
        response.status >= 500
          ? "历史服务暂时不可用"
          : "无法读取当前 Thread 历史",
        response.status >= 500,
      );
    }
    return parseThreadHistoryPage(await response.json(), threadId);
  } catch (error) {
    if (error instanceof ThreadHistoryClientError) {
      throw error;
    }
    if (request.signal?.aborted === true || isAbortError(error)) {
      throw new ThreadHistoryClientError("aborted", "历史查询已取消", false);
    }
    throw new ThreadHistoryClientError(
      "network_error",
      "无法连接历史服务",
      true,
    );
  }
}
