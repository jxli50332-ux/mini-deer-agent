import type { MouseEvent } from "react";
import type { ChatTimelineItem } from "@/entities/message/model/types";
import { formatAttachmentSize } from "@/entities/attachment/model/text-attachments";
import {
  documentPageUrl,
  isTextFilename,
  textFilePageUrl,
  textFileFromUrl,
  type TextFileReference,
} from "@/features/office/api/documents";
import { useOfficeDocuments } from "@/features/office/model/context";

export function OfficeDocumentsButton() {
  const office = useOfficeDocuments();
  if (office === null) return null;
  return (
    <button
      type="button"
      className="benchmark-open-button"
      onClick={office.openLibrary}
    >
      文件
      {office.documents.length > 0 ? ` · ${office.documents.length}` : ""}
    </button>
  );
}

/** 以真实文件清单核对工具参数；不从模型正文猜测文件是否生成成功。 */
export function OfficeDocumentCards({
  steps,
}: {
  readonly steps: readonly ChatTimelineItem[];
}) {
  const office = useOfficeDocuments();
  if (office === null) return null;
  const names = new Set<string>();
  const textFiles = new Map<string, TextFileReference>();
  for (const step of steps) {
    if (
      step.kind !== "tool" ||
      step.status !== "completed" ||
      step.name === null
    )
      continue;
    try {
      const input: unknown = JSON.parse(step.input);
      if (input === null || typeof input !== "object" || Array.isArray(input))
        continue;
      const filename = (input as Record<string, unknown>).filename;
      if (step.name.startsWith("word_") && typeof filename === "string")
        names.add(filename.replace(/\\/g, "/").split("/").at(-1) ?? "");
      const path = (input as Record<string, unknown>).path;
      if (
        ["create_file", "overwrite_file", "str_replace", "read_file"].includes(
          step.name,
        ) &&
        typeof path === "string" &&
        isTextFilename(path)
      ) {
        const ref: TextFileReference = {
          path,
          ...(path.startsWith("workspace-") || office.projectId === null
            ? {}
            : { projectId: office.projectId }),
        };
        if (textFileFromUrl(textFilePageUrl(ref)) !== null)
          textFiles.set(JSON.stringify(ref), ref);
      }
    } catch {
      /* 流式参数尚未完成时不展示文件卡片。 */
    }
  }
  const documents = office.documents.filter((item) => names.has(item.filename));
  if (documents.length === 0 && textFiles.size === 0) return null;
  return (
    <>
      {documents.length > 0 && (
        <ul className="office-document-cards" aria-label="相关 Word 文档">
          {documents.map((item) => (
            <li key={item.filename}>
              <a
                href={documentPageUrl(item.filename)}
                onClick={(event: MouseEvent<HTMLAnchorElement>) => {
                  if (
                    event.button !== 0 ||
                    event.ctrlKey ||
                    event.metaKey ||
                    event.shiftKey ||
                    event.altKey
                  )
                    return;
                  event.preventDefault();
                  office.openDocument(item.filename);
                }}
              >
                <span className="office-document-card__icon" aria-hidden="true">
                  W
                </span>
                <span>
                  <strong>{item.filename}</strong>
                  <small>
                    Word · {formatAttachmentSize(item.sizeBytes)} · 点击预览
                  </small>
                </span>
                <span aria-hidden="true">↗</span>
              </a>
            </li>
          ))}
        </ul>
      )}
      {textFiles.size > 0 && (
        <ul className="office-document-cards" aria-label="相关文本文件">
          {[...textFiles.values()].map((file) => (
            <li key={JSON.stringify(file)}>
              <a
                href={textFilePageUrl(file)}
                onClick={(event) => {
                  if (
                    event.button !== 0 ||
                    event.ctrlKey ||
                    event.metaKey ||
                    event.shiftKey ||
                    event.altKey
                  )
                    return;
                  event.preventDefault();
                  office.openTextFile(file.path, file.projectId);
                }}
              >
                <span className="office-document-card__icon" aria-hidden="true">
                  文
                </span>
                <span>
                  <strong>{file.path.split("/").at(-1)}</strong>
                  <small>{file.path} · 点击预览</small>
                </span>
                <span aria-hidden="true">↗</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
