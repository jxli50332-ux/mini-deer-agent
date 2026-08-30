import {
  ChatStreamClientError,
  parseChatRunDetail,
  type ChatRunDetail,
} from "@/features/chat/api/chat-stream";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface ThreadRunsRequest {
  readonly threadId: string;
  readonly limit?: number;
  readonly signal?: AbortSignal;
}

export type ThreadRunsLoader = (
  request: ThreadRunsRequest,
) => Promise<readonly ChatRunDetail[]>;

export type ThreadRunsFetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export class ThreadRunsClientError extends Error {
  readonly code:
    | "invalid_request"
    | "http_error"
    | "invalid_response"
    | "network_error"
    | "aborted";
  readonly retryable: boolean;

  constructor(
    code: ThreadRunsClientError["code"],
    message: string,
    retryable: boolean,
  ) {
    super(message);
    this.name = "ThreadRunsClientError";
    this.code = code;
    this.retryable = retryable;
  }
}

export function parseThreadRuns(
  value: unknown,
  expectedThreadId: string,
): readonly ChatRunDetail[] {
  if (!Array.isArray(value)) {
    throw new ThreadRunsClientError(
      "invalid_response",
      "Run 列表响应必须是数组",
      false,
    );
  }
  try {
    const runs = value.map((item) =>
      parseChatRunDetail(item, { threadId: expectedThreadId }),
    );
    const identities = new Set<string>();
    for (const run of runs) {
      if (identities.has(run.runId)) {
        throw new ThreadRunsClientError(
          "invalid_response",
          "Run 列表包含重复身份",
          false,
        );
      }
      identities.add(run.runId);
    }
    return runs;
  } catch (error) {
    if (error instanceof ThreadRunsClientError) {
      throw error;
    }
    if (error instanceof ChatStreamClientError) {
      throw new ThreadRunsClientError(
        "invalid_response",
        "Run 列表包含无效记录",
        false,
      );
    }
    throw error;
  }
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

/** 读取 Thread 的持久化 Run 生命周期，用于恢复每轮权威耗时。 */
export async function fetchThreadRuns(
  request: ThreadRunsRequest,
  options: { readonly fetcher?: ThreadRunsFetchLike } = {},
): Promise<readonly ChatRunDetail[]> {
  const threadId = request.threadId.trim().toLowerCase();
  const limit = request.limit ?? 200;
  if (
    !UUID_PATTERN.test(threadId) ||
    !Number.isSafeInteger(limit) ||
    limit < 1 ||
    limit > 200
  ) {
    throw new ThreadRunsClientError(
      "invalid_request",
      "Run 列表查询参数无效",
      false,
    );
  }

  try {
    const response = await (options.fetcher ?? globalThis.fetch)(
      `/api/v1/threads/${encodeURIComponent(threadId)}/runs?limit=${limit}`,
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
      throw new ThreadRunsClientError(
        "http_error",
        response.status >= 500
          ? "Run 历史服务暂时不可用"
          : "无法读取当前 Thread 的 Run 历史",
        response.status >= 500,
      );
    }
    return parseThreadRuns(await response.json(), threadId);
  } catch (error) {
    if (error instanceof ThreadRunsClientError) {
      throw error;
    }
    if (request.signal?.aborted === true || isAbortError(error)) {
      throw new ThreadRunsClientError("aborted", "Run 历史查询已取消", false);
    }
    throw new ThreadRunsClientError(
      "network_error",
      "无法连接 Run 历史服务",
      true,
    );
  }
}
