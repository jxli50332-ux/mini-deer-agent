import type { ChatTimelineItem } from "@/entities/message/model/types";
import { parseWebSearchResult } from "@/entities/search/model/web-search-result";
import { parseTodoList } from "@/entities/todo/model/todo-list";
import { parseWebFetchResult } from "@/entities/web-page/model/web-fetch-result";

export type CotStepKind = "reasoning" | "message" | "tool";
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
  readonly status?: "pending" | "completed" | "failed" | "cancelled";
  readonly detail?: string;
  readonly links?: readonly CotStepLink[];
  readonly todoContents?: readonly string[];
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
    const taskDescription = stringValue(input, "description", "prompt");
    return {
      ...base,
      icon: "task",
      text:
        taskDescription === null
          ? "委派子任务"
          : `委派子任务：${compactText(taskDescription)}`,
    };
  }

  if (name === "read_file" || name === "write_file" || name === "str_replace") {
    const path = stringValue(input, "path", "file_path");
    const action = name === "read_file" ? "读取文件" : "更新文件";
    return {
      ...base,
      icon: "file",
      text: description ?? action,
      ...(path === null ? {} : { detail: compactText(path, 140) }),
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
