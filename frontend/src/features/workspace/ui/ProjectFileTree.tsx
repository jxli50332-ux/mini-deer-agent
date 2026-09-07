import { useEffect, useState } from "react";
import type { DirectoryPage } from "@/entities/project/model/directory";

export type DirectoryLoader = (
  projectId: string,
  path: string,
  signal: AbortSignal,
) => Promise<DirectoryPage>;
interface Props {
  readonly projectId: string;
  readonly load: DirectoryLoader;
  readonly path?: string;
  readonly name?: string;
  readonly initiallyOpen?: boolean;
  readonly refreshRevision?: number;
  readonly onOpenFile?: (path: string) => void;
}

/** 每个目录独立懒加载；卸载或刷新拒绝旧响应，避免切换项目后串树。 */
export function ProjectFileTree({
  projectId,
  load,
  path = "",
  name = "文件",
  initiallyOpen = false,
  refreshRevision = 0,
  onOpenFile,
}: Props) {
  const [open, setOpen] = useState(initiallyOpen);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<DirectoryPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(initiallyOpen);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    let live = true;
    void load(projectId, path, controller.signal).then(
      (result) => {
        if (live) {
          setPage(result);
          setError(null);
          setLoading(false);
        }
      },
      () => {
        if (live) {
          setError("目录加载失败，请刷新重试。");
          setLoading(false);
        }
      },
    );
    return () => {
      live = false;
      controller.abort();
    };
  }, [open, revision, refreshRevision, projectId, path, load]);
  return (
    <div className="project-file-tree">
      <div className="project-file-tree__row">
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${open ? "收起" : "展开"}目录 ${path || "根目录"}`}
          onClick={() => {
            if (!open) {
              setLoading(true);
              setPage(null);
              setError(null);
            }
            setOpen(!open);
          }}
        >
          <span aria-hidden="true">{open ? "▾" : "▸"}</span> {name}
        </button>
        {open && (
          <button
            type="button"
            aria-label={`刷新目录 ${path || "根目录"}`}
            disabled={loading}
            onClick={() => {
              setLoading(true);
              setPage(null);
              setError(null);
              setRevision((n) => n + 1);
            }}
          >
            刷新
          </button>
        )}
      </div>
      {open && (
        <div className="project-file-tree__children">
          {loading && <p role="status">正在加载目录…</p>}
          {error && <p role="alert">{error}</p>}
          {page && (
            <>
              {page.items.length === 0 && <p>空目录</p>}
              <ul>
                {page.items.map((item) => (
                  <li key={item.path}>
                    {item.kind === "directory" &&
                    item.status === "available" ? (
                      <ProjectFileTree
                        key={`${item.path}:${revision}`}
                        projectId={projectId}
                        load={load}
                        path={item.path}
                        name={item.name}
                        initiallyOpen={false}
                        refreshRevision={refreshRevision}
                        {...(onOpenFile ? { onOpenFile } : {})}
                      />
                    ) : item.kind === "file" &&
                      item.status === "available" &&
                      onOpenFile ? (
                      <button
                        type="button"
                        className="project-file-tree__file"
                        title={item.path}
                        aria-label={`预览文件 ${item.path}`}
                        onClick={() => onOpenFile(item.path)}
                      >
                        {item.name}
                      </button>
                    ) : (
                      <span
                        className="project-file-tree__file"
                        title={item.path}
                      >
                        {item.name}
                        {item.status !== "available" && (
                          <small>
                            {item.status === "ignored" ? "已忽略" : "不可访问"}
                          </small>
                        )}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
              {page.truncated && (
                <p role="status">
                  {page.truncationReason === "time_budget"
                    ? "达到扫描时间限制"
                    : "达到条目数量限制"}
                  ，仅显示部分内容。
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
