import {
  decodeChatRunEvent,
  RunEventDecodeError,
  type ChatRunEvent,
} from "@/features/chat/model/events";
import {
  parseSseStream,
  SseInactivityTimeoutError,
  SseParseError,
} from "@/shared/api/sse-parser";
import {
  validateTextAttachmentPayloads,
  type TextAttachmentPayload,
} from "@/entities/attachment/model/text-attachments";
import {
  parseHumanInputResponse,
  type HumanInputResponse,
} from "@/features/chat/model/human-input";

export interface ChatStreamRequest {
  readonly threadId: string;
  readonly messageId: string;
  readonly message: string;
  readonly attachments?: readonly TextAttachmentPayload[];
  readonly humanInputResponse?: HumanInputResponse;
  readonly benchmarkCaseId?: string;
  readonly goalResumeRevision?: string;
  readonly skillInstallAuthorizationToken?: string;
  readonly signal?: AbortSignal;
  readonly onRunId?: (runId: string) => void;
}

export interface ChatRunCancelRequest {
  readonly threadId: string;
  readonly runId: string;
}

export interface ChatRunDetailRequest extends ChatRunCancelRequest {
  readonly signal?: AbortSignal;
}

export type ChatRunStatus =
  "pending" | "running" | "completed" | "failed" | "cancelled" | "interrupted";

export interface ChatRunDetail {
  readonly runId: string;
  readonly threadId: string;
  readonly status: ChatRunStatus;
  readonly userMessageId: string;
  readonly createdAt: string;
  readonly startedAt: string | null;
  readonly finishedAt: string | null;
  readonly finishReason: string | null;
  readonly errorCode: string | null;
  readonly inputTokens?: number | null;
  readonly outputTokens?: number | null;
  readonly totalTokens?: number | null;
  readonly modelCalls?: number | null;
  readonly modelProfile?: string | null;
  readonly modelProfileRevision?: string | null;
  readonly modelSelectionRevision?: number | null;
  readonly skillCatalogHash?: string | null;
}

export type ChatRunReconciler = (
  request: ChatRunDetailRequest,
) => Promise<ChatRunDetail>;

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface ChatStreamClientOptions {
  readonly fetcher?: FetchLike;
  readonly inactivityTimeoutMilliseconds?: number;
}

export type ChatStreamClientErrorCode =
  | "invalid_request"
  | "unauthorized"
  | "forbidden"
  | "thread_not_found"
  | "run_not_found"
  | "run_conflict"
  | "run_not_cancellable"
  | "rate_limited"
  | "server_unavailable"
  | "http_error"
  | "invalid_content_type"
  | "missing_response_body"
  | "missing_run_id"
  | "invalid_run_response"
  | "stream_protocol_error"
  | "stream_inactive"
  | "incomplete_stream"
  | "network_error"
  | "aborted";

export class ChatStreamClientError extends Error {
  readonly code: ChatStreamClientErrorCode;
  readonly retryable: boolean;
  readonly status: number | null;

  constructor(
    code: ChatStreamClientErrorCode,
    message: string,
    options: { readonly retryable: boolean; readonly status?: number } = {
      retryable: false,
    },
  ) {
    super(message);
    this.name = "ChatStreamClientError";
    this.code = code;
    this.retryable = options.retryable;
    this.status = options.status ?? null;
  }
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_MESSAGE_CHARACTERS = 32_768;
const DEFAULT_STREAM_INACTIVITY_TIMEOUT_MILLISECONDS = 45_000;
const DEFAULT_RUN_RECONCILIATION_ATTEMPTS = 5;
const DEFAULT_RUN_RECONCILIATION_DELAY_MILLISECONDS = 250;
const DEFAULT_RUN_RECONCILIATION_TIMEOUT_MILLISECONDS = 5_000;

type UnknownRecord = Record<string, unknown>;

function resolveInactivityTimeout(value: number | undefined): number {
  const resolved = value ?? DEFAULT_STREAM_INACTIVITY_TIMEOUT_MILLISECONDS;
  if (!Number.isSafeInteger(resolved) || resolved <= 0) {
    throw new ChatStreamClientError(
      "invalid_request",
      "SSE 静默超时必须是大于 0 的安全整数",
      { retryable: false },
    );
  }
  return resolved;
}

function validateRequest(request: ChatStreamRequest): {
  readonly threadId: string;
  readonly messageId: string;
  readonly message: string;
  readonly attachments: readonly TextAttachmentPayload[];
  readonly humanInputResponse: HumanInputResponse | null;
  readonly benchmarkCaseId: string | null;
  readonly goalResumeRevision: string | null;
  readonly skillInstallAuthorizationToken: string | null;
} {
  const threadId = request.threadId.trim().toLowerCase();
  if (!UUID_PATTERN.test(threadId)) {
    throw new ChatStreamClientError(
      "invalid_request",
      "threadId 必须是有效 UUID",
      { retryable: false },
    );
  }

  const messageId = request.messageId.trim().toLowerCase();
  if (!UUID_PATTERN.test(messageId)) {
    throw new ChatStreamClientError(
      "invalid_request",
      "messageId 必须是有效 UUID",
      { retryable: false },
    );
  }

  const message = request.message.trim();
  if (message.length === 0 || message.length > MAX_MESSAGE_CHARACTERS) {
    throw new ChatStreamClientError(
      "invalid_request",
      `消息长度必须在 1 到 ${MAX_MESSAGE_CHARACTERS} 个字符之间`,
      { retryable: false },
    );
  }
  const benchmarkCaseId = request.benchmarkCaseId?.trim() ?? null;
  if (benchmarkCaseId !== null && !/^[a-z0-9-]{1,64}$/.test(benchmarkCaseId)) {
    throw new ChatStreamClientError(
      "invalid_request",
      "benchmarkCaseId 格式无效",
      { retryable: false },
    );
  }
  let attachments;
  try {
    attachments = validateTextAttachmentPayloads(request.attachments ?? []).map(
      ({ filename, content }) => ({ filename, content }),
    );
  } catch (error) {
    throw new ChatStreamClientError(
      "invalid_request",
      error instanceof Error ? error.message : "附件无效",
      { retryable: false },
    );
  }
  const humanInputResponse =
    request.humanInputResponse === undefined
      ? null
      : parseHumanInputResponse(request.humanInputResponse);
  if (request.humanInputResponse !== undefined && humanInputResponse === null) {
    throw new ChatStreamClientError(
      "invalid_request",
      "humanInputResponse 不是受支持的 v1 澄清回答",
      { retryable: false },
    );
  }
  const goalResumeRevision =
    request.goalResumeRevision?.trim().toLowerCase() ?? null;
  if (goalResumeRevision !== null && !UUID_PATTERN.test(goalResumeRevision)) {
    throw new ChatStreamClientError(
      "invalid_request",
      "goalResumeRevision 必须是有效 UUID",
      { retryable: false },
    );
  }
  const skillInstallAuthorizationToken =
    request.skillInstallAuthorizationToken?.trim().toLowerCase() ?? null;
  if (
    skillInstallAuthorizationToken !== null &&
    !/^[a-f0-9]{32}$/.test(skillInstallAuthorizationToken)
  ) {
    throw new ChatStreamClientError(
      "invalid_request",
      "skillInstallAuthorizationToken 格式无效",
      { retryable: false },
    );
  }
  if (
    goalResumeRevision !== null &&
    (attachments.length > 0 ||
      humanInputResponse !== null ||
      benchmarkCaseId !== null ||
      skillInstallAuthorizationToken !== null)
  ) {
    throw new ChatStreamClientError(
      "invalid_request",
      "恢复 Goal 时不能同时提交附件、澄清回答、基准任务或 Skill 安装授权",
      { retryable: false },
    );
  }
  return {
    threadId,
    messageId,
    message,
    attachments,
    humanInputResponse,
    benchmarkCaseId,
    goalResumeRevision,
    skillInstallAuthorizationToken,
  };
}

function validateRunAddress(request: ChatRunCancelRequest): {
  readonly threadId: string;
  readonly runId: string;
} {
  const threadId = request.threadId.trim().toLowerCase();
  const runId = request.runId.trim().toLowerCase();
  if (!UUID_PATTERN.test(threadId) || !UUID_PATTERN.test(runId)) {
    throw new ChatStreamClientError(
      "invalid_request",
      "Run 请求必须包含有效的 threadId 和 runId",
      { retryable: false },
    );
  }
  return { threadId, runId };
}

function invalidRunResponse(message: string): never {
  throw new ChatStreamClientError("invalid_run_response", message, {
    retryable: false,
  });
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(record: UnknownRecord, field: string): string {
  const value = record[field];
  if (typeof value !== "string" || value.length === 0) {
    invalidRunResponse(`${field} 必须是非空字符串`);
  }
  return value;
}

function nullableString(record: UnknownRecord, field: string): string | null {
  const value = record[field];
  if (value === null) {
    return null;
  }
  if (typeof value !== "string") {
    invalidRunResponse(`${field} 必须是字符串或 null`);
  }
  return value;
}

function optionalNullableInteger(
  record: UnknownRecord,
  field: string,
): number | null {
  const value = record[field];
  if (value === undefined || value === null) {
    return null;
  }
  if (!Number.isInteger(value) || (value as number) < 0) {
    invalidRunResponse(`${field} 必须是非负整数或 null`);
  }
  return value as number;
}

function timestampField(
  record: UnknownRecord,
  field: string,
  nullable: boolean,
): string | null {
  const value = nullable
    ? nullableString(record, field)
    : requiredString(record, field);
  if (value !== null && Number.isNaN(Date.parse(value))) {
    invalidRunResponse(`${field} 必须是有效日期时间`);
  }
  return value;
}

function runStatus(record: UnknownRecord): ChatRunStatus {
  const value = record.status;
  if (
    value !== "pending" &&
    value !== "running" &&
    value !== "completed" &&
    value !== "failed" &&
    value !== "cancelled" &&
    value !== "interrupted"
  ) {
    invalidRunResponse("Run status 不受支持");
  }
  return value;
}

/** 把不可信 JSON 校验为路径中指定 Run 的持久化生命周期快照。 */
export function parseChatRunDetail(
  value: unknown,
  expected: { readonly threadId: string; readonly runId?: string },
): ChatRunDetail {
  if (!isRecord(value)) {
    invalidRunResponse("Run 详情响应必须是 JSON object");
  }
  const expectedThreadId = expected.threadId.trim().toLowerCase();
  const expectedRunId = expected.runId?.trim().toLowerCase();
  if (
    !UUID_PATTERN.test(expectedThreadId) ||
    (expectedRunId !== undefined && !UUID_PATTERN.test(expectedRunId))
  ) {
    invalidRunResponse("Run 详情校验必须包含有效的 Thread 和 Run 身份");
  }
  const runId = requiredString(value, "run_id").toLowerCase();
  const threadId = requiredString(value, "thread_id").toLowerCase();
  const userMessageId = requiredString(value, "user_message_id").toLowerCase();
  if (!UUID_PATTERN.test(runId) || !UUID_PATTERN.test(threadId)) {
    invalidRunResponse("Run 详情身份必须是 UUID");
  }
  if (!UUID_PATTERN.test(userMessageId)) {
    invalidRunResponse("user_message_id 必须是 UUID");
  }
  if (
    threadId !== expectedThreadId ||
    (expectedRunId !== undefined && runId !== expectedRunId)
  ) {
    invalidRunResponse("Run 详情身份与请求路径不一致");
  }
  return {
    runId,
    threadId,
    status: runStatus(value),
    userMessageId,
    createdAt: timestampField(value, "created_at", false) ?? "",
    startedAt: timestampField(value, "started_at", true),
    finishedAt: timestampField(value, "finished_at", true),
    finishReason: nullableString(value, "finish_reason"),
    errorCode: nullableString(value, "error_code"),
    ...(value.input_tokens === undefined
      ? {}
      : { inputTokens: optionalNullableInteger(value, "input_tokens") }),
    ...(value.output_tokens === undefined
      ? {}
      : { outputTokens: optionalNullableInteger(value, "output_tokens") }),
    ...(value.total_tokens === undefined
      ? {}
      : { totalTokens: optionalNullableInteger(value, "total_tokens") }),
    ...(value.model_calls === undefined
      ? {}
      : { modelCalls: optionalNullableInteger(value, "model_calls") }),
    ...(value.model_profile === undefined
      ? {}
      : { modelProfile: nullableString(value, "model_profile") }),
    ...(value.model_profile_revision === undefined
      ? {}
      : {
          modelProfileRevision: nullableString(value, "model_profile_revision"),
        }),
    ...(value.model_selection_revision === undefined
      ? {}
      : {
          modelSelectionRevision: optionalNullableInteger(
            value,
            "model_selection_revision",
          ),
        }),
    ...(value.skill_catalog_hash === undefined
      ? {}
      : { skillCatalogHash: nullableString(value, "skill_catalog_hash") }),
  };
}

async function cancelResponseBody(response: Response): Promise<void> {
  try {
    await response.body?.cancel();
  } catch {
    // 错误响应清理失败不应覆盖真正的 HTTP 或协议错误。
  }
}

function httpFailure(status: number): ChatStreamClientError {
  if (status === 400 || status === 422) {
    return new ChatStreamClientError("invalid_request", "后端拒绝了聊天请求", {
      retryable: false,
      status,
    });
  }
  if (status === 401) {
    return new ChatStreamClientError("unauthorized", "需要登录后才能继续", {
      retryable: false,
      status,
    });
  }
  if (status === 403) {
    return new ChatStreamClientError("forbidden", "当前身份无权访问该线程", {
      retryable: false,
      status,
    });
  }
  if (status === 404) {
    return new ChatStreamClientError(
      "thread_not_found",
      "聊天线程不存在或不可访问",
      { retryable: false, status },
    );
  }
  if (status === 409) {
    return new ChatStreamClientError(
      "run_conflict",
      "该线程已有正在执行的 run",
      { retryable: true, status },
    );
  }
  if (status === 429) {
    return new ChatStreamClientError(
      "rate_limited",
      "请求过于频繁，请稍后重试",
      { retryable: true, status },
    );
  }
  if (status >= 500) {
    return new ChatStreamClientError(
      "server_unavailable",
      "Agent 服务暂时不可用",
      { retryable: true, status },
    );
  }
  return new ChatStreamClientError("http_error", "聊天请求失败", {
    retryable: status === 408 || status === 425,
    status,
  });
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

function normalizeClientError(
  error: unknown,
  signal: AbortSignal | undefined,
): ChatStreamClientError {
  if (error instanceof ChatStreamClientError) {
    return error;
  }
  if (signal?.aborted === true || isAbortError(error)) {
    return new ChatStreamClientError("aborted", "本次生成已取消", {
      retryable: false,
    });
  }
  if (error instanceof RunEventDecodeError) {
    return new ChatStreamClientError(
      "stream_protocol_error",
      "服务端返回了无法识别的 Agent 事件",
      { retryable: false },
    );
  }
  if (error instanceof SseInactivityTimeoutError) {
    return new ChatStreamClientError(
      "stream_inactive",
      "长时间未收到 Agent 心跳或事件，连接可能已经中断",
      { retryable: true },
    );
  }
  if (error instanceof SseParseError) {
    return new ChatStreamClientError(
      "stream_protocol_error",
      "Agent 事件流格式不完整或不合法",
      { retryable: error.code === "truncated_frame" },
    );
  }
  // 浏览器 fetch 的网络异常通常是 TypeError，但不能把原异常正文直接展示给用户。
  return new ChatStreamClientError(
    "network_error",
    "无法连接 Mini Deer Agent 后端",
    { retryable: true },
  );
}

function isTerminalEvent(event: ChatRunEvent): boolean {
  return (
    event.event === "run_completed" ||
    event.event === "run_error" ||
    event.event === "run_interrupted"
  );
}

/**
 * 显式取消服务端 Run；成功只表示终态已经持久化，SSE 仍负责交付 run_interrupted。
 */
export async function cancelChatRun(
  request: ChatRunCancelRequest,
  options: ChatStreamClientOptions = {},
): Promise<void> {
  const { threadId, runId } = validateRunAddress(request);

  const fetcher = options.fetcher ?? globalThis.fetch;
  let response: Response;
  try {
    response = await fetcher(
      `/api/v1/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/cancel`,
      {
        method: "POST",
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
      },
    );
  } catch (error) {
    throw normalizeClientError(error, undefined);
  }

  if (response.status === 204) {
    return;
  }
  await cancelResponseBody(response);
  if (response.status === 404) {
    throw new ChatStreamClientError("run_not_found", "要取消的 Run 不存在", {
      retryable: false,
      status: response.status,
    });
  }
  if (response.status === 409) {
    throw new ChatStreamClientError(
      "run_not_cancellable",
      "Run 已结束或当前服务实例无法取消它",
      { retryable: true, status: response.status },
    );
  }
  throw httpFailure(response.status);
}

/** 查询一个 Run 的持久化生命周期事实，并在交给状态机前校验完整响应。 */
export async function fetchChatRun(
  request: ChatRunDetailRequest,
  options: { readonly fetcher?: FetchLike } = {},
): Promise<ChatRunDetail> {
  const { threadId, runId } = validateRunAddress(request);
  let response: Response;
  try {
    response = await (options.fetcher ?? globalThis.fetch)(
      `/api/v1/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}`,
      {
        method: "GET",
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        ...(request.signal === undefined ? {} : { signal: request.signal }),
      },
    );
  } catch (error) {
    throw normalizeClientError(error, request.signal);
  }

  if (!response.ok) {
    await cancelResponseBody(response);
    if (response.status === 404) {
      throw new ChatStreamClientError(
        "run_not_found",
        "需要核对的 Run 不存在",
        { retryable: false, status: response.status },
      );
    }
    throw httpFailure(response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    invalidRunResponse("Run 详情不是有效 JSON");
  }
  return parseChatRunDetail(body, { threadId, runId });
}

function isTerminalRunStatus(status: ChatRunStatus): boolean {
  return status !== "pending" && status !== "running";
}

function waitForRetry(
  milliseconds: number,
  signal: AbortSignal | undefined,
): Promise<void> {
  if (milliseconds === 0) {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    if (signal?.aborted === true) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    const onAbort = () => {
      globalThis.clearTimeout(timer);
      reject(new DOMException("aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function createReconciliationSignal(
  parentSignal: AbortSignal | undefined,
  timeoutMilliseconds: number,
): { readonly signal: AbortSignal; readonly dispose: () => void } {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (parentSignal?.aborted === true) {
    abort();
  } else {
    parentSignal?.addEventListener("abort", abort, { once: true });
  }
  const timer = globalThis.setTimeout(abort, timeoutMilliseconds);
  return {
    signal: controller.signal,
    dispose: () => {
      globalThis.clearTimeout(timer);
      parentSignal?.removeEventListener("abort", abort);
    },
  };
}

/**
 * 断线后短暂等待服务端把取消竞争物化为终态；预算耗尽时返回最后一次活动快照。
 * 这里只核对状态，不恢复或伪造缺失的 SSE 业务事件。
 */
export async function reconcileChatRunAfterDisconnect(
  request: ChatRunDetailRequest,
  options: {
    readonly fetcher?: FetchLike;
    readonly maxAttempts?: number;
    readonly retryDelayMilliseconds?: number;
    readonly timeoutMilliseconds?: number;
  } = {},
): Promise<ChatRunDetail> {
  const maxAttempts =
    options.maxAttempts ?? DEFAULT_RUN_RECONCILIATION_ATTEMPTS;
  const retryDelayMilliseconds =
    options.retryDelayMilliseconds ??
    DEFAULT_RUN_RECONCILIATION_DELAY_MILLISECONDS;
  const timeoutMilliseconds =
    options.timeoutMilliseconds ??
    DEFAULT_RUN_RECONCILIATION_TIMEOUT_MILLISECONDS;
  if (
    !Number.isSafeInteger(maxAttempts) ||
    maxAttempts < 1 ||
    !Number.isSafeInteger(retryDelayMilliseconds) ||
    retryDelayMilliseconds < 0 ||
    !Number.isSafeInteger(timeoutMilliseconds) ||
    timeoutMilliseconds < 1
  ) {
    throw new ChatStreamClientError("invalid_request", "Run 状态核对预算无效", {
      retryable: false,
    });
  }

  const reconciliation = createReconciliationSignal(
    request.signal,
    timeoutMilliseconds,
  );
  try {
    let latest: ChatRunDetail | null = null;
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      latest = await fetchChatRun(
        { ...request, signal: reconciliation.signal },
        {
          ...(options.fetcher === undefined
            ? {}
            : { fetcher: options.fetcher }),
        },
      );
      if (isTerminalRunStatus(latest.status) || attempt === maxAttempts) {
        return latest;
      }
      await waitForRetry(retryDelayMilliseconds, reconciliation.signal);
    }

    // maxAttempts 已限制为至少 1；该分支只用于保持类型系统完整。
    throw new ChatStreamClientError(
      "invalid_run_response",
      "Run 状态核对没有产生结果",
      { retryable: false },
    );
  } catch (error) {
    throw normalizeClientError(error, reconciliation.signal);
  } finally {
    reconciliation.dispose();
  }
}

/**
 * 启动一次版本化 Agent run，并逐条产生已经通过运行时校验的领域事件。
 * 该模块只负责编排 HTTP/SSE 边界，不保存消息，也不依赖 React。
 */
export async function* streamChatRun(
  request: ChatStreamRequest,
  options: ChatStreamClientOptions = {},
): AsyncGenerator<ChatRunEvent> {
  const validated = validateRequest(request);
  const inactivityTimeoutMilliseconds = resolveInactivityTimeout(
    options.inactivityTimeoutMilliseconds,
  );
  const fetcher = options.fetcher ?? globalThis.fetch;
  const threadEndpoint = `/api/v1/threads/${encodeURIComponent(
    validated.threadId,
  )}`;
  const endpoint =
    validated.goalResumeRevision === null
      ? `${threadEndpoint}/runs/stream`
      : `${threadEndpoint}/goal/resume`;

  let response: Response;
  try {
    response = await fetcher(endpoint, {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(
        validated.goalResumeRevision === null
          ? {
              message_id: validated.messageId,
              message: validated.message,
              ...(validated.attachments.length > 0
                ? { attachments: validated.attachments }
                : {}),
              ...(validated.humanInputResponse === null
                ? {}
                : { human_input_response: validated.humanInputResponse }),
              ...(validated.benchmarkCaseId === null
                ? {}
                : { benchmark_case_id: validated.benchmarkCaseId }),
              ...(validated.skillInstallAuthorizationToken === null
                ? {}
                : {
                    skill_install_authorization_token:
                      validated.skillInstallAuthorizationToken,
                  }),
            }
          : {
              message_id: validated.messageId,
              revision: validated.goalResumeRevision,
            },
      ),
      credentials: "same-origin",
      cache: "no-store",
      ...(request.signal === undefined ? {} : { signal: request.signal }),
    });
  } catch (error) {
    throw normalizeClientError(error, request.signal);
  }

  if (!response.ok) {
    await cancelResponseBody(response);
    throw httpFailure(response.status);
  }

  const mediaType =
    response.headers
      .get("content-type")
      ?.split(";", 1)[0]
      ?.trim()
      .toLowerCase() ?? "";
  if (mediaType !== "text/event-stream") {
    await cancelResponseBody(response);
    throw new ChatStreamClientError(
      "invalid_content_type",
      "后端没有返回 SSE 事件流",
      { retryable: false, status: response.status },
    );
  }
  if (response.body === null) {
    throw new ChatStreamClientError(
      "missing_response_body",
      "后端返回了空的事件流响应",
      { retryable: true, status: response.status },
    );
  }

  const responseRunId = response.headers.get("x-run-id")?.trim().toLowerCase();
  if (responseRunId === undefined || !UUID_PATTERN.test(responseRunId)) {
    await cancelResponseBody(response);
    throw new ChatStreamClientError(
      "missing_run_id",
      "后端响应缺少有效的 run ID",
      { retryable: false, status: response.status },
    );
  }
  // 响应头先于第一条 SSE 到达，停止按钮因此可以在 connecting 窗口定位服务端 Run。
  request.onRunId?.(responseRunId);

  let sawEvent = false;
  let sawTerminalEvent = false;
  try {
    for await (const frame of parseSseStream(response.body, {
      inactivityTimeoutMilliseconds,
    })) {
      if (sawTerminalEvent) {
        throw new ChatStreamClientError(
          "stream_protocol_error",
          "run 终止后仍收到新的事件",
          { retryable: false },
        );
      }

      const event = decodeChatRunEvent(frame);
      if (event.runId.toLowerCase() !== responseRunId) {
        throw new ChatStreamClientError(
          "stream_protocol_error",
          "响应头 run ID 与事件 run ID 不一致",
          { retryable: false },
        );
      }
      if (event.threadId.toLowerCase() !== validated.threadId) {
        throw new ChatStreamClientError(
          "stream_protocol_error",
          "事件不属于请求的聊天线程",
          { retryable: false },
        );
      }

      sawEvent = true;
      sawTerminalEvent = isTerminalEvent(event);
      yield event;
    }

    if (!sawEvent || !sawTerminalEvent) {
      throw new ChatStreamClientError(
        "incomplete_stream",
        "Agent 事件流在终止事件之前结束",
        { retryable: true },
      );
    }
  } catch (error) {
    throw normalizeClientError(error, request.signal);
  }
}
