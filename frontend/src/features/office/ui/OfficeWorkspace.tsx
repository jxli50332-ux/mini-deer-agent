import {
  createElement,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { CopyButton } from "@/shared/ui/CopyButton";
import { useResizablePreference } from "@/shared/model/use-resizable-preference";
import { formatAttachmentSize } from "@/entities/attachment/model/text-attachments";
import {
  documentDownloadUrl,
  documentPageUrl,
  filenameFromDocumentUrl,
  listOfficeDocuments,
  loadWordPreview,
  loadTextPreview,
  textFileFromUrl,
  textFilePageUrl,
  textFileDownloadUrl,
  type TextFileReference,
  type OfficeDocument,
  type WordPreview,
} from "@/features/office/api/documents";
import { OfficeDocumentsContext } from "@/features/office/model/context";
import { TextDocumentContent } from "./TextDocumentContent";
import { PreviewResizeHandle } from "./PreviewResizeHandle";
import "./office.css";

const PREVIEW_WIDTH = {
  storageKey: "mini-deer-agent.layout.preview-width.v1",
  defaultValue: 600,
  minValue: 360,
  maxStoredValue: 4096,
  getMaxValue: () => {
    const viewport = globalThis.innerWidth || 1440;
    // 桌面保留导航与聊天空间；平板浮层可覆盖大部分屏幕，手机由 CSS 铺满。
    return Math.max(360, viewport > 1100 ? viewport - 640 : viewport * 0.94);
  },
} as const;

type Selection = {
  readonly threadId: string;
  readonly filename: string | null;
  readonly textFile?: TextFileReference;
};

export function OfficeWorkspace({
  children,
  threadId,
  refreshKey,
  hasOfficeTools = false,
  projectId = null,
}: {
  readonly children: ReactNode;
  readonly threadId: string;
  readonly refreshKey: string;
  readonly hasOfficeTools?: boolean;
  readonly projectId?: string | null;
}) {
  const [selection, setSelection] = useState<Selection | null>(() => {
    const filename = filenameFromDocumentUrl(window.location.href);
    const textFile = textFileFromUrl(window.location.href);
    if (textFile !== null)
      return {
        threadId,
        filename: textFile.path.split("/").at(-1) ?? textFile.path,
        textFile,
      };
    return filename === null ? null : { threadId, filename };
  });
  const [documents, setDocuments] = useState<readonly OfficeDocument[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const selected = selection?.threadId === threadId ? selection : null;
  const panelOpen = selected !== null;
  const returnFocus = useRef<HTMLElement | null>(null);
  const panelId = useId();
  const previewWidth = useResizablePreference(PREVIEW_WIDTH);

  useEffect(() => {
    if (selection === null || selection.threadId === threadId) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("document");
    url.searchParams.delete("file");
    url.searchParams.delete("preview_project");
    window.history.replaceState(null, "", url);
    queueMicrotask(() =>
      setSelection((current) =>
        current?.threadId === threadId ? current : null,
      ),
    );
  }, [selection, threadId]);

  useEffect(() => {
    if (!hasOfficeTools && !panelOpen) return;
    const controller = new AbortController();
    void listOfficeDocuments(controller.signal).then(
      (result) => {
        if (!controller.signal.aborted) {
          setDocuments(result);
          setListError(null);
          setLoading(false);
        }
      },
      () => {
        if (!controller.signal.aborted) {
          setListError("无法读取文件列表，请刷新重试。");
          setLoading(false);
        }
      },
    );
    return () => controller.abort();
  }, [refreshKey, revision, hasOfficeTools, panelOpen]);

  const select = useCallback(
    (filename: string | null, textFile?: TextFileReference) => {
      returnFocus.current =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;
      setSelection({
        threadId,
        filename,
        ...(textFile === undefined ? {} : { textFile }),
      });
      const url = new URL(window.location.href);
      url.searchParams.delete("file");
      url.searchParams.delete("preview_project");
      if (filename === null) url.searchParams.delete("document");
      else url.searchParams.set("document", filename);
      if (textFile !== undefined)
        window.history.replaceState(null, "", textFilePageUrl(textFile));
      else window.history.replaceState(null, "", url);
    },
    [threadId],
  );
  const close = useCallback(() => {
    setSelection(null);
    const url = new URL(window.location.href);
    url.searchParams.delete("document");
    url.searchParams.delete("file");
    url.searchParams.delete("preview_project");
    window.history.replaceState(null, "", url);
    returnFocus.current?.focus();
  }, []);
  useEffect(() => {
    if (selected === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [close, selected]);
  useEffect(() => {
    const onPopState = () => {
      const filename = filenameFromDocumentUrl(window.location.href);
      const textFile = textFileFromUrl(window.location.href);
      setSelection(
        textFile !== null
          ? {
              threadId,
              filename: textFile.path.split("/").at(-1) ?? textFile.path,
              textFile,
            }
          : filename === null
            ? null
            : { threadId, filename },
      );
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [threadId]);
  const value = useMemo(
    () => ({
      documents,
      openDocument: (filename: string) => select(filename),
      openTextFile: (path: string, explicitProjectId?: string) => {
        const scopeProjectId =
          explicitProjectId ??
          (path.startsWith("workspace-")
            ? undefined
            : (projectId ?? undefined));
        select(path.split("/").at(-1) ?? path, {
          path,
          ...(scopeProjectId === undefined
            ? {}
            : { projectId: scopeProjectId }),
        });
      },
      projectId,
      openLibrary: () => select(null),
    }),
    [documents, select, projectId],
  );

  return (
    <OfficeDocumentsContext value={value}>
      <div
        className="office-workspace"
        data-preview-open={selected !== null}
        style={
          {
            "--office-preview-width": `${previewWidth.value}px`,
          } as CSSProperties
        }
      >
        {children}
        {selected !== null && (
          <aside
            id={panelId}
            className="office-panel"
            aria-label="文件预览面板"
          >
            <PreviewResizeHandle
              panelId={panelId}
              width={previewWidth.value}
              minWidth={PREVIEW_WIDTH.minValue}
              maxWidth={Math.round(PREVIEW_WIDTH.getMaxValue())}
              onWidthChange={previewWidth.setValue}
              onReset={previewWidth.reset}
            />
            <header className="office-panel__header">
              <div>
                <small>FILES</small>
                <strong>{selected.filename ?? "文件"}</strong>
              </div>
              <button
                type="button"
                className="office-panel__close"
                onClick={close}
                aria-label="关闭文档面板"
              >
                ×
              </button>
            </header>
            {selected.filename === null ? (
              <>
                <div className="office-panel__toolbar">
                  <span>文档输出目录中的文件</span>
                  <button
                    type="button"
                    onClick={() => {
                      setLoading(true);
                      setRevision((r) => r + 1);
                    }}
                  >
                    刷新
                  </button>
                </div>
                {loading && (
                  <p className="office-panel__feedback" role="status">
                    正在读取文档…
                  </p>
                )}
                {listError !== null && (
                  <p className="office-panel__feedback" role="alert">
                    {listError}
                  </p>
                )}
                {!loading && listError === null && documents.length === 0 && (
                  <p className="office-panel__feedback">尚无生成的文件。</p>
                )}
                <ul className="office-library">
                  {documents.map((item) => (
                    <li key={item.filename}>
                      <a
                        href={documentPageUrl(item.filename)}
                        onClick={(event) => {
                          if (
                            event.ctrlKey ||
                            event.metaKey ||
                            event.shiftKey ||
                            event.altKey
                          )
                            return;
                          event.preventDefault();
                          select(item.filename);
                        }}
                      >
                        <span
                          className="office-document-card__icon"
                          aria-hidden="true"
                        >
                          {item.filename.toLowerCase().endsWith(".docx")
                            ? "W"
                            : "文"}
                        </span>
                        <span>
                          <strong>{item.filename}</strong>
                          <small>{formatAttachmentSize(item.sizeBytes)}</small>
                        </span>
                        <span aria-hidden="true">→</span>
                      </a>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <WordDocumentPreview
                key={
                  selected.textFile === undefined
                    ? selected.filename
                    : JSON.stringify(selected.textFile)
                }
                filename={selected.filename}
                {...(selected.textFile === undefined
                  ? {}
                  : { textFile: selected.textFile })}
                onBack={() => select(null)}
              />
            )}
          </aside>
        )}
      </div>
    </OfficeDocumentsContext>
  );
}

function WordDocumentPreview({
  filename,
  onBack,
  textFile,
}: {
  readonly filename: string;
  readonly onBack: () => void;
  readonly textFile?: TextFileReference;
}) {
  const [preview, setPreview] = useState<WordPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    void (
      textFile === undefined
        ? loadWordPreview(filename, controller.signal)
        : loadTextPreview(textFile, controller.signal)
    ).then(
      (result) => {
        if (!controller.signal.aborted) {
          setPreview(result);
          setError(null);
          setLoading(false);
        }
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "文档无法读取");
          setLoading(false);
        }
      },
    );
    return () => controller.abort();
  }, [filename, attempt, textFile]);
  const pageUrl =
    textFile === undefined
      ? documentPageUrl(filename)
      : textFilePageUrl(textFile);
  const isWord =
    textFile === undefined && filename.toLowerCase().endsWith(".docx");
  return (
    <>
      <div className="office-panel__toolbar">
        <button type="button" onClick={onBack}>
          ← 全部文档
        </button>
        <button
          type="button"
          onClick={() => {
            setLoading(true);
            setError(null);
            setAttempt((n) => n + 1);
          }}
        >
          刷新预览
        </button>
        <CopyButton
          text={new URL(pageUrl, window.location.href).href}
          label="复制链接"
        />
        <a
          className="office-download"
          href={
            textFile === undefined
              ? documentDownloadUrl(filename)
              : textFileDownloadUrl(textFile)
          }
          download={filename}
        >
          {isWord ? "下载 Word" : "下载文件"}
        </a>
      </div>
      <p className="office-panel__hint">
        {isWord ? "内容预览 · 原始排版请下载后查看" : "UTF-8 文本预览"}
        {preview === null
          ? ""
          : ` · ${formatAttachmentSize(preview.document.sizeBytes)}`}
      </p>
      <div className="office-panel__scroll" aria-busy={loading}>
        {loading && (
          <p className="office-panel__feedback" role="status">
            正在打开文件…
          </p>
        )}
        {error !== null && (
          <p className="office-panel__feedback" role="alert">
            {error}
          </p>
        )}
        {!loading && error === null && preview !== null && (
          <article className="word-preview" aria-label={`文档内容 ${filename}`}>
            {preview.kind === "markdown" || preview.kind === "text" ? (
              <TextDocumentContent
                content={preview.content ?? ""}
                markdown={preview.kind === "markdown"}
              />
            ) : null}
            {(preview.kind === undefined || preview.kind === "word") &&
              preview.blocks.length === 0 && <p>这是一个空文档。</p>}
            {preview.blocks.map((block, index) =>
              block.kind === "table" ? (
                <div className="word-preview__table" key={index}>
                  <table>
                    <tbody>
                      {block.rows.map((row, r) => (
                        <tr key={r}>
                          {row.map((cell, c) => (
                            <td key={c}>{cell}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : block.headingLevel > 0 ? (
                createElement(
                  `h${block.headingLevel}`,
                  { key: index },
                  block.text,
                )
              ) : (
                <p key={index}>{block.text || "\u00a0"}</p>
              ),
            )}
            {preview.truncated && (
              <p className="word-preview__truncated">
                内容较长，预览已截取。下载文件可查看完整内容。
              </p>
            )}
          </article>
        )}
      </div>
    </>
  );
}
