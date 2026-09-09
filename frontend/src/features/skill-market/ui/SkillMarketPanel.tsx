import { useMemo, useState, type FormEvent } from "react";

interface MarketSkill {
  provider: string;
  remote_id: string;
  name: string;
  version: string | null;
  description: string;
  publisher: string;
  license: string | null;
  tags: readonly string[];
  canonical_url: string;
  required_tools: readonly string[];
  runtime_requirements: readonly string[];
  scan_status: string;
  changelog: string | null;
  published_at: string | null;
  compatible: boolean;
  compatibility_reason: string;
  file_paths: readonly string[];
  package_size: number | null;
}

interface MarketVersion {
  version: string;
  changelog: string | null;
  published_at: string | null;
}

interface MarketChangePreview {
  confirmation_token: string;
  action: "install" | "update";
  name: string;
  current_version: string | null;
  target_version: string | null;
  content_hash: string;
  enabled_after: boolean;
  allowed_tools_before: readonly string[] | null;
  allowed_tools_after: readonly string[] | null;
  added_tools: readonly string[];
  removed_tools: readonly string[];
  permission_changed: boolean;
  description_changed: boolean;
  instructions_changed: boolean;
  resources_changed: boolean;
  risk_warnings: readonly string[];
  expires_at: string;
}

interface PendingChange {
  item: MarketSkill;
  preview: MarketChangePreview;
}

interface MarketHistory {
  history_id: string;
  action: string;
  version: string | null;
  created_at: string;
}

function toolsLabel(value: readonly string[] | null): string {
  if (value === null) return "继承当前 Agent 可用工具";
  return value.length === 0 ? "不使用工具" : value.join("、");
}

export function SkillMarketPanel() {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<readonly MarketSkill[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cache, setCache] = useState<{
    fromCache: boolean;
    syncedAt: string | null;
  } | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [installed, setInstalled] = useState<Readonly<Record<string, string>>>(
    {},
  );
  const [settingsRevision, setSettingsRevision] = useState(0);
  const [history, setHistory] = useState<
    Readonly<Record<string, readonly MarketHistory[]>>
  >({});
  const [publisher, setPublisher] = useState("");
  const [tag, setTag] = useState("");
  const [compatibility, setCompatibility] = useState<
    "all" | "compatible" | "incompatible"
  >("all");
  const [pending, setPending] = useState<PendingChange | null>(null);
  const [versions, setVersions] = useState<
    Readonly<Record<string, readonly MarketVersion[]>>
  >({});
  const [selectedVersions, setSelectedVersions] = useState<
    Readonly<Record<string, string>>
  >({});
  const publishers = useMemo(
    () => [...new Set(items.map((item) => item.publisher))].sort(),
    [items],
  );
  const visibleItems = useMemo(
    () =>
      items.filter(
        (item) =>
          (!publisher || item.publisher === publisher) &&
          (!tag.trim() ||
            item.tags.some((value) =>
              value
                .toLocaleLowerCase()
                .includes(tag.trim().toLocaleLowerCase()),
            )) &&
          (compatibility === "all" ||
            item.compatible === (compatibility === "compatible")),
      ),
    [compatibility, items, publisher, tag],
  );

  const search = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const [response, installedResponse] = await Promise.all([
        fetch(
          `/api/v1/skill-market/catalog?q=${encodeURIComponent(query.trim())}&refresh=true`,
        ),
        fetch("/api/v1/skills", { headers: { Accept: "application/json" } }),
      ]);
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: { message?: string };
        };
        throw new Error(
          payload.detail?.message ?? `市场请求失败（HTTP ${response.status}）`,
        );
      }
      const payload = (await response.json()) as {
        items: readonly MarketSkill[];
        synced_at: string | null;
        from_cache: boolean;
      };
      setItems(payload.items);
      setCache({ fromCache: payload.from_cache, syncedAt: payload.synced_at });
      if (installedResponse.ok) {
        const local = (await installedResponse.json()) as {
          skills: readonly { name: string; source: string }[];
          revision: number;
        };
        setInstalled(
          Object.fromEntries(
            local.skills.map((item) => [item.name, item.source]),
          ),
        );
        setSettingsRevision(local.revision);
      }
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Skill 市场暂时不可用",
      );
    } finally {
      setLoading(false);
    }
  };

  const prepare = async (item: MarketSkill, enabled = true) => {
    const updating = installed[item.name] === "market";
    setInstalling(item.remote_id);
    setError(null);
    setNotice(null);
    try {
      const [owner, slug] = item.remote_id.split("/", 2);
      if (!owner || !slug) throw new Error("市场下载引用无效");
      const response = await fetch(
        `/api/v1/skill-market/items/${encodeURIComponent(item.provider)}/${encodeURIComponent(owner)}/${encodeURIComponent(slug)}/preview`,
        {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            action: updating ? "update" : "install",
            version: selectedVersions[item.remote_id] || null,
            enabled,
          }),
        },
      );
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: { message?: string };
        };
        throw new Error(
          payload.detail?.message ?? `安装失败（HTTP ${response.status}）`,
        );
      }
      setPending({
        item,
        preview: (await response.json()) as MarketChangePreview,
      });
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "市场 Skill 预检失败",
      );
    } finally {
      setInstalling(null);
    }
  };

  const loadVersions = async (item: MarketSkill) => {
    setInstalling(item.remote_id);
    setError(null);
    try {
      const [owner, slug] = item.remote_id.split("/", 2);
      if (!owner || !slug) throw new Error("市场下载引用无效");
      const response = await fetch(
        `/api/v1/skill-market/items/${encodeURIComponent(item.provider)}/${encodeURIComponent(owner)}/${encodeURIComponent(slug)}/versions`,
      );
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: { message?: string };
        };
        throw new Error(
          payload.detail?.message ?? `版本请求失败（HTTP ${response.status}）`,
        );
      }
      const payload = (await response.json()) as {
        versions: readonly MarketVersion[];
      };
      setVersions((current) => ({
        ...current,
        [item.remote_id]: payload.versions,
      }));
      if (payload.versions[0] !== undefined) {
        setSelectedVersions((current) => ({
          ...current,
          [item.remote_id]:
            current[item.remote_id] ?? payload.versions[0]!.version,
        }));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取市场版本");
    } finally {
      setInstalling(null);
    }
  };

  const loadDetail = async (item: MarketSkill) => {
    setInstalling(item.remote_id);
    setError(null);
    try {
      const [owner, slug] = item.remote_id.split("/", 2);
      if (!owner || !slug) throw new Error("市场下载引用无效");
      const response = await fetch(
        `/api/v1/skill-market/items/${encodeURIComponent(item.provider)}/${encodeURIComponent(owner)}/${encodeURIComponent(slug)}`,
      );
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: { message?: string };
        };
        throw new Error(
          payload.detail?.message ?? `详情请求失败（HTTP ${response.status}）`,
        );
      }
      const detail = (await response.json()) as MarketSkill;
      setItems((current) =>
        current.map((candidate) =>
          candidate.provider === item.provider &&
          candidate.remote_id === item.remote_id
            ? detail
            : candidate,
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "无法读取市场 Skill 详情",
      );
    } finally {
      setInstalling(null);
    }
  };

  const apply = async () => {
    if (pending === null) return;
    const { item, preview } = pending;
    setInstalling(item.remote_id);
    setError(null);
    try {
      const [owner, slug] = item.remote_id.split("/", 2);
      if (!owner || !slug) throw new Error("市场下载引用无效");
      const response = await fetch(
        `/api/v1/skill-market/items/${encodeURIComponent(item.provider)}/${encodeURIComponent(owner)}/${encodeURIComponent(slug)}/${preview.action}`,
        {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            confirmation_token: preview.confirmation_token,
          }),
        },
      );
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: { message?: string };
        };
        throw new Error(
          payload.detail?.message ?? `提交失败（HTTP ${response.status}）`,
        );
      }
      setInstalled((current) => ({ ...current, [item.name]: "market" }));
      setSettingsRevision((current) => current + 1);
      setPending(null);
      setNotice(
        `已${preview.action === "update" ? "更新" : "安装"} ${item.name}，下一次 Run 生效。`,
      );
    } catch (reason) {
      setPending(null);
      setError(
        reason instanceof Error
          ? reason.message
          : "市场 Skill 提交失败，请重新预检",
      );
    } finally {
      setInstalling(null);
    }
  };

  const loadHistory = async (item: MarketSkill) => {
    setInstalling(item.remote_id);
    setError(null);
    try {
      const response = await fetch(
        `/api/v1/skills/${encodeURIComponent(item.name)}/history`,
      );
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: { message?: string };
        };
        throw new Error(
          payload.detail?.message ?? `历史请求失败（HTTP ${response.status}）`,
        );
      }
      const payload = (await response.json()) as {
        history: readonly MarketHistory[];
      };
      setHistory((current) => ({
        ...current,
        [item.remote_id]: payload.history,
      }));
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "无法读取市场 Skill 历史",
      );
    } finally {
      setInstalling(null);
    }
  };

  const rollback = async (item: MarketSkill, historyId: string) => {
    setInstalling(item.remote_id);
    setError(null);
    try {
      const [owner, slug] = item.remote_id.split("/", 2);
      if (!owner || !slug) throw new Error("市场下载引用无效");
      const response = await fetch(
        `/api/v1/skill-market/items/${encodeURIComponent(item.provider)}/${encodeURIComponent(owner)}/${encodeURIComponent(slug)}/rollback`,
        {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            history_id: historyId,
            revision: settingsRevision,
          }),
        },
      );
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: { message?: string };
        };
        throw new Error(
          payload.detail?.message ?? `回滚失败（HTTP ${response.status}）`,
        );
      }
      setSettingsRevision((current) => current + 1);
      setInstalled((current) => ({ ...current, [item.name]: "market" }));
      setHistory((current) => {
        const next = { ...current };
        delete next[item.remote_id];
        return next;
      });
      setNotice(`已回滚 ${item.name}，下一次 Run 生效。`);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "市场 Skill 回滚失败",
      );
    } finally {
      setInstalling(null);
    }
  };

  const uninstall = async (item: MarketSkill) => {
    if (!window.confirm(`卸载市场 Skill“${item.name}”？历史版本仍可恢复。`))
      return;
    setInstalling(item.remote_id);
    setError(null);
    try {
      const [owner, slug] = item.remote_id.split("/", 2);
      if (!owner || !slug) throw new Error("市场下载引用无效");
      const response = await fetch(
        `/api/v1/skill-market/items/${encodeURIComponent(item.provider)}/${encodeURIComponent(owner)}/${encodeURIComponent(slug)}/installation?revision=${settingsRevision}`,
        {
          method: "DELETE",
          headers: { Accept: "application/json" },
        },
      );
      if (!response.ok) {
        const payload = (await response.json()) as {
          detail?: { message?: string };
        };
        throw new Error(
          payload.detail?.message ?? `卸载失败（HTTP ${response.status}）`,
        );
      }
      setInstalled((current) => {
        const next = { ...current };
        delete next[item.name];
        return next;
      });
      setSettingsRevision((current) => current + 1);
      setNotice(`已卸载 ${item.name}，下一次 Run 生效。`);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "市场 Skill 卸载失败",
      );
    } finally {
      setInstalling(null);
    }
  };

  return (
    <div className="skill-market">
      <form onSubmit={(event) => void search(event)}>
        <label>
          <span className="sr-only">搜索 Skill 市场</span>
          <input
            value={query}
            placeholder="搜索名称、描述或标签"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <button type="submit" disabled={loading || !query.trim()}>
          {loading ? "搜索中…" : "搜索"}
        </button>
      </form>
      {cache !== null && (
        <p className="skill-market__sync" data-cache={cache.fromCache}>
          {cache.fromCache ? "正在显示离线缓存" : "已同步 ClawHub"}
          {cache.syncedAt !== null
            ? ` · ${new Date(cache.syncedAt).toLocaleString("zh-CN")}`
            : ""}
        </p>
      )}
      {items.length > 0 && (
        <div className="skill-market__filters" aria-label="市场筛选">
          <label>
            类别或标签
            <input
              value={tag}
              onChange={(event) => setTag(event.target.value)}
            />
          </label>
          <label>
            发布者
            <select
              value={publisher}
              onChange={(event) => setPublisher(event.target.value)}
            >
              <option value="">全部</option>
              {publishers.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            兼容性
            <select
              value={compatibility}
              onChange={(event) =>
                setCompatibility(event.target.value as typeof compatibility)
              }
            >
              <option value="all">全部</option>
              <option value="compatible">兼容</option>
              <option value="incompatible">不兼容</option>
            </select>
          </label>
        </div>
      )}
      {error !== null && (
        <p className="settings-inline-error" role="alert">
          {error}
        </p>
      )}
      {notice !== null && (
        <p className="settings-inline-notice" role="status">
          {notice}
        </p>
      )}
      {pending !== null && (
        <section
          className="skill-market-confirmation"
          aria-label="Skill 变更确认"
        >
          <header>
            <div>
              <strong>
                {pending.preview.action === "update" ? "确认更新" : "确认安装"}{" "}
                {pending.preview.name}
              </strong>
              <p>
                {pending.preview.current_version ?? "未安装"} →{" "}
                {pending.preview.target_version ?? "latest"}
              </p>
            </div>
            <button type="button" onClick={() => setPending(null)}>
              取消
            </button>
          </header>
          <dl>
            <div>
              <dt>预检内容哈希</dt>
              <dd>
                <code>{pending.preview.content_hash}</code>
              </dd>
            </div>
            <div>
              <dt>安装后状态</dt>
              <dd>{pending.preview.enabled_after ? "启用" : "停用"}</dd>
            </div>
            <div data-changed={pending.preview.permission_changed}>
              <dt>原工具权限</dt>
              <dd>{toolsLabel(pending.preview.allowed_tools_before)}</dd>
            </div>
            <div data-changed={pending.preview.permission_changed}>
              <dt>新工具权限</dt>
              <dd>{toolsLabel(pending.preview.allowed_tools_after)}</dd>
            </div>
            <div>
              <dt>新增工具</dt>
              <dd>{pending.preview.added_tools.join("、") || "无"}</dd>
            </div>
            <div>
              <dt>本地风险提示</dt>
              <dd>
                {pending.preview.risk_warnings?.join("；") || "未发现静态风险"}
              </dd>
            </div>
            <div>
              <dt>内容变化</dt>
              <dd>
                {[
                  pending.preview.description_changed ? "描述" : "",
                  pending.preview.instructions_changed ? "指令" : "",
                  pending.preview.resources_changed ? "资源" : "",
                ]
                  .filter(Boolean)
                  .join("、") ||
                  (pending.preview.action === "install" ? "新安装" : "无")}
              </dd>
            </div>
          </dl>
          <p>确认令牌只绑定本次已校验内容，十分钟内有效且只能使用一次。</p>
          <button
            type="button"
            disabled={installing !== null}
            onClick={() => void apply()}
          >
            {installing !== null
              ? "提交中…"
              : pending.preview.permission_changed
                ? "确认权限变化并提交"
                : "确认提交"}
          </button>
        </section>
      )}
      <ul className="skill-market__list">
        {visibleItems.map((item) => (
          <li key={`${item.provider}:${item.remote_id}`}>
            <div>
              <strong>{item.name}</strong>
              <span>{item.publisher}</span>
              <span data-compatible={item.compatible}>
                {item.compatible ? "可检查安装" : "不兼容"}
              </span>
            </div>
            <p>{item.description}</p>
            <dl>
              <div>
                <dt>版本</dt>
                <dd>{item.version ?? "latest"}</dd>
              </div>
              <div>
                <dt>许可证</dt>
                <dd>{item.license ?? "未声明"}</dd>
              </div>
              <div>
                <dt>扫描</dt>
                <dd>{item.scan_status}</dd>
              </div>
              <div>
                <dt>更新说明</dt>
                <dd>{item.changelog ?? "未提供"}</dd>
              </div>
              <div>
                <dt>发布时间</dt>
                <dd>
                  {item.published_at === null
                    ? "未提供"
                    : new Date(item.published_at).toLocaleString("zh-CN")}
                </dd>
              </div>
              <div>
                <dt>工具</dt>
                <dd>{item.required_tools.join("、") || "未声明"}</dd>
              </div>
              <div>
                <dt>包大小</dt>
                <dd>
                  {item.package_size === null || item.package_size === undefined
                    ? "预检时确认"
                    : `${item.package_size} B`}
                </dd>
              </div>
              <div>
                <dt>运行时</dt>
                <dd>{item.runtime_requirements.join("、") || "无额外要求"}</dd>
              </div>
              <div>
                <dt>资源清单</dt>
                <dd>
                  {(item.file_paths?.length ?? 0) === 0
                    ? "预检时确认"
                    : item.file_paths.join("、")}
                </dd>
              </div>
            </dl>
            {versions[item.remote_id] !== undefined && (
              <label className="skill-market__version">
                安装版本
                <select
                  value={selectedVersions[item.remote_id] ?? ""}
                  onChange={(event) =>
                    setSelectedVersions((current) => ({
                      ...current,
                      [item.remote_id]: event.target.value,
                    }))
                  }
                >
                  {versions[item.remote_id]?.map((version) => (
                    <option key={version.version} value={version.version}>
                      {version.version}
                    </option>
                  ))}
                </select>
                <small>
                  {versions[item.remote_id]?.find(
                    (version) =>
                      version.version === selectedVersions[item.remote_id],
                  )?.changelog ?? "未提供更新说明"}
                </small>
              </label>
            )}
            <p className="skill-market__compatibility">
              {item.compatibility_reason}
            </p>
            <footer>
              <a href={item.canonical_url} target="_blank" rel="noreferrer">
                查看 ClawHub 来源
              </a>
              <button
                type="button"
                disabled={installing !== null}
                onClick={() => void loadDetail(item)}
              >
                刷新详情
              </button>
              <button
                type="button"
                disabled={installing !== null}
                onClick={() => void loadVersions(item)}
              >
                选择版本
              </button>
              <button
                type="button"
                disabled={
                  !item.compatible ||
                  installing !== null ||
                  (installed[item.name] !== undefined &&
                    installed[item.name] !== "market")
                }
                onClick={() => void prepare(item)}
              >
                {installing === item.remote_id
                  ? "预检中…"
                  : installed[item.name] === "market"
                    ? "检查并更新"
                    : installed[item.name] !== undefined
                      ? "名称已被本地 Skill 使用"
                      : "检查安装并启用"}
              </button>
              {installed[item.name] === undefined && (
                <button
                  type="button"
                  disabled={!item.compatible || installing !== null}
                  onClick={() => void prepare(item, false)}
                >
                  检查安装但暂不启用
                </button>
              )}
              {installed[item.name] !== "user" && (
                <button
                  type="button"
                  disabled={installing !== null}
                  onClick={() => void loadHistory(item)}
                >
                  {installed[item.name] === "market" ? "回滚版本" : "恢复历史"}
                </button>
              )}
              {installed[item.name] === "market" && (
                <button
                  type="button"
                  className="danger"
                  disabled={installing !== null}
                  onClick={() => void uninstall(item)}
                >
                  卸载
                </button>
              )}
            </footer>
            {history[item.remote_id] !== undefined && (
              <div className="skill-market__history">
                <strong>选择历史版本</strong>
                {history[item.remote_id]?.map((entry) => (
                  <button
                    type="button"
                    key={entry.history_id}
                    disabled={installing !== null}
                    onClick={() => void rollback(item, entry.history_id)}
                  >
                    {entry.version ?? entry.action} ·{" "}
                    {new Date(entry.created_at).toLocaleString("zh-CN")}
                  </button>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
