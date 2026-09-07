import type {
  ProjectChange,
  ProjectChangeKind,
  ProjectCheck,
  ProjectCheckStatus,
} from "@/features/chat/model/project-changes";

const CHANGE_LABEL: Record<ProjectChangeKind, string> = {
  created: "新增文件",
  modified: "修改文件",
  directory_created: "新增目录",
  renamed: "重命名",
  moved: "移动文件",
  deleted: "删除文件",
};

const CHECK_LABEL: Record<ProjectCheckStatus, string> = {
  running: "运行中",
  passed: "通过",
  failed: "失败",
  timed_out: "超时",
  cancelled: "已取消",
  unavailable: "未完成",
};

function ChangePath({ change }: { readonly change: ProjectChange }) {
  if (
    change.previousPath !== undefined &&
    change.previousPath !== change.path
  ) {
    return (
      <span className="run-changes__path">
        <code>{change.previousPath}</code>
        <span aria-hidden="true">→</span>
        <code>{change.path}</code>
      </span>
    );
  }
  return <code className="run-changes__path">{change.path}</code>;
}

function diffLines(value: string, prefix: "-" | "+"): string {
  return value
    .split("\n")
    .map((line) => `${prefix} ${line}`)
    .join("\n");
}

function ChangeDiff({ change }: { readonly change: ProjectChange }) {
  if (change.diff === undefined) {
    return null;
  }
  return (
    <details className="run-changes__diff" open>
      <summary>查看差异</summary>
      <div
        className="run-changes__diff-content"
        role="region"
        aria-label={`${change.path} 的改动差异`}
      >
        {change.diff.before !== undefined && (
          <pre data-diff="removed">{diffLines(change.diff.before, "-")}</pre>
        )}
        {change.diff.after !== undefined && (
          <pre data-diff="added">{diffLines(change.diff.after, "+")}</pre>
        )}
        {change.diff.truncated && <small>差异过长，已截断显示</small>}
      </div>
    </details>
  );
}

export function RunChanges({
  changes,
  checks = [],
}: {
  readonly changes: readonly ProjectChange[];
  readonly checks?: readonly ProjectCheck[];
}) {
  if (changes.length === 0 && checks.length === 0) {
    return null;
  }
  return (
    <>
      {changes.length > 0 && (
        <section className="run-changes" aria-label="本轮改动">
          <details open>
            <summary className="run-changes__summary">
              <span>本轮改动</span>
              <span>{changes.length} 项</span>
            </summary>
            <ul className="run-changes__list">
              {changes.map((change) => (
                <li key={change.id} data-kind={change.kind}>
                  <div className="run-changes__item-main">
                    <span className="run-changes__kind">
                      {CHANGE_LABEL[change.kind]}
                    </span>
                    <ChangePath change={change} />
                  </div>
                  <ChangeDiff change={change} />
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}
      {checks.length > 0 && (
        <section className="run-changes" aria-label="检查结果">
          <details open>
            <summary className="run-changes__summary">
              <span>检查结果</span>
              <span>{checks.length} 次</span>
            </summary>
            <ul className="run-changes__list">
              {checks.map((check) => (
                <li key={check.id} data-kind={check.status}>
                  <div className="run-changes__item-main">
                    <span className="run-changes__kind">
                      {CHECK_LABEL[check.status]}
                    </span>
                    <span className="run-changes__path">
                      <code>{check.command}</code>
                      {check.exitCode !== undefined && (
                        <span>exit {check.exitCode}</span>
                      )}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </details>
        </section>
      )}
    </>
  );
}
