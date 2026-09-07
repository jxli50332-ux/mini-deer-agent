import { ProjectPayloadError } from "./types";

export interface DirectoryEntry {
  readonly name: string;
  readonly path: string;
  readonly kind: "directory" | "file" | "unknown";
  readonly status: "available" | "ignored" | "unavailable";
}
export interface DirectoryPage {
  readonly items: readonly DirectoryEntry[];
  readonly truncated: boolean;
  readonly truncationReason: "entry_limit" | "time_budget" | null;
}

/** 校验目录身份和直接子项，错误响应不能成为可点击的越界导航。 */
export function parseDirectory(
  value: unknown,
  projectId: string,
  path: string,
): DirectoryPage {
  const fail = (): never => {
    throw new ProjectPayloadError();
  };
  if (typeof value !== "object" || value === null) return fail();
  const page = value as Record<string, unknown>;
  if (
    page.project_id !== projectId ||
    page.path !== path ||
    !Array.isArray(page.items) ||
    page.items.length > 500 ||
    typeof page.truncated !== "boolean" ||
    ![null, "entry_limit", "time_budget"].includes(
      page.truncation_reason as string | null,
    ) ||
    page.truncated !== (page.truncation_reason !== null)
  )
    return fail();
  const seen = new Set<string>();
  const items = page.items.map((raw: unknown): DirectoryEntry => {
    if (typeof raw !== "object" || raw === null) return fail();
    const item = raw as Record<string, unknown>;
    if (
      typeof item.name !== "string" ||
      !item.name ||
      item.name.length > 255 ||
      /[\\/\x00-\x1f]/.test(item.name) ||
      [".", ".."].includes(item.name) ||
      item.path !== (path ? `${path}/${item.name}` : item.name) ||
      seen.has(item.name) ||
      !["directory", "file", "unknown"].includes(String(item.kind)) ||
      !["available", "ignored", "unavailable"].includes(String(item.status))
    )
      return fail();
    seen.add(item.name);
    return {
      name: item.name,
      path: item.path,
      kind: item.kind as DirectoryEntry["kind"],
      status: item.status as DirectoryEntry["status"],
    };
  });
  return {
    items,
    truncated: page.truncated,
    truncationReason:
      page.truncation_reason as DirectoryPage["truncationReason"],
  };
}
