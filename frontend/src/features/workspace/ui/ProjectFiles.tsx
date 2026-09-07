import { useEffect, useRef, useState } from "react";
import { ProjectFileTree, type DirectoryLoader } from "./ProjectFileTree";
import type { FilePage } from "@/entities/project/model/file";

export type FileLoader = (
  projectId: string,
  path: string,
  startLine: number,
  signal: AbortSignal,
) => Promise<FilePage>;
const STATUS_TEXT = {
  binary: "这是二进制文件，无法显示源码。",
  unsupported_encoding: "文件不是 UTF-8 编码，暂不支持预览。",
  too_large: "文件超过 2 MiB 预览上限。",
  line_too_long: "当前行超过显示长度上限，无法完整预览。",
};

/** 预览随项目树生命周期卸载，关闭或切换项目不保留源码正文。 */
export function ProjectFiles({
  projectId,
  rootName = "文件",
  initiallyOpen = false,
  refreshRevision = 0,
  loadDirectory,
  loadFile,
  canReferenceCurrentThread = false,
  onReferenceFile,
}: {
  readonly projectId: string;
  readonly rootName?: string;
  readonly initiallyOpen?: boolean;
  readonly refreshRevision?: number;
  readonly loadDirectory: DirectoryLoader;
  readonly loadFile: FileLoader;
  readonly canReferenceCurrentThread?: boolean;
  readonly onReferenceFile?: (path: string) => void;
}) {
  const [path, setPath] = useState<string | null>(null);
  return (
    <>
      <ProjectFileTree
        projectId={projectId}
        load={loadDirectory}
        name={rootName}
        initiallyOpen={initiallyOpen}
        refreshRevision={refreshRevision}
        onOpenFile={setPath}
      />
      {path !== null && (
        <FilePreview
          key={path}
          projectId={projectId}
          path={path}
          load={loadFile}
          onClose={() => setPath(null)}
          canReferenceCurrentThread={canReferenceCurrentThread}
          {...(onReferenceFile === undefined ? {} : { onReferenceFile })}
        />
      )}
    </>
  );
}

/** 按段显示源码并核对版本；使用纯文本节点，不把源码当 HTML 或 Markdown 执行。 */
export function FilePreview({
  projectId,
  path,
  load,
  onClose,
  canReferenceCurrentThread = false,
  onReferenceFile,
}: {
  readonly projectId: string;
  readonly path: string;
  readonly load: FileLoader;
  readonly onClose: () => void;
  readonly canReferenceCurrentThread?: boolean;
  readonly onReferenceFile?: (path: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [request, setRequest] = useState({ start: 1, attempt: 0 });
  const [page, setPage] = useState<FilePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [previous, setPrevious] = useState<number[]>([]);
  const revision = useRef<string | null>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    void load(projectId, path, request.start, controller.signal).then(
      (result) => {
        if (!live) return;
        if (revision.current !== null && result.revision !== revision.current) {
          setError("文件已在外部修改，请重新加载，避免混用不同版本。");
        } else {
          revision.current = result.revision;
          setPage(result);
        }
        setLoading(false);
      },
      () => {
        if (live) {
          setError("文件读取失败，可能已移动、删除或无法访问。请重新加载。");
          setLoading(false);
        }
      },
    );
    return () => {
      live = false;
      controller.abort();
    };
  }, [projectId, path, load, request]);
  const go = (start: number) => {
    setLoading(true);
    setError(null);
    setPage(null);
    setRequest((current) => ({ start, attempt: current.attempt + 1 }));
  };
  return (
    <dialog
      ref={dialog}
      className="source-preview"
      aria-label={`源码预览 ${path}`}
      onClose={onClose}
    >
      <header className="source-preview__header">
        <div>
          <strong>{path}</strong>
          <small>只读源码预览</small>
        </div>
        <button type="button" onClick={onClose} aria-label="关闭源码预览">
          关闭
        </button>
      </header>
      <div className="source-preview__actions">
        {onReferenceFile !== undefined && (
          <button
            type="button"
            disabled={!canReferenceCurrentThread}
            title={
              canReferenceCurrentThread
                ? "把项目相对路径插入当前输入框"
                : "请先进入该项目的会话"
            }
            onClick={() => {
              onReferenceFile(path);
              onClose();
            }}
          >
            引用到当前提问
          </button>
        )}
        <button
          type="button"
          disabled={loading}
          onClick={() => {
            revision.current = null;
            setPrevious([]);
            go(1);
          }}
        >
          重新加载
        </button>
        {page && (
          <span>
            {page.sizeBytes} 字节
            {page.status === "text" && page.totalLines !== null
              ? ` · 共 ${page.totalLines} 行`
              : ""}
          </span>
        )}
      </div>
      {loading && <p role="status">正在读取源码…</p>}
      {error && <p role="alert">{error}</p>}
      {page && !error && (
        <>
          {page.status !== "text" ? (
            <p role="status">{STATUS_TEXT[page.status]}</p>
          ) : page.lines.length === 0 ? (
            <p>空文件</p>
          ) : (
            <div
              className="source-preview__code"
              tabIndex={0}
              aria-label="源码内容"
            >
              {page.lines.map((line, index) => (
                <div
                  className="source-preview__line"
                  key={page.startLine + index}
                >
                  <span
                    className="source-preview__number"
                    aria-label={`第 ${page.startLine + index} 行`}
                  >
                    {page.startLine + index}
                  </span>
                  <code>{line || " "}</code>
                </div>
              ))}
            </div>
          )}
          <footer className="source-preview__actions">
            <button
              type="button"
              disabled={loading || previous.length === 0}
              onClick={() => {
                const start = previous.at(-1);
                if (start !== undefined) {
                  setPrevious(previous.slice(0, -1));
                  go(start);
                }
              }}
            >
              上一段
            </button>
            <button
              type="button"
              disabled={loading || page.nextLine === null}
              onClick={() => {
                if (page.nextLine !== null) {
                  setPrevious([...previous, page.startLine]);
                  go(page.nextLine);
                }
              }}
            >
              下一段
            </button>
            {page.lines.length > 0 && (
              <span>
                第 {page.startLine}—{page.startLine + page.lines.length - 1} 行
              </span>
            )}
          </footer>
        </>
      )}
    </dialog>
  );
}
