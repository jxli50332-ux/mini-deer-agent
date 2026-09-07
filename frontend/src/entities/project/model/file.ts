import { ProjectPayloadError } from "./types";

export interface FilePage {
  readonly status:
    "text" | "binary" | "unsupported_encoding" | "too_large" | "line_too_long";
  readonly lines: readonly string[];
  readonly startLine: number;
  readonly nextLine: number | null;
  readonly totalLines: number | null;
  readonly revision: string | null;
  readonly sizeBytes: number;
}

/** 正文响应必须匹配项目、文件和请求行号，分页游标只能指向连续下一行。 */
export function parseFilePage(
  value: unknown,
  projectId: string,
  path: string,
  startLine: number,
): FilePage {
  const fail = (): never => {
    throw new ProjectPayloadError();
  };
  if (typeof value !== "object" || value === null) return fail();
  const data = value as Record<string, unknown>;
  if (
    data.project_id !== projectId ||
    data.path !== path ||
    data.start_line !== startLine ||
    !Number.isSafeInteger(data.size_bytes) ||
    (data.size_bytes as number) < 0 ||
    ![
      "text",
      "binary",
      "unsupported_encoding",
      "too_large",
      "line_too_long",
    ].includes(String(data.status)) ||
    !Array.isArray(data.lines) ||
    data.lines.length > 500
  )
    return fail();
  const lines: string[] = [];
  let chars = 0;
  for (const line of data.lines as unknown[]) {
    if (typeof line !== "string" || /[\r\n]/.test(line)) return fail();
    chars += line.length + 1;
    if (chars > 65536) return fail(); // UTF-16 长度至多是后端 Unicode 字符预算的两倍。
    lines.push(line);
  }
  if (
    data.revision !== null &&
    (typeof data.revision !== "string" || !/^[a-f0-9]{64}$/.test(data.revision))
  )
    return fail();
  if (
    data.total_lines !== null &&
    (!Number.isSafeInteger(data.total_lines) ||
      (data.total_lines as number) < 0)
  )
    return fail();
  if (data.status === "text") {
    if (
      typeof data.total_lines !== "number" ||
      typeof data.revision !== "string" ||
      startLine > Math.max(1, data.total_lines) ||
      startLine - 1 + lines.length > data.total_lines ||
      (data.total_lines > 0 && lines.length === 0)
    )
      return fail();
    const expectedNext =
      startLine - 1 + lines.length < data.total_lines
        ? startLine + lines.length
        : null;
    if (data.next_line !== expectedNext) return fail();
  } else if (lines.length !== 0 || data.next_line !== null) return fail();
  return {
    status: data.status as FilePage["status"],
    lines,
    startLine,
    nextLine: data.next_line as number | null,
    totalLines: data.total_lines as number | null,
    revision: data.revision,
    sizeBytes: data.size_bytes as number,
  };
}
