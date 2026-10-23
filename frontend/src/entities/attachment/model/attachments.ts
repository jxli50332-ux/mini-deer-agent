import {
  MAX_TEXT_ATTACHMENT_COUNT,
  MAX_TEXT_ATTACHMENTS_TOTAL_BYTES,
  isSupportedTextAttachmentMediaType,
  prepareSelectedTextAttachments,
  validateTextAttachmentPayloads,
  type TextAttachmentMediaType,
  type TextAttachmentPayload,
} from "./text-attachments";

export { formatAttachmentSize } from "./text-attachments";
export const MAX_IMAGE_ATTACHMENT_BYTES = 4 * 1024 * 1024;
const MAX_IMAGES_TOTAL_BYTES = 8 * 1024 * 1024;
type ImageMediaType = "image/png" | "image/jpeg";
export type AttachmentMediaType = TextAttachmentMediaType | ImageMediaType;
export type AttachmentPayload = TextAttachmentPayload;
export interface PreparedAttachment {
  readonly filename: string;
  readonly mediaType: AttachmentMediaType;
  readonly sizeBytes: number;
  readonly content: string;
}
export type AttachmentContent = PreparedAttachment;

/** 下载使用稳定消息身份，避免 data/blob URL 被内嵌浏览器拦截。 */
export function attachmentDownloadUrl(
  messageId: string,
  position: number,
): string {
  return `/api/v1/attachments/${encodeURIComponent(messageId)}/${position}/download`;
}

/** 根据已验证的媒体类型区分视觉内容，图片只使用本地 data URL。 */
export function isImageAttachment(value: {
  readonly mediaType: string;
}): boolean {
  return value.mediaType === "image/png" || value.mediaType === "image/jpeg";
}

/** 历史响应和乐观消息共享同一份媒体类型白名单。 */
export function isSupportedAttachmentMediaType(
  value: string,
): value is AttachmentMediaType {
  return (
    isImageAttachment({ mediaType: value }) ||
    isSupportedTextAttachmentMediaType(value)
  );
}

function imageMediaType(filename: string): ImageMediaType | null {
  return /\.png$/i.test(filename)
    ? "image/png"
    : /\.jpe?g$/i.test(filename)
      ? "image/jpeg"
      : null;
}

function validateImage(
  filename: string,
  content: string,
  mediaType: ImageMediaType,
): PreparedAttachment {
  if (!filename || filename.length > 120 || /[/\\\x00-\x1f]/.test(filename))
    throw new Error("附件文件名无效");
  const prefix = `data:${mediaType};base64,`;
  if (content.length > 4 * Math.ceil(MAX_IMAGE_ATTACHMENT_BYTES / 3) + 32)
    throw new Error("单张图片不能超过 4 MiB");
  if (
    !content.startsWith(prefix) ||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(content.slice(prefix.length))
  )
    throw new Error("图片内容或格式无效，仅支持 PNG、JPG/JPEG");
  let bytes: string;
  try {
    bytes = atob(content.slice(prefix.length));
  } catch {
    throw new Error("无法读取图片编码");
  }
  if (!bytes.length || bytes.length > MAX_IMAGE_ATTACHMENT_BYTES)
    throw new Error("图片不能为空且不能超过 4 MiB");
  // 浏览器做快速格式检查，后端还会完整解码以验证损坏内容和像素上限。
  if (
    !(mediaType === "image/png"
      ? bytes.startsWith("\x89PNG\r\n\x1a\n")
      : bytes.startsWith("\xff\xd8\xff"))
  )
    throw new Error("图片实际格式与文件名不一致");
  return { filename, content, mediaType, sizeBytes: bytes.length };
}

/** HTTP 发送前再次校验混合附件，沿用 filename/content 协议以兼容已有文本附件。 */
export function validateAttachmentPayloads(
  values: readonly AttachmentPayload[],
): readonly PreparedAttachment[] {
  if (values.length > MAX_TEXT_ATTACHMENT_COUNT)
    throw new Error("每条消息最多添加 3 个附件");
  const prepared = values.map(({ filename: rawName, content }) => {
    const filename = rawName.trim();
    const mediaType = imageMediaType(filename);
    if (mediaType !== null) return validateImage(filename, content, mediaType);
    const [text] = validateTextAttachmentPayloads([{ filename, content }]);
    if (text === undefined) throw new Error("无法读取附件");
    return text;
  });
  if (
    prepared
      .filter(isImageAttachment)
      .reduce((sum, item) => sum + item.sizeBytes, 0) > MAX_IMAGES_TOTAL_BYTES
  )
    throw new Error("一条消息的图片总大小不能超过 8 MiB");
  if (
    prepared
      .filter((item) => !isImageAttachment(item))
      .reduce((sum, item) => sum + item.sizeBytes, 0) >
    MAX_TEXT_ATTACHMENTS_TOTAL_BYTES
  )
    throw new Error("一条消息的文本附件总大小不能超过 64 KiB");
  return prepared;
}

function readImage(file: File, mediaType: ImageMediaType): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("无法读取图片"));
    reader.onload = () =>
      typeof reader.result === "string"
        ? // 文件系统未提供 MIME 时仍使用已核对的扩展名；实际字节还会检查。
          resolve(
            `data:${mediaType};base64,${reader.result.slice(reader.result.indexOf(",") + 1)}`,
          )
        : reject(new Error("无法读取图片"));
    reader.readAsDataURL(file);
  });
}

/** 图片保持原始视觉内容，文本复用既有 UTF-8 读取规则，不执行 OCR。 */
export async function prepareSelectedAttachments(
  existing: readonly PreparedAttachment[],
  selected: FileList | readonly File[],
): Promise<readonly PreparedAttachment[]> {
  const files = Array.from(selected);
  if (existing.length + files.length > MAX_TEXT_ATTACHMENT_COUNT)
    throw new Error("每条消息最多添加 3 个附件");
  const incoming: PreparedAttachment[] = [];
  for (const file of files) {
    const mediaType = imageMediaType(file.name.trim());
    if (mediaType !== null) {
      if (file.size > MAX_IMAGE_ATTACHMENT_BYTES)
        throw new Error("单张图片不能超过 4 MiB");
      if (typeof createImageBitmap === "function") {
        const bitmap = await createImageBitmap(file).catch(() => {
          throw new Error("图片已损坏或无法解码");
        });
        try {
          if (
            Math.max(bitmap.width, bitmap.height) > 6000 ||
            bitmap.width * bitmap.height > 16_000_000
          )
            throw new Error(
              "图片单边不能超过 6000 像素，总像素不能超过 1600 万",
            );
        } finally {
          bitmap.close();
        }
      }
      incoming.push(
        validateImage(
          file.name.trim(),
          await readImage(file, mediaType),
          mediaType,
        ),
      );
    } else {
      incoming.push(...(await prepareSelectedTextAttachments([], [file])));
    }
  }
  return validateAttachmentPayloads([...existing, ...incoming]);
}
