import type {
  ThreadStatus,
  ThreadSummary,
} from "@/entities/thread/model/types";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type UnknownRecord = Record<string, unknown>;

export interface ThreadListRequest {
  readonly limit?: number;
  readonly signal?: AbortSignal;
}

export type ThreadListLoader = (
  request: ThreadListRequest,
) => Promise<readonly ThreadSummary[]>;

export type ThreadListFetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface ThreadTitleUpdateRequest {
  readonly threadId: string;
  readonly title: string;
  readonly signal?: AbortSignal;
}

export type ThreadTitleUpdater = (
  request: ThreadTitleUpdateRequest,
) => Promise<ThreadSummary>;

export type ThreadTitleFetchLike = ThreadListFetchLike;

export interface ThreadDeleteRequest {
  readonly threadId: string;
  readonly signal?: AbortSignal;
}

export type ThreadDeleter = (request: ThreadDeleteRequest) => Promise<void>;

export type ThreadDeleteFetchLike = ThreadListFetchLike;

export class ThreadListClientError extends Error {
  readonly code:
    | "invalid_request"
    | "http_error"
    | "invalid_response"
    | "network_error"
    | "aborted";
  readonly retryable: boolean;

  constructor(
    code: ThreadListClientError["code"],
    message: string,
    retryable: boolean,
  ) {
    super(message);
    this.name = "ThreadListClientError";
    this.code = code;
    this.retryable = retryable;
  }
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalidResponse(message: string): never {
  throw new ThreadListClientError("invalid_response", message, false);
}

function requiredString(record: UnknownRecord, field: string): string {
  const value = record[field];
  if (typeof value !== "string" || value.length === 0) {
    invalidResponse(`${field} 必须是非空字符串`);
  }
  return value;
}

function parseTimestamp(record: UnknownRecord, field: string): string {
  const value = requiredString(record, field);
  if (Number.isNaN(Date.parse(value))) {
    invalidResponse(`${field} 必须是有效日期时间`);
  }
  return value;
}

function parseStatus(record: UnknownRecord): ThreadStatus {
  const status = record.status;
  if (status !== "idle" && status !== "busy" && status !== "error") {
    invalidResponse("Thread status 不受支持");
  }
  return status;
}

function parseTitle(record: UnknownRecord): string | null {
  const title = record.title;
  if (title === null) {
    return null;
  }
  if (typeof title !== "string" || title.length === 0 || title.length > 60) {
    invalidResponse("title 必须是非空字符串或 null");
  }
  return title;
}

function parseProjectId(record: UnknownRecord): string | null {
  const projectId = record.project_id;
  if (projectId === null) return null;
  if (typeof projectId !== "string" || !UUID_PATTERN.test(projectId)) {
    invalidResponse("project_id 必须是 UUID 或 null");
  }
  return projectId.toLowerCase();
}

export function parseThreadSummary(value: unknown): ThreadSummary {
  if (!isRecord(value)) {
    invalidResponse("Thread 列表项必须是 JSON object");
  }
  const threadId = requiredString(value, "thread_id").toLowerCase();
  if (!UUID_PATTERN.test(threadId)) {
    invalidResponse("thread_id 必须是 UUID");
  }
  return {
    threadId,
    title: parseTitle(value),
    status: parseStatus(value),
    projectId: parseProjectId(value),
    createdAt: parseTimestamp(value, "created_at"),
    updatedAt: parseTimestamp(value, "updated_at"),
  };
}

function normalizeRequestedTitle(title: string): string {
  return title.trim().replace(/\s+/g, " ");
}

/** 把不可信服务端 JSON 校验为可供 UI 使用的最近 Thread 列表。 */
export function parseThreadList(value: unknown): readonly ThreadSummary[] {
  if (!Array.isArray(value)) {
    invalidResponse("Thread 列表响应必须是 JSON array");
  }
  const items = value.map(parseThreadSummary);
  const identities = new Set<string>();
  for (const item of items) {
    if (identities.has(item.threadId)) {
      invalidResponse("Thread 列表包含重复 ID");
    }
    identities.add(item.threadId);
  }
  return items;
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

/** 请求正式最近 Thread API，并在数据进入页面前完成运行时校验。 */
export async function fetchThreadList(
  request: ThreadListRequest,
  options: { readonly fetcher?: ThreadListFetchLike } = {},
): Promise<readonly ThreadSummary[]> {
  const limit = request.limit ?? 20;
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new ThreadListClientError(
      "invalid_request",
      "最近会话数量参数无效",
      false,
    );
  }

  try {
    const response = await (options.fetcher ?? globalThis.fetch)(
      `/api/v1/threads?limit=${limit}`,
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
      throw new ThreadListClientError(
        "http_error",
        response.status >= 500 ? "最近会话服务暂时不可用" : "无法读取最近会话",
        response.status >= 500,
      );
    }
    return parseThreadList(await response.json());
  } catch (error) {
    if (error instanceof ThreadListClientError) {
      throw error;
    }
    if (request.signal?.aborted === true || isAbortError(error)) {
      throw new ThreadListClientError("aborted", "最近会话查询已取消", false);
    }
    throw new ThreadListClientError(
      "network_error",
      "无法连接最近会话服务",
      true,
    );
  }
}

/** 更新一个 Thread 的业务标题，并把完整服务端记录作为唯一成功结果。 */
export async function updateThreadTitle(
  request: ThreadTitleUpdateRequest,
  options: { readonly fetcher?: ThreadTitleFetchLike } = {},
): Promise<ThreadSummary> {
  const threadId = request.threadId.toLowerCase();
  const title = normalizeRequestedTitle(request.title);
  if (!UUID_PATTERN.test(threadId) || title.length < 1 || title.length > 60) {
    throw new ThreadListClientError(
      "invalid_request",
      "会话标题必须包含 1 到 60 个字符",
      false,
    );
  }

  try {
    const response = await (options.fetcher ?? globalThis.fetch)(
      `/api/v1/threads/${threadId}`,
      {
        method: "PATCH",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({ title }),
        ...(request.signal === undefined ? {} : { signal: request.signal }),
      },
    );
    if (!response.ok) {
      await response.body?.cancel();
      throw new ThreadListClientError(
        "http_error",
        response.status === 404
          ? "这个会话已经不存在"
          : response.status >= 500
            ? "改名服务暂时不可用"
            : "无法更新会话标题",
        response.status >= 500,
      );
    }
    return parseThreadSummary(await response.json());
  } catch (error) {
    if (error instanceof ThreadListClientError) {
      throw error;
    }
    if (request.signal?.aborted === true || isAbortError(error)) {
      throw new ThreadListClientError("aborted", "会话改名已取消", false);
    }
    throw new ThreadListClientError("network_error", "无法连接改名服务", true);
  }
}

/** 删除一个持久化 Thread；204 表示业务历史与 checkpoint 已共同删除。 */
export async function deleteThread(
  request: ThreadDeleteRequest,
  options: { readonly fetcher?: ThreadDeleteFetchLike } = {},
): Promise<void> {
  const threadId = request.threadId.toLowerCase();
  if (!UUID_PATTERN.test(threadId)) {
    throw new ThreadListClientError(
      "invalid_request",
      "待删除的会话 ID 无效",
      false,
    );
  }

  try {
    const response = await (options.fetcher ?? globalThis.fetch)(
      `/api/v1/threads/${threadId}`,
      {
        method: "DELETE",
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        ...(request.signal === undefined ? {} : { signal: request.signal }),
      },
    );
    if (response.status !== 204) {
      await response.body?.cancel();
      throw new ThreadListClientError(
        "http_error",
        response.status === 409
          ? "会话正在运行，结束后才能删除"
          : response.status === 404
            ? "这个会话已经不存在"
            : response.status >= 500
              ? "删除服务暂时不可用"
              : "无法删除会话",
        response.status >= 500,
      );
    }
  } catch (error) {
    if (error instanceof ThreadListClientError) {
      throw error;
    }
    if (request.signal?.aborted === true || isAbortError(error)) {
      throw new ThreadListClientError("aborted", "会话删除已取消", false);
    }
    throw new ThreadListClientError("network_error", "无法连接删除服务", true);
  }
}
