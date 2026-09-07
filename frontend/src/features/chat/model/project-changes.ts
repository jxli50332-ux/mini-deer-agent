import type { ChatTimelineItem } from "@/entities/message/model/types";

export type ProjectChangeKind =
  | "created"
  | "modified"
  | "directory_created"
  | "renamed"
  | "moved"
  | "deleted";

export interface ProjectChange {
  readonly id: string;
  readonly kind: ProjectChangeKind;
  readonly path: string;
  readonly previousPath?: string;
  readonly diff?: ProjectChangeDiff;
}

export interface ProjectChangeDiff {
  readonly before?: string;
  readonly after?: string;
  readonly truncated: boolean;
}

export type ProjectCheckStatus =
  "running" | "passed" | "failed" | "timed_out" | "cancelled" | "unavailable";

export interface ProjectCheck {
  readonly id: string;
  readonly command: string;
  readonly status: ProjectCheckStatus;
  readonly exitCode?: number;
}

type UnknownRecord = Record<string, unknown>;

function parseObject(value: string | null): UnknownRecord | null {
  if (value === null) {
    return null;
  }
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

function text(record: UnknownRecord | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : null;
}

const MAX_DIFF_SIDE_CHARACTERS = 4000;

function diffText(value: unknown): { text: string; truncated: boolean } | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.replace(/\r\n?/g, "\n");
  return {
    text: normalized.slice(0, MAX_DIFF_SIDE_CHARACTERS),
    truncated: normalized.length > MAX_DIFF_SIDE_CHARACTERS,
  };
}

function changeDiff(
  name: string,
  input: UnknownRecord | null,
  result: UnknownRecord,
): ProjectChangeDiff | null {
  if (name === "create_file") {
    const after = diffText(input?.content);
    return after === null
      ? null
      : { after: after.text, truncated: after.truncated };
  }
  if (name === "delete_file") {
    const before = diffText(result.deleted_content_preview);
    return before === null
      ? null
      : {
          before: before.text,
          truncated:
            result.deleted_content_truncated === true || before.truncated,
        };
  }
  let beforeValue: unknown;
  let afterValue: unknown;
  let resultTruncated = false;
  if (name === "str_replace") {
    beforeValue = input?.old_str;
    afterValue = input?.new_str;
  } else if (name === "write_file") {
    beforeValue = result.previous_content_preview;
    afterValue = input?.content;
    resultTruncated = result.previous_content_truncated === true;
  } else {
    return null;
  }
  const before = diffText(beforeValue);
  const after = diffText(afterValue);
  if (before === null || after === null) {
    return null;
  }
  return {
    before: before.text,
    after: after.text,
    truncated: resultTruncated || before.truncated || after.truncated,
  };
}

function actualChange(
  name: string,
  result: UnknownRecord,
): ProjectChangeKind | null {
  if (result.ok !== true) {
    return null;
  }
  if (name === "create_file" && result.created === true) {
    return "created";
  }
  if (name === "create_directory" && result.created === true) {
    return "directory_created";
  }
  if (name === "str_replace" && result.replaced === true) {
    return "modified";
  }
  if (
    name === "write_file" &&
    result.written === true &&
    result.changed === true
  ) {
    return "modified";
  }
  if (name === "rename_file" && result.renamed === true) {
    return "renamed";
  }
  if (name === "move_file" && result.moved === true) {
    return "moved";
  }
  if (name === "delete_file" && result.deleted === true) {
    return "deleted";
  }
  return null;
}

/** 从持久化工具时间线中投影一轮内真正发生的文件变化。 */
export function projectChanges(
  items: readonly ChatTimelineItem[],
): readonly ProjectChange[] {
  const changes: ProjectChange[] = [];
  for (const item of items) {
    if (
      item.kind !== "tool" ||
      item.status !== "completed" ||
      item.name === null
    ) {
      continue;
    }
    const result = parseObject(item.result);
    if (result === null) {
      continue;
    }
    const kind = actualChange(item.name, result);
    const path = text(result, "path");
    if (kind === null || path === null) {
      continue;
    }
    const previousPath = text(result, "previous_path");
    const diff = changeDiff(item.name, parseObject(item.input), result);
    changes.push({
      id: item.id,
      kind,
      path,
      ...(previousPath === null ? {} : { previousPath }),
      ...(diff === null ? {} : { diff }),
    });
  }
  return changes;
}

/** 从同一持久化工具时间线投影真实项目命令及其终态。 */
export function projectChecks(
  items: readonly ChatTimelineItem[],
): readonly ProjectCheck[] {
  const checks: ProjectCheck[] = [];
  for (const item of items) {
    if (item.kind !== "tool" || item.name !== "run_project_command") {
      continue;
    }
    const input = parseObject(item.input);
    const command = text(input, "command");
    if (command === null) {
      continue;
    }
    if (item.status === "pending") {
      checks.push({ id: item.id, command, status: "running" });
      continue;
    }
    if (item.status === "cancelled") {
      checks.push({ id: item.id, command, status: "cancelled" });
      continue;
    }
    if (item.status === "failed") {
      checks.push({ id: item.id, command, status: "failed" });
      continue;
    }
    const result = parseObject(item.result);
    const exitCode = result?.exit_code;
    if (typeof exitCode === "number" && Number.isInteger(exitCode)) {
      checks.push({
        id: item.id,
        command,
        status: exitCode === 0 ? "passed" : "failed",
        exitCode,
      });
    } else {
      checks.push({
        id: item.id,
        command,
        status: result?.timed_out === true ? "timed_out" : "unavailable",
      });
    }
  }
  return checks;
}

const PROJECT_TREE_CHANGE_KINDS: ReadonlySet<ProjectChangeKind> = new Set([
  "created",
  "directory_created",
  "renamed",
  "moved",
  "deleted",
]);

/** 判断一个已完成工具结果是否真实改变目录结构。 */
export function projectToolResultChangesTree(
  name: string | null,
  resultText: string,
): boolean {
  if (name === null) {
    return false;
  }
  const result = parseObject(resultText);
  if (result === null) {
    return false;
  }
  const kind = actualChange(name, result);
  return kind !== null && PROJECT_TREE_CHANGE_KINDS.has(kind);
}
