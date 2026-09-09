const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type UnknownRecord = Record<string, unknown>;

export type GoalBlocker =
  | "none"
  | "missing_evidence"
  | "needs_user_input"
  | "run_failed"
  | "external_wait"
  | "goal_not_met_yet";

export type GoalStatus = "active" | "paused" | "stopped" | "completed";

export interface GoalEvaluation {
  readonly satisfied: boolean;
  readonly blocker: GoalBlocker;
  readonly reason: string;
  readonly evidenceSummary: string;
  readonly evaluatedAt: string;
}

export interface ThreadGoal {
  readonly version: 1;
  readonly revision: string;
  readonly objective: string;
  readonly continuationCount: number;
  readonly maxContinuations: number;
  readonly noProgressCount: number;
  readonly lastEvaluation: GoalEvaluation | null;
  readonly status: GoalStatus;
  readonly stopReason: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface GoalRequest {
  readonly threadId: string;
  readonly signal?: AbortSignal;
}

export interface SetGoalRequest extends GoalRequest {
  readonly objective: string;
  readonly maxContinuations: number;
  readonly expectedRevision?: string;
}

export interface GoalMutationRequest extends GoalRequest {
  readonly revision: string;
}

export type GoalLoader = (request: GoalRequest) => Promise<ThreadGoal | null>;
export type GoalSetter = (request: SetGoalRequest) => Promise<ThreadGoal>;
export type GoalStopper = (request: GoalMutationRequest) => Promise<ThreadGoal>;
export type GoalClearer = (request: GoalMutationRequest) => Promise<void>;
export type GoalFetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export class GoalClientError extends Error {
  readonly code:
    | "invalid_request"
    | "http_error"
    | "invalid_response"
    | "network_error"
    | "aborted"
    | "thread_not_found";
  readonly retryable: boolean;

  constructor(
    code: GoalClientError["code"],
    message: string,
    retryable: boolean,
  ) {
    super(message);
    this.name = "GoalClientError";
    this.code = code;
    this.retryable = retryable;
  }
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalid(message: string): never {
  throw new GoalClientError("invalid_response", message, false);
}

function rejectUnknownFields(
  record: UnknownRecord,
  allowed: ReadonlySet<string>,
  label: string,
): void {
  if (Object.keys(record).some((field) => !allowed.has(field))) {
    invalid(`${label}包含未知字段`);
  }
}

const GOAL_FIELDS = new Set([
  "version",
  "revision",
  "objective",
  "continuation_count",
  "max_continuations",
  "no_progress_count",
  "last_evaluation",
  "status",
  "stop_reason",
  "created_at",
  "updated_at",
]);
const EVALUATION_FIELDS = new Set([
  "satisfied",
  "blocker",
  "reason",
  "evidence_summary",
  "evaluated_at",
]);

function requiredString(record: UnknownRecord, field: string): string {
  const value = record[field];
  if (typeof value !== "string" || value.length === 0) {
    invalid(`${field} 必须是非空字符串`);
  }
  return value;
}

function integer(record: UnknownRecord, field: string): number {
  const value = record[field];
  if (!Number.isSafeInteger(value) || Number(value) < 0) {
    invalid(`${field} 必须是非负整数`);
  }
  return Number(value);
}

function timestamp(record: UnknownRecord, field: string): string {
  const value = requiredString(record, field);
  if (Number.isNaN(Date.parse(value))) invalid(`${field} 必须是有效时间`);
  return value;
}

const BLOCKERS = new Set<GoalBlocker>([
  "none",
  "missing_evidence",
  "needs_user_input",
  "run_failed",
  "external_wait",
  "goal_not_met_yet",
]);

function parseEvaluation(value: unknown): GoalEvaluation | null {
  if (value === null) return null;
  if (!isRecord(value)) invalid("last_evaluation 必须是对象或 null");
  rejectUnknownFields(value, EVALUATION_FIELDS, "last_evaluation");
  const blocker = requiredString(value, "blocker");
  if (!BLOCKERS.has(blocker as GoalBlocker)) invalid("blocker 不受支持");
  if (typeof value.satisfied !== "boolean") invalid("satisfied 必须是布尔值");
  return {
    satisfied: value.satisfied,
    blocker: blocker as GoalBlocker,
    reason: requiredString(value, "reason"),
    evidenceSummary: requiredString(value, "evidence_summary"),
    evaluatedAt: timestamp(value, "evaluated_at"),
  };
}

export function parseThreadGoal(value: unknown): ThreadGoal {
  if (!isRecord(value)) invalid("Goal 响应必须是对象");
  rejectUnknownFields(value, GOAL_FIELDS, "Goal 响应");
  if (value.version !== 1) invalid("Goal version 不受支持");
  const revision = requiredString(value, "revision").toLowerCase();
  if (!UUID_PATTERN.test(revision)) invalid("Goal revision 必须是 UUID");
  const status = requiredString(value, "status");
  if (
    status !== "active" &&
    status !== "paused" &&
    status !== "stopped" &&
    status !== "completed"
  ) {
    invalid("Goal status 不受支持");
  }
  const stopReason = value.stop_reason;
  if (
    stopReason !== null &&
    (typeof stopReason !== "string" || stopReason.length === 0)
  ) {
    invalid("stop_reason 必须是非空字符串或 null");
  }
  const maxContinuations = integer(value, "max_continuations");
  if (maxContinuations < 1 || maxContinuations > 20) {
    invalid("max_continuations 超出范围");
  }
  const continuationCount = integer(value, "continuation_count");
  if (continuationCount > maxContinuations) {
    invalid("continuation_count 不能超过 max_continuations");
  }
  const lastEvaluation = parseEvaluation(value.last_evaluation);
  if (
    ((status === "active" || status === "completed") && stopReason !== null) ||
    ((status === "paused" || status === "stopped") && stopReason === null)
  ) {
    invalid("Goal status 与 stop_reason 不一致");
  }
  if (status === "completed" && lastEvaluation?.satisfied !== true) {
    invalid("已完成 Goal 必须包含满足条件的最近评估");
  }
  return {
    version: 1,
    revision,
    objective: requiredString(value, "objective"),
    continuationCount,
    maxContinuations,
    noProgressCount: integer(value, "no_progress_count"),
    lastEvaluation,
    status,
    stopReason,
    createdAt: timestamp(value, "created_at"),
    updatedAt: timestamp(value, "updated_at"),
  };
}

function validateThreadId(threadId: string): string {
  const normalized = threadId.toLowerCase();
  if (!UUID_PATTERN.test(normalized)) {
    throw new GoalClientError("invalid_request", "Thread ID 无效", false);
  }
  return normalized;
}

function validateRevision(revision: string): string {
  const normalized = revision.trim().toLowerCase();
  if (!UUID_PATTERN.test(normalized)) {
    throw new GoalClientError("invalid_request", "Goal revision 无效", false);
  }
  return normalized;
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

async function requestGoal(
  request: GoalRequest,
  init: RequestInit,
  fetcher: GoalFetchLike,
  allowMissing = false,
): Promise<ThreadGoal | null> {
  const threadId = validateThreadId(request.threadId);
  try {
    const response = await fetcher(`/api/v1/threads/${threadId}/goal`, {
      credentials: "same-origin",
      cache: "no-store",
      ...init,
      ...(request.signal === undefined ? {} : { signal: request.signal }),
    });
    if (allowMissing && response.status === 404) {
      let errorCode: string | null = null;
      try {
        const body = (await response.json()) as unknown;
        if (
          isRecord(body) &&
          isRecord(body.detail) &&
          typeof body.detail.code === "string"
        ) {
          errorCode = body.detail.code;
        }
      } catch {
        // 兼容旧后端的空 404；旧协议只表达“没有可展示的 Goal”。
      }
      if (errorCode === "thread_not_found") {
        throw new GoalClientError(
          "thread_not_found",
          "该对话尚未在服务端创建",
          false,
        );
      }
      if (errorCode === null || errorCode === "goal_not_found") return null;
      throw new GoalClientError("http_error", "Goal 请求失败", false);
    }
    if (!response.ok) {
      await response.body?.cancel();
      throw new GoalClientError(
        "http_error",
        response.status >= 500 ? "Goal 服务暂时不可用" : "Goal 请求失败",
        response.status >= 500,
      );
    }
    return parseThreadGoal(await response.json());
  } catch (error) {
    if (error instanceof GoalClientError) throw error;
    if (request.signal?.aborted === true || isAbortError(error)) {
      throw new GoalClientError("aborted", "Goal 请求已取消", false);
    }
    throw new GoalClientError("network_error", "无法连接 Goal 服务", true);
  }
}

export function fetchThreadGoal(
  request: GoalRequest,
  options: { readonly fetcher?: GoalFetchLike } = {},
): Promise<ThreadGoal | null> {
  return requestGoal(
    request,
    { method: "GET", headers: { Accept: "application/json" } },
    options.fetcher ?? globalThis.fetch,
    true,
  );
}

export async function setThreadGoal(
  request: SetGoalRequest,
  options: { readonly fetcher?: GoalFetchLike } = {},
): Promise<ThreadGoal> {
  const objective = request.objective.trim();
  if (!objective || objective.length > 4000) {
    throw new GoalClientError(
      "invalid_request",
      "目标内容必须为 1–4000 字",
      false,
    );
  }
  if (
    !Number.isSafeInteger(request.maxContinuations) ||
    request.maxContinuations < 1 ||
    request.maxContinuations > 20
  ) {
    throw new GoalClientError(
      "invalid_request",
      "最大续跑次数必须为 1–20",
      false,
    );
  }
  const expectedRevision =
    request.expectedRevision === undefined
      ? undefined
      : validateRevision(request.expectedRevision);
  const result = await requestGoal(
    request,
    {
      method: "PUT",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        objective,
        max_continuations: request.maxContinuations,
        ...(expectedRevision === undefined
          ? {}
          : { expected_revision: expectedRevision }),
      }),
    },
    options.fetcher ?? globalThis.fetch,
  );
  if (result === null) invalid("设置 Goal 未返回状态");
  return result;
}

export async function stopThreadGoal(
  request: GoalMutationRequest,
  options: { readonly fetcher?: GoalFetchLike } = {},
): Promise<ThreadGoal> {
  const threadId = validateThreadId(request.threadId);
  const revision = validateRevision(request.revision);
  const result = await requestGoal(
    request,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ revision }),
    },
    (_input, init) =>
      (options.fetcher ?? globalThis.fetch)(
        `/api/v1/threads/${threadId}/goal/stop`,
        init,
      ),
  );
  if (result === null) invalid("停止 Goal 未返回状态");
  return result;
}

export async function clearThreadGoal(
  request: GoalMutationRequest,
  options: { readonly fetcher?: GoalFetchLike } = {},
): Promise<void> {
  const threadId = validateThreadId(request.threadId);
  const revision = validateRevision(request.revision);
  try {
    const response = await (options.fetcher ?? globalThis.fetch)(
      `/api/v1/threads/${threadId}/goal?revision=${encodeURIComponent(
        revision,
      )}`,
      {
        method: "DELETE",
        credentials: "same-origin",
        cache: "no-store",
        ...(request.signal === undefined ? {} : { signal: request.signal }),
      },
    );
    if (!response.ok) {
      await response.body?.cancel();
      throw new GoalClientError(
        "http_error",
        "无法清除 Goal",
        response.status >= 500,
      );
    }
  } catch (error) {
    if (error instanceof GoalClientError) throw error;
    if (request.signal?.aborted === true || isAbortError(error)) {
      throw new GoalClientError("aborted", "Goal 请求已取消", false);
    }
    throw new GoalClientError("network_error", "无法连接 Goal 服务", true);
  }
}
