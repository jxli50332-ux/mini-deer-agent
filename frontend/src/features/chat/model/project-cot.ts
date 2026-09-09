import type { ChatTimelineItem } from "@/entities/message/model/types";
import { parseWebSearchResult } from "@/entities/search/model/web-search-result";
import { parseTodoList } from "@/entities/todo/model/todo-list";
import { parseWebFetchResult } from "@/entities/web-page/model/web-fetch-result";

export type CotStepKind = "reasoning" | "message" | "tool";
export type SubagentDisplayStatus =
  "pending" | "running" | "completed" | "failed" | "cancelled" | "timed_out";

export interface SubagentStepDetail {
  readonly name: string;
  readonly description: string | null;
  readonly status: SubagentDisplayStatus;
  readonly durationMs: number | null;
  readonly stopReason: string | null;
  readonly totalTokens: number | null;
  readonly modelCalls: number | null;
  readonly resultSummary: string | null;
  readonly rawResult: string | null;
}
export type CotStepIcon =
  | "reasoning"
  | "message"
  | "search"
  | "web"
  | "todo"
  | "file"
  | "task"
  | "tool";

export interface CotStepLink {
  readonly label: string;
  readonly url: string;
}

export interface CotStep {
  readonly id: string;
  readonly kind: CotStepKind;
  readonly icon: CotStepIcon;
  readonly text: string;
  readonly toolName?: string;
  readonly status?: SubagentDisplayStatus;
  readonly detail?: string;
  readonly links?: readonly CotStepLink[];
  readonly todoContents?: readonly string[];
  readonly subagent?: SubagentStepDetail;
}

type UnknownRecord = Record<string, unknown>;

function parseObject(value: string): UnknownRecord | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    return typeof parsed === "object" &&
      parsed !== null &&
      !Array.isArray(parsed)
      ? (parsed as UnknownRecord)
      : null;
  } catch {
    return null;
  }
}

function stringValue(
  value: UnknownRecord | null,
  ...keys: readonly string[]
): string | null {
  for (const key of keys) {
    const candidate = value?.[key];
    if (typeof candidate === "string" && candidate.trim().length > 0) {
      return candidate.trim();
    }
  }
  return null;
}

function compactText(value: string, maxLength = 96): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length > maxLength
    ? `${normalized.slice(0, maxLength)}…`
    : normalized;
}

function nonnegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : null;
}

function taskDisplayStatus(
  itemStatus: Extract<ChatTimelineItem, { kind: "tool" }>["status"],
  result: UnknownRecord | null,
): SubagentDisplayStatus {
  if (itemStatus === "pending") return "running";
  if (itemStatus === "cancelled") return "cancelled";
  const status = result?.status;
  if (
    status === "pending" ||
    status === "running" ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "timed_out"
  ) {
    return status;
  }
  return itemStatus === "failed" ? "failed" : "completed";
}

function projectSubagent(
  item: Extract<ChatTimelineItem, { kind: "tool" }>,
  input: UnknownRecord | null,
): SubagentStepDetail {
  const result = item.result === null ? null : parseObject(item.result);
  const usage =
    result?.usage !== null &&
    typeof result?.usage === "object" &&
    !Array.isArray(result.usage)
      ? (result.usage as UnknownRecord)
      : null;
  const name =
    stringValue(result, "subagent_type") ??
    stringValue(input, "subagent_type") ??
    "未知 Agent";
  const description =
    stringValue(result, "description") ?? stringValue(input, "description");
  const resultText = stringValue(result, "result", "last_result", "message");
  return {
    name,
    description,
    status: taskDisplayStatus(item.status, result),
    durationMs: nonnegativeInteger(result?.duration_ms),
    stopReason: stringValue(result, "stop_reason"),
    totalTokens: nonnegativeInteger(usage?.total_tokens),
    modelCalls: nonnegativeInteger(usage?.model_calls),
    resultSummary: resultText === null ? null : compactText(resultText, 240),
    rawResult: item.result,
  };
}

function toolStep(item: Extract<ChatTimelineItem, { kind: "tool" }>): CotStep {
  const name = item.name ?? "未知工具";
  const input = parseObject(item.input);
  const description = stringValue(input, "description");
  const base = {
    id: item.id,
    kind: "tool" as const,
    toolName: name,
    status: item.status,
  };

  if (name === "web_search") {
    const result =
      item.result === null ? null : parseWebSearchResult(item.result);
    const query = stringValue(input, "query") ?? result?.query ?? null;
    return {
      ...base,
      icon: "search",
      text: query === null ? "搜索网页" : `搜索“${compactText(query, 64)}”`,
      ...(result?.error === null || result?.error === undefined
        ? {}
        : { detail: result.error }),
      ...(result === null || result.sources.length === 0
        ? {}
        : {
            links: result.sources.map((source) => ({
              label: source.title,
              url: source.url,
            })),
          }),
    };
  }

  if (name === "web_fetch") {
    const result =
      item.result === null ? null : parseWebFetchResult(item.result);
    const requestedUrl = stringValue(input, "url");
    return {
      ...base,
      icon: "web",
      text: description ?? "读取网页",
      ...(result?.error === null || result?.error === undefined
        ? {}
        : { detail: result.error }),
      ...(result === null
        ? requestedUrl === null
          ? {}
          : { detail: compactText(requestedUrl) }
        : {
            links: [{ label: result.title, url: result.url }],
          }),
    };
  }

  if (name === "write_todos") {
    const todoList = item.result === null ? null : parseTodoList(item.result);
    return {
      ...base,
      icon: "todo",
      text: "更新任务清单",
      ...(todoList === null
        ? {}
        : { todoContents: todoList.items.map((todo) => todo.content) }),
    };
  }

  if (name === "task") {
    const subagent = projectSubagent(item, input);
    return {
      ...base,
      icon: "task",
      status: subagent.status,
      text: `${subagent.name}：${subagent.description ?? "委派子任务"}`,
      subagent,
    };
  }

  if (
    name === "list_files" ||
    name === "glob_files" ||
    name === "search_files" ||
    name === "read_file" ||
    name === "delete_file" ||
    name === "move_file" ||
    name === "rename_file" ||
    name === "create_directory" ||
    name === "create_file" ||
    name === "write_file" ||
    name === "str_replace"
  ) {
    const path = stringValue(input, "path", "file_path");
    const pattern = stringValue(input, "pattern");
    const query = stringValue(input, "query");
    const newPath = stringValue(input, "new_path");
    const action =
      name === "list_files"
        ? "浏览文件"
        : name === "glob_files"
          ? pattern === null
            ? "查找文件"
            : `查找文件：${compactText(pattern, 64)}`
          : name === "search_files"
            ? query === null
              ? "搜索文件正文"
              : `搜索正文：${compactText(query, 64)}`
            : name === "read_file"
              ? "读取文件"
              : name === "create_file"
                ? "创建文件"
                : name === "create_directory"
                  ? "创建目录"
                  : name === "rename_file"
                    ? "重命名文件"
                    : name === "move_file"
                      ? "移动文件"
                      : name === "delete_file"
                        ? "删除文件"
                        : "更新文件";
    return {
      ...base,
      icon: "file",
      text: description ?? action,
      ...(path === null
        ? {}
        : {
            detail:
              name === "move_file" && newPath !== null
                ? `${compactText(path, 64)} → ${compactText(newPath, 64)}`
                : compactText(path, 140),
          }),
    };
  }

  if (name === "get_weather") {
    const city = stringValue(input, "city", "location");
    return {
      ...base,
      icon: "tool",
      text: city === null ? "查询天气" : `查询 ${compactText(city, 48)} 天气`,
    };
  }

  if (name === "inspect_execution_environment") {
    const result = item.result === null ? null : parseObject(item.result);
    const verifyLifecycle = input?.verify_lifecycle === true;
    const available = result?.available;
    const lifecycleReady = result?.lifecycle_ready;
    const serverVersion = stringValue(result, "server_version");
    const message = stringValue(result, "message");
    return {
      ...base,
      icon: "tool",
      text: verifyLifecycle ? "验证沙箱生命周期" : "检查执行环境",
      ...(lifecycleReady === true
        ? { detail: "Docker 临时容器已创建并销毁" }
        : verifyLifecycle && lifecycleReady === false && message !== null
          ? { detail: message }
          : available === true
            ? {
                detail:
                  serverVersion === null
                    ? "Docker 隔离环境可用"
                    : `Docker ${compactText(serverVersion, 32)} 可用`,
              }
            : available === false && message !== null
              ? { detail: message }
              : {}),
    };
  }

  if (name === "inspect_project_sandbox") {
    const result = item.result === null ? null : parseObject(item.result);
    const mountReady = result?.mount_ready;
    const entries = Array.isArray(result?.entries)
      ? result.entries.filter(
          (entry): entry is string => typeof entry === "string",
        )
      : [];
    const message = stringValue(result, "message");
    return {
      ...base,
      icon: "tool",
      text: "检查项目沙箱挂载",
      ...(mountReady === true
        ? {
            detail: `/workspace · ${entries.length} 个根条目 · 容器已销毁`,
          }
        : mountReady === false && message !== null
          ? { detail: message }
          : {}),
    };
  }

  if (name === "run_project_command") {
    const result = item.result === null ? null : parseObject(item.result);
    const command = stringValue(input, "command");
    const commandDescription = stringValue(input, "description");
    const timedOut = result?.timed_out === true;
    const timeoutSeconds =
      typeof result?.timeout_seconds === "number"
        ? result.timeout_seconds
        : typeof input?.timeout_seconds === "number"
          ? input.timeout_seconds
          : null;
    const exitCode =
      typeof result?.exit_code === "number" ? result.exit_code : null;
    const stdout = stringValue(result, "stdout");
    const stderr = stringValue(result, "stderr");
    const message = stringValue(result, "message");
    const detail = [
      command === null ? null : compactText(command, 72),
      timedOut
        ? timeoutSeconds === null
          ? "已超时"
          : `timeout ${timeoutSeconds}s`
        : exitCode === null
          ? null
          : `exit ${exitCode}`,
      stdout === null ? null : `stdout: ${compactText(stdout, 64)}`,
      stderr === null ? null : `stderr: ${compactText(stderr, 64)}`,
      timedOut && message !== null ? compactText(message, 72) : null,
    ]
      .filter((value): value is string => value !== null)
      .join(" · ");
    return {
      ...base,
      icon: "tool",
      text: commandDescription ?? "运行项目命令",
      ...(detail.length > 0
        ? { detail }
        : result?.command_completed === false && message !== null
          ? { detail: message }
          : {}),
    };
  }

  return {
    ...base,
    icon: "tool",
    text: description ?? `调用 ${name}`,
  };
}

/**
 * 将一轮中的 reasoning、中间文本和工具调用投影成统一步骤。
 * 最终 Assistant 的正文仍作为交付物单独展示，但它的 reasoning 属于 COT。
 */
export function projectCotSteps(
  items: readonly ChatTimelineItem[],
  finalAssistantMessageId: string | null,
): readonly CotStep[] {
  const steps: CotStep[] = [];

  for (const item of items) {
    if (item.kind === "tool") {
      steps.push(toolStep(item));
      continue;
    }
    if (item.role !== "assistant") {
      continue;
    }
    if (item.reasoning !== undefined && item.reasoning.trim().length > 0) {
      steps.push({
        id: `${item.id}:reasoning`,
        kind: "reasoning",
        icon: "reasoning",
        text: item.reasoning,
      });
    }
    if (item.id !== finalAssistantMessageId && item.content.trim().length > 0) {
      steps.push({
        id: `${item.id}:content`,
        kind: "message",
        icon: "message",
        text: item.content,
      });
    }
  }

  return steps;
}
