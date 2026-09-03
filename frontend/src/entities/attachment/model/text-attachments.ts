export const MAX_TEXT_ATTACHMENT_COUNT = 3;
export const MAX_TEXT_ATTACHMENT_BYTES = 32 * 1024;
export const MAX_TEXT_ATTACHMENTS_TOTAL_BYTES = 64 * 1024;

// 只收录可以安全作为 UTF-8 文本内联进模型上下文的扩展名。
// 此映射必须与后端 attachments.py 保持一致，历史恢复会按同一媒体类型白名单校验。
export const MEDIA_TYPES_BY_EXTENSION = {
  // 基础文本与数据
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".json": "application/json",
  ".csv": "text/csv",
  // 编程语言
  ".py": "text/x-python",
  ".js": "text/javascript",
  ".jsx": "text/jsx",
  ".ts": "text/typescript",
  ".tsx": "text/tsx",
  ".go": "text/x-go",
  ".java": "text/x-java",
  ".c": "text/x-c",
  ".h": "text/x-c",
  ".cpp": "text/x-c++",
  ".hpp": "text/x-c++",
  ".rs": "text/x-rust",
  ".sql": "text/x-sql",
  ".sh": "text/x-sh",
  // Web 标记与样式
  ".html": "text/html",
  ".htm": "text/html",
  ".css": "text/css",
  ".scss": "text/x-scss",
  // 配置与结构化数据
  ".yaml": "text/yaml",
  ".yml": "text/yaml",
  ".xml": "text/xml",
  ".toml": "application/toml",
} as const;

export type TextAttachmentMediaType =
  (typeof MEDIA_TYPES_BY_EXTENSION)[keyof typeof MEDIA_TYPES_BY_EXTENSION];

export interface TextAttachmentMetadata {
  readonly filename: string;
  readonly mediaType: TextAttachmentMediaType;
  readonly sizeBytes: number;
}

/** 从服务端历史读回的完整附件，含正文，用于历史消息里查看文件内容。 */
export interface TextAttachmentContent extends TextAttachmentMetadata {
  readonly content: string;
}

export interface PreparedTextAttachment extends TextAttachmentMetadata {
  readonly content: string;
}

export interface TextAttachmentPayload {
  readonly filename: string;
  readonly content: string;
}

function mediaTypeForFilename(
  filename: string,
): TextAttachmentMediaType | null {
  const dotIndex = filename.lastIndexOf(".");
  const extension = dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
  return (
    MEDIA_TYPES_BY_EXTENSION[
      extension as keyof typeof MEDIA_TYPES_BY_EXTENSION
    ] ?? null
  );
}

function validateFilename(filename: string): TextAttachmentMediaType {
  if (
    filename.length === 0 ||
    filename.length > 120 ||
    filename === "." ||
    filename === ".." ||
    filename.includes("/") ||
    filename.includes("\\")
  ) {
    throw new Error("附件文件名无效");
  }
  const mediaType = mediaTypeForFilename(filename);
  if (mediaType === null) {
    throw new Error("不支持该文件类型，仅支持文本类附件");
  }
  return mediaType;
}

/** 判断历史响应中的媒体类型是否属于当前支持的文本附件集合，并作为类型守卫收窄。 */
export function isSupportedTextAttachmentMediaType(
  value: string,
): value is TextAttachmentMediaType {
  return (
    Object.values(MEDIA_TYPES_BY_EXTENSION) as readonly string[]
  ).includes(value);
}

function utf8Size(content: string): number {
  return new TextEncoder().encode(content).byteLength;
}

/** 在 HTTP 边界再次校验已经读取的附件正文，不依赖 Composer 状态。 */
export function validateTextAttachmentPayloads(
  values: readonly TextAttachmentPayload[],
): readonly PreparedTextAttachment[] {
  if (values.length > MAX_TEXT_ATTACHMENT_COUNT) {
    throw new Error(`每条消息最多添加 ${MAX_TEXT_ATTACHMENT_COUNT} 个附件`);
  }

  const attachments = values.map((value) => {
    const filename = value.filename.trim();
    const mediaType = validateFilename(filename);
    const sizeBytes = utf8Size(value.content);
    if (sizeBytes === 0) {
      throw new Error("不能添加空附件");
    }
    if (sizeBytes > MAX_TEXT_ATTACHMENT_BYTES) {
      throw new Error("单个附件不能超过 32 KiB");
    }
    return { filename, mediaType, sizeBytes, content: value.content };
  });

  if (
    attachments.reduce((total, item) => total + item.sizeBytes, 0) >
    MAX_TEXT_ATTACHMENTS_TOTAL_BYTES
  ) {
    throw new Error("一条消息的附件总大小不能超过 64 KiB");
  }
  return attachments;
}

function readFileAsArrayBuffer(file: File): Promise<ArrayBuffer> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("无法读取附件"));
    reader.onload = () => {
      if (!(reader.result instanceof ArrayBuffer)) {
        reject(new Error("无法读取附件"));
        return;
      }
      resolve(reader.result);
    };
    reader.readAsArrayBuffer(file);
  });
}

/** 读取浏览器 File，并用 fatal UTF-8 解码阻止二进制内容伪装成文本。 */
export async function prepareSelectedTextAttachments(
  existing: readonly PreparedTextAttachment[],
  selected: FileList | readonly File[],
): Promise<readonly PreparedTextAttachment[]> {
  const incoming = Array.from(selected);
  if (existing.length + incoming.length > MAX_TEXT_ATTACHMENT_COUNT) {
    throw new Error(`每条消息最多添加 ${MAX_TEXT_ATTACHMENT_COUNT} 个附件`);
  }

  const prepared: PreparedTextAttachment[] = [];
  for (const file of incoming) {
    const filename = file.name.trim();
    const mediaType = validateFilename(filename);
    if (file.size === 0) {
      throw new Error("不能添加空附件");
    }
    if (file.size > MAX_TEXT_ATTACHMENT_BYTES) {
      throw new Error("单个附件不能超过 32 KiB");
    }
    let content: string;
    try {
      content = new TextDecoder("utf-8", { fatal: true }).decode(
        await readFileAsArrayBuffer(file),
      );
    } catch {
      throw new Error("附件必须是有效的 UTF-8 文本");
    }
    const [validated] = validateTextAttachmentPayloads([{ filename, content }]);
    if (validated === undefined) {
      throw new Error("无法读取附件");
    }
    prepared.push({ ...validated, mediaType });
  }

  const combined = [...existing, ...prepared];
  if (
    combined.reduce((total, item) => total + item.sizeBytes, 0) >
    MAX_TEXT_ATTACHMENTS_TOTAL_BYTES
  ) {
    throw new Error("一条消息的附件总大小不能超过 64 KiB");
  }
  return combined;
}

export function formatAttachmentSize(bytes: number): string {
  return bytes < 1024
    ? `${bytes} B`
    : `${Number((bytes / 1024).toFixed(1))} KiB`;
}
