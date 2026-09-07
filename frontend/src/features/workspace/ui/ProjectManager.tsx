import { useId, useRef, useState } from "react";

import type { ProjectSummary } from "@/entities/project/model/types";
import type { UseProjectsResult } from "@/features/workspace/model/use-projects";

const STATUS_TEXT: Record<ProjectSummary["status"], string> = {
  available: "可用",
  missing: "目录缺失",
  unavailable: "无法访问",
  changed: "目录已替换",
};
const STATUS_HINT: Record<ProjectSummary["status"], string> = {
  available: "",
  missing: "请确认原目录位置，再刷新状态。",
  unavailable: "请检查目录权限、允许范围或链接目录后再刷新。",
  changed: "当前位置的目录身份已变化，请先核对原项目。",
};

/** 确认仅针对当前项目；取消不发请求，失败时保留确认内容供用户核对。 */
function UnregisterAction({
  project,
  busy,
  onUnregister,
}: {
  readonly project: ProjectSummary;
  readonly busy: boolean;
  readonly onUnregister: (project: ProjectSummary) => Promise<boolean>;
}) {
  const [confirming, setConfirming] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  return (
    <div className="project-unregister">
      <button
        ref={trigger}
        type="button"
        className="project-button"
        disabled={busy}
        aria-expanded={confirming}
        aria-controls={confirming ? id : undefined}
        onClick={() => setConfirming(!confirming)}
      >
        解除登记
      </button>
      {confirming && (
        <div
          id={id}
          className="project-unregister__confirmation"
          role="group"
          aria-label={`解除“${project.name}”的登记`}
        >
          <p>解除“{project.name}”的登记？原目录及文件会保留。</p>
          <div className="project-unregister__actions">
            <button
              type="button"
              className="project-button"
              disabled={busy}
              onClick={() => {
                setConfirming(false);
                trigger.current?.focus();
              }}
            >
              取消
            </button>
            <button
              type="button"
              className="project-button project-button--primary"
              disabled={busy}
              onClick={() => void onUnregister(project)}
            >
              确认解除登记
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** 登记表单只管理用户输入，成功与否以服务端返回为准。 */
function RegistrationForm({
  busy,
  onRegister,
}: {
  readonly busy: boolean;
  readonly onRegister: (name: string, path: string) => Promise<boolean>;
}) {
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const id = useId();
  return (
    <form
      className="project-form"
      onSubmit={async (event) => {
        event.preventDefault();
        if (await onRegister(name, path)) {
          setName("");
          setPath("");
        }
      }}
    >
      <h3>登记已有项目</h3>
      <label htmlFor={`${id}-name`}>项目名称</label>
      <input
        id={`${id}-name`}
        value={name}
        onChange={(event) => setName(event.target.value)}
        maxLength={80}
        required
        disabled={busy}
        placeholder="例如：学习项目"
      />
      <label htmlFor={`${id}-path`}>项目目录</label>
      <input
        id={`${id}-path`}
        value={path}
        onChange={(event) => setPath(event.target.value)}
        maxLength={4096}
        required
        disabled={busy}
        placeholder="D:/projects/my-project"
        spellCheck={false}
        aria-describedby={`${id}-hint`}
      />
      <p id={`${id}-hint`}>
        填写后端运行机器上的绝对目录，目录需已存在并位于允许范围内。
      </p>
      <button
        type="submit"
        className="project-button project-button--primary"
        disabled={busy || !name.trim() || !path.trim()}
      >
        {busy ? "处理中…" : "登记项目"}
      </button>
    </form>
  );
}

/** 项目管理仅负责登记、刷新和移除，项目事实从 API 查询。 */
export function ProjectManager({
  projects,
}: {
  readonly projects: UseProjectsResult;
}) {
  const refreshButton = useRef<HTMLButtonElement>(null);
  const id = useId();
  const busy = projects.pending !== null;
  return (
    <div className="project-manager">
      <p className="project-manager__intro">
        登记已有目录，集中查看项目路径与可用状态。当前项目均为只读。
      </p>
      {projects.error !== null && (
        <p className="project-feedback project-feedback--error" role="alert">
          {projects.error}
        </p>
      )}
      {projects.notice !== null && (
        <p className="project-feedback" role="status">
          {projects.notice}
        </p>
      )}
      <>
        <div className="project-manager__toolbar">
          <span>本地项目</span>
          <button
            ref={refreshButton}
            className="project-button"
            type="button"
            disabled={busy}
            onClick={() => void projects.refresh()}
          >
            刷新项目
          </button>
        </div>
        <div className="project-manager__columns">
          <section
            className="project-registry"
            aria-labelledby={`${id}-list-title`}
            aria-busy={busy}
          >
            <div className="project-registry__heading">
              <h3 id={`${id}-list-title`}>已登记项目</h3>
              <span>已加载 {projects.items.length} 个</span>
            </div>
            {busy && <p role="status">正在更新项目…</p>}
            {projects.items.length === 0 && (
              <div className="project-empty">
                <strong>还没有登记项目</strong>
                <p>填写项目名称与目录，添加第一个只读项目。</p>
              </div>
            )}
            <ul className="project-list">
              {projects.items.map((project) => (
                <li key={project.projectId} className="project-item">
                  <div className="project-item__heading">
                    <strong>{project.name}</strong>
                    <span
                      className="project-status"
                      data-status={project.status}
                    >
                      {STATUS_TEXT[project.status]}
                    </span>
                  </div>
                  <p className="project-item__path">{project.rootPath}</p>
                  <div className="project-item__meta">
                    <span>只读</span>
                    <time dateTime={project.updatedAt}>
                      状态更新{" "}
                      {new Date(project.updatedAt).toLocaleString("zh-CN")}
                    </time>
                  </div>
                  {STATUS_HINT[project.status] && (
                    <p className="project-item__hint">
                      {STATUS_HINT[project.status]}
                    </p>
                  )}
                  <UnregisterAction
                    project={project}
                    busy={busy}
                    onUnregister={async (target) => {
                      const activeElement = document.activeElement;
                      const success = await projects.unregister(target);
                      // 删除卡片后把焦点交回刷新入口；用户已离开面板时不抢焦点。
                      if (success && document.activeElement === activeElement)
                        refreshButton.current?.focus();
                      return success;
                    }}
                  />
                </li>
              ))}
            </ul>
            {projects.nextOffset !== null && (
              <button
                type="button"
                className="project-button"
                disabled={busy}
                onClick={() => void projects.loadMore()}
              >
                加载更多项目
              </button>
            )}
          </section>
          <RegistrationForm busy={busy} onRegister={projects.register} />
        </div>
      </>
    </div>
  );
}
