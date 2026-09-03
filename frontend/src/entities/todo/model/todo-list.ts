export type TodoStatus = "pending" | "in_progress" | "completed";

export interface TodoListItem {
  readonly content: string;
  readonly status: TodoStatus;
}

export interface TodoList {
  readonly items: readonly TodoListItem[];
}

export interface TodoSnapshot {
  readonly list: TodoList;
  readonly sourceToolItemId: string;
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** 校验 write_todos 工具结果 JSON；非法结构返回 null，让工具卡安全退回原始文本。 */
export function parseTodoList(value: string): TodoList | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value) as unknown;
  } catch {
    return null;
  }
  if (!isRecord(parsed) || !Array.isArray(parsed.todos)) {
    return null;
  }

  const items: TodoListItem[] = [];
  for (const candidate of parsed.todos) {
    if (!isRecord(candidate)) {
      continue;
    }
    const content =
      typeof candidate.content === "string" ? candidate.content.trim() : "";
    const status = candidate.status;
    if (
      content.length === 0 ||
      (status !== "pending" &&
        status !== "in_progress" &&
        status !== "completed")
    ) {
      continue;
    }
    items.push({ content, status });
  }

  return { items };
}

/** 从新到旧选择最近一份合法 Todo 快照，供输入框上方的线程级面板恢复状态。 */
export function selectLatestTodoList(
  timeline: readonly ChatTimelineItem[],
): TodoList | null {
  return selectLatestTodoSnapshot(timeline)?.list ?? null;
}

/** 保留 Todo 来源工具步骤，供清单与 COT 在界面中互相定位。 */
export function selectLatestTodoSnapshot(
  timeline: readonly ChatTimelineItem[],
): TodoSnapshot | null {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const item = timeline[index];
    if (
      item?.kind !== "tool" ||
      item.name !== "write_todos" ||
      item.result === null
    ) {
      continue;
    }
    const todoList = parseTodoList(item.result);
    if (todoList !== null) {
      return { list: todoList, sourceToolItemId: item.id };
    }
  }
  return null;
}
import type { ChatTimelineItem } from "@/entities/message/model/types";
