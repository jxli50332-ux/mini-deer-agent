import { parseFilePage, type FilePage } from "@/entities/project/model/file";
import {
  parseDirectory,
  type DirectoryPage,
} from "@/entities/project/model/directory";
import {
  parseProject,
  parseProjectPage,
  ProjectPayloadError,
  type ProjectPage,
  type ProjectSummary,
} from "@/entities/project/model/types";
import type { ThreadSummary } from "@/entities/thread/model/types";
import {
  parseThreadList,
  parseThreadSummary,
} from "@/features/threads/api/thread-list";

interface ProjectAccess {
  readonly signal?: AbortSignal;
}
interface RequestOptions {
  readonly fetcher?: typeof globalThis.fetch;
}

/** 稳定错误类型只含安全说明，不保留路径或未知响应正文。 */
export class ProjectClientError extends Error {
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ProjectClientError";
  }
}

/** 区分权限、配置和登记冲突；不直接渲染后端错误正文。 */
function httpError(
  status: number,
  operation:
    "query" | "register" | "unregister" | "project_thread" | "directory",
): ProjectClientError {
  if (status === 403)
    return new ProjectClientError(
      "access_denied",
      "本地项目请求被拒绝，请检查访问地址。",
    );
  if (status === 503)
    return new ProjectClientError(
      "not_configured",
      "请先在后端配置允许访问的项目目录。",
    );
  if (operation === "directory" && [400, 404, 409, 422].includes(status))
    return new ProjectClientError(
      "directory_unavailable",
      "目录已变化、被忽略或无法访问，请刷新项目后重试。",
    );
  if (status === 404 && operation === "project_thread")
    return new ProjectClientError(
      "project_not_found",
      "项目已经解除登记，请刷新项目列表。",
    );
  if (status === 409 && operation === "project_thread")
    return new ProjectClientError(
      "thread_conflict",
      "无法创建项目会话：项目当前不可用，或该会话身份已经被占用。",
    );
  if (status === 409)
    return new ProjectClientError(
      "duplicate",
      "该目录已登记，请刷新列表查看已有项目。",
    );
  if (status === 400 || status === 422)
    return new ProjectClientError(
      "invalid_request",
      "登记被拒绝，请检查名称、目录是否存在，以及是否位于允许范围内。",
    );
  return new ProjectClientError(
    "unavailable",
    "项目服务暂时不可用，请稍后重试。",
  );
}

/** 请求始终同源、禁止重定向并设置超时；变更失败不自动重发。 */
async function requestProject<T>(
  path: string,
  access: ProjectAccess,
  method: "GET" | "POST" | "DELETE",
  body: object | undefined,
  parse: (value: unknown) => T,
  options: RequestOptions,
  expectedStatus: number,
  operation:
    "query" | "register" | "unregister" | "project_thread" | "directory",
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  access.signal?.addEventListener("abort", abort, { once: true });
  if (access.signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 15000);
  try {
    const response = await (options.fetcher ?? globalThis.fetch)(path, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
      await response.body?.cancel();
      throw httpError(response.status, operation);
    }
    // 变更必须符合精确状态码；DELETE 204 无 JSON 正文，不能误判为解析失败。
    if (response.status !== expectedStatus) throw new ProjectPayloadError();
    return parse(method === "DELETE" ? undefined : await response.json());
  } catch (error) {
    if (error instanceof ProjectClientError) throw error;
    if (access.signal?.aborted)
      throw new ProjectClientError("aborted", "项目请求已结束。");
    if (error instanceof ProjectPayloadError || error instanceof SyntaxError) {
      throw new ProjectClientError(
        "invalid_response",
        operation === "query" || method === "GET"
          ? "项目响应格式无效，请检查后端服务。"
          : operation === "project_thread"
            ? "项目会话创建响应无法确认，请刷新项目会话核对结果。"
            : `${method === "DELETE" ? "解除登记" : "登记"}响应无法确认，请先刷新项目列表核对结果。`,
      );
    }
    throw new ProjectClientError(
      method === "GET" ? "unavailable" : "unconfirmed",
      method === "GET"
        ? "无法加载项目，请检查后端连接后重试。"
        : operation === "project_thread"
          ? "项目会话创建结果尚未确认，请刷新项目会话核对，避免重复提交。"
          : `${method === "DELETE" ? "解除登记" : "登记"}结果尚未确认，请先刷新项目列表核对，避免重复提交。`,
    );
  } finally {
    clearTimeout(timer);
    access.signal?.removeEventListener("abort", abort);
  }
}

/** 使用服务器分页读取登记，每次只请求固定上限的元数据。 */
export function fetchProjects(
  request: ProjectAccess & { readonly offset?: number },
  options: RequestOptions = {},
): Promise<ProjectPage> {
  const offset = request.offset ?? 0;
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 10000) {
    return Promise.reject(
      new ProjectClientError("invalid_request", "项目分页参数无效。"),
    );
  }
  return requestProject(
    `/api/v1/projects?limit=20&offset=${offset}`,
    request,
    "GET",
    undefined,
    (value) => parseProjectPage(value, offset),
    options,
    200,
    "query",
  );
}

/** 仅提交用户填写的名称和根路径，不允许客户端修改权限或身份。 */
export function registerProject(
  request: ProjectAccess & { readonly name: string; readonly rootPath: string },
  options: RequestOptions = {},
): Promise<ProjectSummary> {
  const name = request.name.trim();
  const rootPath = request.rootPath.trim();
  if (
    name.length < 1 ||
    name.length > 80 ||
    rootPath.length < 1 ||
    rootPath.length > 4096
  ) {
    return Promise.reject(
      new ProjectClientError(
        "invalid_request",
        "请填写有效的项目名称和绝对目录。",
      ),
    );
  }
  return requestProject(
    "/api/v1/projects",
    request,
    "POST",
    { name, root_path: rootPath },
    parseProject,
    options,
    201,
    "register",
  );
}

/** 触发本机原生目录选择器；204 表示用户取消，不把取消显示成错误。 */
export async function pickProjectDirectory(
  request: ProjectAccess,
  options: RequestOptions = {},
): Promise<ProjectSummary | null> {
  try {
    const response = await (options.fetcher ?? globalThis.fetch)(
      "/api/v1/projects/pick-directory",
      {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        ...(request.signal === undefined ? {} : { signal: request.signal }),
        headers: { Accept: "application/json" },
      },
    );
    if (response.status === 204) return null;
    if (!response.ok) {
      await response.body?.cancel();
      throw httpError(response.status, "register");
    }
    if (response.status !== 201) throw new ProjectPayloadError();
    return parseProject(await response.json());
  } catch (error) {
    if (error instanceof ProjectClientError) throw error;
    if (request.signal?.aborted)
      throw new ProjectClientError("aborted", "文件夹选择已结束。");
    if (error instanceof ProjectPayloadError || error instanceof SyntaxError) {
      throw new ProjectClientError(
        "invalid_response",
        "文件夹登记响应无法确认，请刷新项目列表核对结果。",
      );
    }
    throw new ProjectClientError(
      "unconfirmed",
      "文件夹登记结果尚未确认，请刷新项目列表核对，避免重复登记。",
    );
  }
}

/** 仅按已登记身份解除关联，不发送目录或任何文件删除参数。 */
export function unregisterProject(
  request: ProjectAccess & { readonly projectId: string },
  options: RequestOptions = {},
): Promise<void> {
  if (
    !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(request.projectId)
  ) {
    return Promise.reject(
      new ProjectClientError(
        "invalid_request",
        "项目身份无效，请刷新项目列表。",
      ),
    );
  }
  return requestProject(
    `/api/v1/projects/${request.projectId}`,
    request,
    "DELETE",
    undefined,
    () => undefined,
    options,
    204,
    "unregister",
  );
}

function validUuid(value: string): boolean {
  return /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
}

/** 读取指定项目的持久会话归属，普通聊天和其他项目不会进入结果。 */
export function fetchProjectThreads(
  request: ProjectAccess & {
    readonly projectId: string;
    readonly limit?: number;
    readonly offset?: number;
  },
  options: RequestOptions = {},
): Promise<readonly ThreadSummary[]> {
  if (!validUuid(request.projectId)) {
    return Promise.reject(
      new ProjectClientError(
        "invalid_request",
        "项目身份无效，请刷新项目列表。",
      ),
    );
  }
  const limit = request.limit ?? 50;
  const offset = request.offset ?? 0;
  if (
    !Number.isSafeInteger(limit) ||
    limit < 1 ||
    limit > 100 ||
    !Number.isSafeInteger(offset) ||
    offset < 0 ||
    offset > 1_000_000
  ) {
    return Promise.reject(
      new ProjectClientError("invalid_request", "项目会话分页参数无效。"),
    );
  }
  return requestProject(
    `/api/v1/projects/${request.projectId}/threads?${new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    })}`,
    request,
    "GET",
    undefined,
    (value) => {
      try {
        const threads = parseThreadList(value);
        if (
          threads.some(
            (thread) => thread.projectId !== request.projectId.toLowerCase(),
          )
        ) {
          throw new ProjectPayloadError();
        }
        return threads;
      } catch {
        throw new ProjectPayloadError();
      }
    },
    options,
    200,
    "project_thread",
  );
}

/** 客户端提供稳定 UUID；只有服务端确认归属后页面才切换到新会话。 */
export function createProjectThread(
  request: ProjectAccess & {
    readonly projectId: string;
    readonly threadId: string;
  },
  options: RequestOptions = {},
): Promise<ThreadSummary> {
  if (!validUuid(request.projectId) || !validUuid(request.threadId)) {
    return Promise.reject(
      new ProjectClientError(
        "invalid_request",
        "项目或会话身份无效，请刷新后重试。",
      ),
    );
  }
  return requestProject(
    `/api/v1/projects/${request.projectId}/threads`,
    request,
    "POST",
    { thread_id: request.threadId },
    (value) => {
      try {
        const thread = parseThreadSummary(value);
        if (
          thread.threadId !== request.threadId.toLowerCase() ||
          thread.projectId !== request.projectId.toLowerCase()
        ) {
          throw new ProjectPayloadError();
        }
        return thread;
      } catch {
        throw new ProjectPayloadError();
      }
    },
    options,
    200,
    "project_thread",
  );
}

/** 复用同源、超时与禁止重定向策略，目录查询不读取文件正文。 */
export function fetchProjectDirectory(
  request: ProjectAccess & {
    readonly projectId: string;
    readonly path: string;
  },
  options: RequestOptions = {},
): Promise<DirectoryPage> {
  if (!validUuid(request.projectId))
    return Promise.reject(new ProjectPayloadError());
  return requestProject(
    `/api/v1/projects/${request.projectId}/directory?${new URLSearchParams({ path: request.path })}`,
    request,
    "GET",
    undefined,
    (value) => parseDirectory(value, request.projectId, request.path),
    options,
    200,
    "directory",
  );
}

/** 按行请求只读源码；复用工作区门禁与不缓存策略。 */
export function fetchProjectFile(
  request: ProjectAccess & {
    readonly projectId: string;
    readonly path: string;
    readonly startLine: number;
  },
  options: RequestOptions = {},
): Promise<FilePage> {
  if (
    !validUuid(request.projectId) ||
    !Number.isSafeInteger(request.startLine) ||
    request.startLine < 1
  )
    return Promise.reject(new ProjectPayloadError());
  return requestProject(
    `/api/v1/projects/${request.projectId}/file?${new URLSearchParams({ path: request.path, start_line: String(request.startLine) })}`,
    request,
    "GET",
    undefined,
    (value) =>
      parseFilePage(value, request.projectId, request.path, request.startLine),
    options,
    200,
    "directory",
  );
}
