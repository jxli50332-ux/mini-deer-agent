export interface OfficeDocument {
  readonly filename: string;
  readonly sizeBytes: number;
  readonly modifiedAt: string;
}

export type WordBlock =
  | {
      readonly kind: "paragraph";
      readonly text: string;
      readonly headingLevel: number;
    }
  | { readonly kind: "table"; readonly rows: readonly (readonly string[])[] };

export interface WordPreview {
  readonly document: OfficeDocument;
  readonly title: string;
  readonly blocks: readonly WordBlock[];
  readonly truncated: boolean;
  readonly kind?: "word" | "markdown" | "text";
  readonly content?: string | null;
}

export interface TextFileReference {
  readonly path: string;
  readonly projectId?: string;
}
export function isTextFilename(filename: string): boolean {
  if (
    /^(readme|license|makefile|dockerfile|\.gitignore|\.dockerignore)$/i.test(
      filename.split("/").at(-1) ?? filename,
    )
  )
    return true;
  return /\.(md|markdown|txt|text|json|ya?ml|toml|ini|cfg|conf|xml|html|css|scss|csv|tsv|py|[cm]?js|jsx|ts|tsx|sql|sh|ps1|bat|c|cpp|h|hpp|rs|go|java|rb|log|rst|vue|svelte)$/i.test(
    filename,
  );
}

export function textFilePageUrl(file: TextFileReference): string {
  const url = new URL(window.location.href);
  url.searchParams.delete("document");
  url.searchParams.set("file", file.path);
  url.searchParams.delete("preview_project");
  if (file.projectId !== undefined)
    url.searchParams.set("preview_project", file.projectId);
  return `${url.pathname}${url.search}${url.hash}`;
}

export function textFileFromUrl(href: string): TextFileReference | null {
  try {
    const url = new URL(href, window.location.href);
    if (url.origin !== window.location.origin) return null;
    if (url.pathname !== window.location.pathname) {
      // Agent 已有的 workspace-N 相对文件链接也进入统一面板。
      const scopedPath = decodeURIComponent(url.pathname).replace(/^\//, "");
      return /^workspace-\d+\//.test(scopedPath) && isTextFilename(scopedPath)
        ? textFileFromUrl(textFilePageUrl({ path: scopedPath }))
        : null;
    }
    const path = url.searchParams.get("file");
    if (
      path === null ||
      path.length > 2048 ||
      path.startsWith("/") ||
      path.includes("\\") ||
      path.includes(":") ||
      path
        .split("/")
        .some((part) => part === ".." || part === "." || part === "")
    )
      return null;
    const projectId = url.searchParams.get("preview_project");
    return { path, ...(projectId === null ? {} : { projectId }) };
  } catch {
    return null;
  }
}

export function textFileDownloadUrl(file: TextFileReference): string {
  const query = new URLSearchParams({ path: file.path });
  if (file.projectId !== undefined) query.set("project_id", file.projectId);
  return `/api/v1/office/documents/text-download?${query}`;
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("文档服务返回了无效数据");
  }
  return value as Record<string, unknown>;
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("文档服务返回了无效文本");
  return value;
}

function document(value: unknown): OfficeDocument {
  const item = record(value);
  if (
    typeof item.size_bytes !== "number" ||
    !Number.isFinite(item.size_bytes)
  ) {
    throw new Error("文档大小无效");
  }
  return {
    filename: text(item.filename),
    sizeBytes: item.size_bytes,
    modifiedAt: text(item.modified_at),
  };
}

async function request(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, { signal, cache: "no-store" });
  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? "文档已移动、删除或尚未生成。"
        : response.status === 415
          ? "此文件不是有效的 UTF-8 纯文本，无法预览。"
          : response.status === 413
            ? "文件超过在线预览大小上限。"
            : "文档暂时无法读取，请稍后重试。",
    );
  }
  return response.json() as Promise<unknown>;
}

export async function listOfficeDocuments(
  signal: AbortSignal,
): Promise<readonly OfficeDocument[]> {
  const data = record(await request("/api/v1/office/documents", signal));
  if (!Array.isArray(data.documents)) throw new Error("文档列表无效");
  return data.documents.map(document);
}

export function documentDownloadUrl(filename: string): string {
  return `/api/v1/office/documents/${encodeURIComponent(filename)}/download`;
}

/** 使用页面 URL 分享预览，浏览器不需要访问宿主的绝对文件路径。 */
export function documentPageUrl(filename: string): string {
  const url = new URL(window.location.href);
  url.searchParams.delete("file");
  url.searchParams.delete("preview_project");
  url.searchParams.set("document", filename);
  return `${url.pathname}${url.search}${url.hash}`;
}

export function filenameFromDocumentUrl(href: string): string | null {
  try {
    const url = new URL(href, window.location.href);
    if (
      url.origin !== window.location.origin ||
      url.pathname !== window.location.pathname
    )
      return null;
    const filename = url.searchParams.get("document");
    return filename !== null &&
      /^[^<>:"/\\|?*\x00-\x1f]+$/i.test(filename) &&
      (filename.toLowerCase().endsWith(".docx") || isTextFilename(filename))
      ? filename
      : null;
  } catch {
    return null;
  }
}

export async function loadWordPreview(
  filename: string,
  signal: AbortSignal,
): Promise<WordPreview> {
  const data = record(
    await request(
      `/api/v1/office/documents/${encodeURIComponent(filename)}/preview`,
      signal,
    ),
  );
  return parsePreview(data);
}

function parsePreview(data: Record<string, unknown>): WordPreview {
  if (!Array.isArray(data.blocks) || typeof data.truncated !== "boolean")
    throw new Error("文档预览无效");
  const blocks = data.blocks.map((value: unknown): WordBlock => {
    const block = record(value);
    if (
      block.kind === "paragraph" &&
      typeof block.heading_level === "number" &&
      Number.isInteger(block.heading_level) &&
      block.heading_level >= 0 &&
      block.heading_level <= 6
    ) {
      return {
        kind: "paragraph",
        text: text(block.text),
        headingLevel: block.heading_level,
      };
    }
    if (block.kind === "table" && Array.isArray(block.rows)) {
      const rows = block.rows.map((row: unknown) => {
        if (!Array.isArray(row)) throw new Error("文档表格无效");
        return row.map(text);
      });
      return { kind: "table", rows };
    }
    throw new Error("不支持的文档内容");
  });
  return {
    document: document(data.document),
    title: text(data.title),
    blocks,
    truncated: data.truncated,
    kind:
      data.kind === "markdown"
        ? "markdown"
        : data.kind === "text"
          ? "text"
          : "word",
    content:
      data.kind === "markdown" || data.kind === "text"
        ? text(data.content)
        : null,
  };
}

export async function loadTextPreview(
  file: TextFileReference,
  signal: AbortSignal,
): Promise<WordPreview> {
  const query = new URLSearchParams({ path: file.path });
  if (file.projectId !== undefined) query.set("project_id", file.projectId);
  return parsePreview(
    record(
      await request(`/api/v1/office/documents/text-preview?${query}`, signal),
    ),
  );
}
