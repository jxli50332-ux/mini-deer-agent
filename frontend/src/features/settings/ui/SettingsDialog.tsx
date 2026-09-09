import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";

import {
  checkSkillDraft,
  createSkillDraft,
  deleteSkill,
  getSkill,
  getSkillHistoryVersion,
  getSkillAgentSettings,
  importSkillArchive,
  installSkillDraft,
  listSkillHistory,
  listRecoverableSkills,
  listSkillDrafts,
  listSkills,
  rollbackSkill,
  saveSkillAgentSettings,
  setSkillEnabled,
  updateSkillDraft,
  type SkillCheck,
  type SkillDraft,
  type SkillHistory,
  type SkillDetail,
  type SkillResource,
  type SkillAgentSettings,
  type SkillSummary,
  type RecoverableSkill,
} from "@/features/skills/api/skills";
import { ModelSettingsPanel } from "@/features/models/ui/ModelSettingsPanel";
import { SkillMarketPanel } from "@/features/skill-market/ui/SkillMarketPanel";

interface SettingsDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onStartSkillCreation?: (
    mode: "balanced" | "guided" | "automatic",
    requirement: string,
    expectedName?: string,
  ) => void | Promise<void>;
}

type SettingsTab = "skills" | "models";
type SkillView = "list" | "editor" | "detail";

interface EditorState {
  readonly originalName: string | null;
  readonly name: string;
  readonly description: string;
  readonly instructions: string;
  readonly allowedTools: string;
  readonly resources: readonly SkillResource[];
}

const EMPTY_EDITOR: EditorState = {
  originalName: null,
  name: "",
  description: "",
  instructions: "",
  allowedTools: "",
  resources: [],
};

function sourceLabel(skill: SkillSummary): string {
  if (skill.source === "builtin") return "内置";
  return skill.source === "market" ? "市场" : "用户";
}

function permissionLabel(skill: SkillSummary): string {
  if (skill.allowedTools === null) return "继承 Agent 工具";
  if (skill.allowedTools.length === 0) return "不使用工具";
  return skill.allowedTools.join("、");
}

function errorText(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

export function SettingsDialog({
  open,
  onClose,
  onStartSkillCreation,
}: SettingsDialogProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("skills");
  const [view, setView] = useState<SkillView>("list");
  const [skillArea, setSkillArea] = useState<"installed" | "market" | "drafts">(
    "installed",
  );
  const [skills, setSkills] = useState<readonly SkillSummary[]>([]);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busyName, setBusyName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState>(EMPTY_EDITOR);
  const [draft, setDraft] = useState<SkillDraft | null>(null);
  const [check, setCheck] = useState<SkillCheck | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [history, setHistory] = useState<readonly SkillHistory[]>([]);
  const [currentDetail, setCurrentDetail] = useState<SkillDetail | null>(null);
  const [historyDetail, setHistoryDetail] = useState<SkillDetail | null>(null);
  const [recoverable, setRecoverable] = useState<readonly RecoverableSkill[]>(
    [],
  );
  const [drafts, setDrafts] = useState<readonly SkillDraft[]>([]);
  const [creationMode, setCreationMode] = useState<
    "balanced" | "guided" | "automatic"
  >("balanced");
  const [creationRequirement, setCreationRequirement] = useState("");
  const [creationName, setCreationName] = useState("");
  const [agentSettings, setAgentSettings] = useState<SkillAgentSettings | null>(
    null,
  );
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback((controller = new AbortController()) => {
    setLoading(true);
    setError(null);
    void Promise.all([listSkills(controller.signal), listRecoverableSkills()])
      .then(([result, deleted]) => {
        setSkills(result.skills);
        setRevision(result.revision);
        setRecoverable(deleted);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        setError(errorText(reason, "无法读取 Skill 清单"));
      })
      .finally(() => setLoading(false));
    return controller;
  }, []);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) load(controller);
    });
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      controller.abort();
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [load, open, onClose]);

  if (!open) return null;

  const beginCreate = () => {
    setEditor(EMPTY_EDITOR);
    setDraft(null);
    setCheck(null);
    setError(null);
    setNotice(null);
    setView("editor");
  };

  const showDrafts = async () => {
    setSkillArea("drafts");
    setLoading(true);
    setError(null);
    try {
      const [nextDrafts, nextSettings] = await Promise.all([
        listSkillDrafts(),
        getSkillAgentSettings(),
      ]);
      setDrafts(nextDrafts);
      setAgentSettings(nextSettings);
    } catch (reason) {
      setError(errorText(reason, "无法读取 Skill 草稿"));
    } finally {
      setLoading(false);
    }
  };

  const toggleAgentCreation = async () => {
    if (agentSettings === null) return;
    setLoading(true);
    setError(null);
    try {
      setAgentSettings(
        await saveSkillAgentSettings({
          ...agentSettings,
          creationEnabled: !agentSettings.creationEnabled,
        }),
      );
    } catch (reason) {
      setError(errorText(reason, "无法更新 Agent Skill 创作设置"));
    } finally {
      setLoading(false);
    }
  };

  const openDraft = async (item: SkillDraft) => {
    setEditor({
      originalName: null,
      name: item.name,
      description: item.description,
      instructions: item.instructions,
      allowedTools: item.allowedTools?.join(", ") ?? "",
      resources: item.resources ?? [],
    });
    setDraft(item);
    setCheck(await checkSkillDraft(item.draftId));
    setSkillArea("installed");
    setView("editor");
  };

  const openDetail = async (name: string) => {
    setBusyName(name);
    setError(null);
    try {
      const [detail, versions] = await Promise.all([
        getSkill(name),
        listSkillHistory(name),
      ]);
      setSelectedName(name);
      setEditor({
        originalName: detail.editable ? name : null,
        name: detail.name,
        description: detail.description,
        instructions: detail.instructions,
        allowedTools: detail.allowedTools?.join(", ") ?? "",
        resources: detail.resources,
      });
      setHistory(versions);
      setCurrentDetail(detail);
      setHistoryDetail(null);
      setDraft(null);
      setCheck(null);
      setView("detail");
    } catch (reason) {
      setError(errorText(reason, "无法读取 Skill 详情"));
    } finally {
      setBusyName(null);
    }
  };

  const submitCheck = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusyName(editor.name || "draft");
    setError(null);
    setNotice(null);
    try {
      const payload = {
        name: editor.name.trim(),
        description: editor.description.trim(),
        instructions: editor.instructions.trim(),
        allowedTools:
          editor.allowedTools.trim().length === 0
            ? null
            : editor.allowedTools
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
        resources: editor.resources,
      };
      const created =
        draft === null
          ? await createSkillDraft(payload)
          : await updateSkillDraft(draft, payload);
      const result = await checkSkillDraft(created.draftId);
      setDraft(created);
      setCheck(result);
      setNotice(result.valid ? "检查通过，请确认保存。" : null);
    } catch (reason) {
      setError(errorText(reason, "无法检查 Skill 草稿"));
    } finally {
      setBusyName(null);
    }
  };

  const confirmInstall = async () => {
    if (draft === null || check?.valid !== true) return;
    setBusyName(draft.name);
    setError(null);
    try {
      await installSkillDraft(draft, revision);
      setNotice(`已保存 Skill“${draft.name}”，将在下一次 Run 生效。`);
      setView("list");
      setDraft(null);
      setCheck(null);
      load();
    } catch (reason) {
      setError(errorText(reason, "无法保存 Skill"));
    } finally {
      setBusyName(null);
    }
  };

  const toggle = async (skill: SkillSummary) => {
    setBusyName(skill.name);
    setError(null);
    try {
      await setSkillEnabled(skill.name, !skill.enabled, revision);
      setNotice(
        `${skill.name} 已${skill.enabled ? "停用" : "启用"}，下一次 Run 生效。`,
      );
      load();
    } catch (reason) {
      setError(errorText(reason, "无法更新 Skill 状态"));
      load();
    } finally {
      setBusyName(null);
    }
  };

  const removeSelected = async () => {
    if (
      selectedName === null ||
      !window.confirm(`删除 Skill“${selectedName}”？可从历史恢复。`)
    ) {
      return;
    }
    setBusyName(selectedName);
    setError(null);
    try {
      await deleteSkill(selectedName, revision);
      setNotice(`已删除 Skill“${selectedName}”。`);
      setView("list");
      setSelectedName(null);
      load();
    } catch (reason) {
      setError(errorText(reason, "无法删除 Skill"));
    } finally {
      setBusyName(null);
    }
  };

  const restore = async (item: SkillHistory) => {
    if (selectedName === null) return;
    setBusyName(selectedName);
    setError(null);
    try {
      await rollbackSkill(selectedName, item.historyId, revision);
      setNotice(`已恢复 ${selectedName} 的所选版本，下一次 Run 生效。`);
      await openDetail(selectedName);
      load();
    } catch (reason) {
      setError(errorText(reason, "无法回滚 Skill"));
    } finally {
      setBusyName(null);
    }
  };

  const restoreDeleted = async (item: RecoverableSkill) => {
    setBusyName(item.name);
    setError(null);
    try {
      await rollbackSkill(item.name, item.historyId, revision);
      setNotice(`已恢复 ${item.name}，将在下一次 Run 生效。`);
      load();
    } catch (reason) {
      setError(errorText(reason, "无法恢复已删除 Skill"));
      load();
    } finally {
      setBusyName(null);
    }
  };

  const inspectHistory = async (item: SkillHistory) => {
    if (selectedName === null) return;
    setBusyName(selectedName);
    setError(null);
    try {
      setHistoryDetail(
        await getSkillHistoryVersion(selectedName, item.historyId),
      );
    } catch (reason) {
      setError(errorText(reason, "无法读取 Skill 历史版本"));
    } finally {
      setBusyName(null);
    }
  };

  const importArchive = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file === undefined) return;
    setBusyName(file.name);
    setError(null);
    try {
      const imported = await importSkillArchive(file);
      const result = await checkSkillDraft(imported.draftId);
      setEditor({
        originalName: null,
        name: imported.name,
        description: imported.description,
        instructions: imported.instructions,
        allowedTools: imported.allowedTools?.join(", ") ?? "",
        resources: imported.resources ?? [],
      });
      setDraft(imported);
      setCheck(result);
      setView("editor");
      setNotice(
        result.valid
          ? `归档“${file.name}”检查通过，请确认安装。`
          : `归档“${file.name}”检查未通过。`,
      );
    } catch (reason) {
      setError(errorText(reason, "无法导入 Skill 归档"));
    } finally {
      setBusyName(null);
    }
  };

  const isEditing = editor.originalName !== null;

  const copyMarketSkill = () => {
    const suffix = "-custom";
    const copiedName = `${editor.name.slice(0, 64 - suffix.length).replace(/-+$/, "")}${suffix}`;
    setEditor({ ...editor, originalName: null, name: copiedName });
    setDraft(null);
    setCheck(null);
    setHistoryDetail(null);
    setView("editor");
  };

  return (
    <div className="settings-overlay" role="presentation" onMouseDown={onClose}>
      <section
        className="settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="settings-dialog__header">
          <div>
            <p>应用级配置</p>
            <h2 id="settings-title">设置</h2>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            className="settings-dialog__close"
            aria-label="关闭设置"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className="settings-dialog__layout">
          <nav className="settings-tabs" aria-label="设置分类">
            <button
              type="button"
              aria-current={activeTab === "skills" ? "page" : undefined}
              onClick={() => setActiveTab("skills")}
            >
              Skills
            </button>
            <button
              type="button"
              aria-current={activeTab === "models" ? "page" : undefined}
              onClick={() => setActiveTab("models")}
            >
              模型
            </button>
          </nav>
          <main className="settings-dialog__content">
            {activeTab === "skills" ? (
              <>
                <div
                  className="skill-area-tabs"
                  role="tablist"
                  aria-label="Skills 子页"
                >
                  <button
                    type="button"
                    role="tab"
                    aria-selected={skillArea === "installed"}
                    onClick={() => setSkillArea("installed")}
                  >
                    已安装
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={skillArea === "market"}
                    onClick={() => setSkillArea("market")}
                  >
                    市场
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={skillArea === "drafts"}
                    onClick={() => void showDrafts()}
                  >
                    草稿
                  </button>
                </div>
                {skillArea === "market" ? (
                  <SkillMarketPanel />
                ) : skillArea === "drafts" ? (
                  <div className="skill-draft-list">
                    <div className="settings-section-heading">
                      <div>
                        <h3>Skill 草稿</h3>
                        <p>Agent 可搜索市场并生成草稿；安装仍由设置页确认。</p>
                      </div>
                    </div>
                    {agentSettings !== null && (
                      <label className="skill-agent-toggle">
                        <input
                          type="checkbox"
                          checked={agentSettings.creationEnabled}
                          onChange={() => void toggleAgentCreation()}
                        />
                        允许 Agent 创建 Skill 草稿
                      </label>
                    )}
                    <form
                      className="skill-ai-creator"
                      onSubmit={(event) => {
                        event.preventDefault();
                        const requirement = creationRequirement.trim();
                        const expectedName = creationName.trim();
                        if (
                          onStartSkillCreation === undefined ||
                          !requirement ||
                          (creationMode === "automatic" && !expectedName)
                        )
                          return;
                        setLoading(true);
                        setError(null);
                        const start =
                          creationMode === "automatic"
                            ? onStartSkillCreation(
                                creationMode,
                                requirement,
                                expectedName,
                              )
                            : onStartSkillCreation(creationMode, requirement);
                        const complete = () => {
                          setCreationRequirement("");
                          setCreationName("");
                          onClose();
                          setLoading(false);
                        };
                        if (start instanceof Promise) {
                          void start.then(complete).catch((reason: unknown) => {
                            setError(errorText(reason, "无法开始 Skill 创作"));
                            setLoading(false);
                          });
                        } else {
                          complete();
                        }
                      }}
                    >
                      <label>
                        AI 创建模式
                        <select
                          value={creationMode}
                          onChange={(event) =>
                            setCreationMode(
                              event.target.value as typeof creationMode,
                            )
                          }
                        >
                          <option value="balanced">平衡模式</option>
                          <option value="guided">逐步引导</option>
                          <option value="automatic">自动完成草稿</option>
                        </select>
                      </label>
                      {creationMode === "automatic" && (
                        <label>
                          新 Skill 名称
                          <input
                            value={creationName}
                            pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                            maxLength={64}
                            placeholder="meeting-actions"
                            onChange={(event) =>
                              setCreationName(event.target.value)
                            }
                          />
                          <small>
                            自动授权仅允许在当前任务安装这个全新名称，且只能使用一次。
                          </small>
                        </label>
                      )}
                      <label>
                        需求
                        <textarea
                          value={creationRequirement}
                          placeholder="例如：把会议记录整理为决定、行动项和负责人"
                          onChange={(event) =>
                            setCreationRequirement(event.target.value)
                          }
                        />
                      </label>
                      <button
                        type="submit"
                        disabled={
                          loading ||
                          agentSettings?.creationEnabled === false ||
                          onStartSkillCreation === undefined ||
                          !creationRequirement.trim() ||
                          (creationMode === "automatic" && !creationName.trim())
                        }
                      >
                        在当前对话开始创作
                      </button>
                    </form>
                    {loading ? (
                      <p className="settings-empty">读取中…</p>
                    ) : drafts.length === 0 ? (
                      <p className="settings-empty">没有草稿。</p>
                    ) : (
                      <ul>
                        {drafts.map((item) => (
                          <li key={item.draftId}>
                            <span>
                              <strong>{item.name}</strong>
                              <small>{item.description}</small>
                            </span>
                            <button
                              type="button"
                              onClick={() => void openDraft(item)}
                            >
                              检查并确认
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ) : (
                  <>
                    <div className="settings-section-heading">
                      <div>
                        <h3>
                          {view === "list"
                            ? "已安装 Skills"
                            : view === "editor"
                              ? isEditing
                                ? `编辑 ${editor.name}`
                                : "新建 Skill"
                              : editor.name}
                        </h3>
                        <p>Skill 变更只影响之后启动的 Run。</p>
                      </div>
                      <div className="settings-section-actions">
                        {view !== "list" && (
                          <button type="button" onClick={() => setView("list")}>
                            返回清单
                          </button>
                        )}
                        {view === "list" && (
                          <>
                            <input
                              ref={importInputRef}
                              type="file"
                              accept=".skill,.zip,application/zip"
                              hidden
                              onChange={(event) => void importArchive(event)}
                            />
                            <button
                              type="button"
                              onClick={() => importInputRef.current?.click()}
                            >
                              导入 .skill
                            </button>
                            <button type="button" onClick={beginCreate}>
                              新建 Skill
                            </button>
                            <button
                              type="button"
                              disabled={loading}
                              onClick={() => load()}
                            >
                              {loading ? "刷新中…" : "刷新"}
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                    {error !== null && (
                      <div className="settings-inline-error" role="alert">
                        <span>{error}</span>
                        <button type="button" onClick={() => setError(null)}>
                          关闭
                        </button>
                      </div>
                    )}
                    {notice !== null && (
                      <p className="settings-inline-notice" role="status">
                        {notice}
                      </p>
                    )}

                    {view === "list" && (
                      <>
                        {loading && skills.length === 0 && (
                          <p className="settings-empty" role="status">
                            正在读取 Skill 清单…
                          </p>
                        )}
                        {!loading && error === null && skills.length === 0 && (
                          <p className="settings-empty">还没有可用的 Skill。</p>
                        )}
                        <ul className="skill-settings-list">
                          {skills.map((skill) => (
                            <li key={`${skill.source}:${skill.name}`}>
                              <div className="skill-settings-list__title">
                                <button
                                  type="button"
                                  className="skill-settings-list__name"
                                  disabled={busyName === skill.name}
                                  onClick={() => void openDetail(skill.name)}
                                >
                                  {skill.name}
                                </button>
                                <span data-source={skill.source}>
                                  {sourceLabel(skill)}
                                </span>
                                <span data-enabled={skill.enabled}>
                                  {skill.enabled ? "已启用" : "已停用"}
                                </span>
                                <button
                                  type="button"
                                  className="skill-toggle"
                                  disabled={busyName !== null}
                                  aria-pressed={skill.enabled}
                                  onClick={() => void toggle(skill)}
                                >
                                  {skill.enabled ? "停用" : "启用"}
                                </button>
                              </div>
                              <p>{skill.description}</p>
                              <dl>
                                <div>
                                  <dt>可编辑</dt>
                                  <dd>
                                    {skill.editable ? "是" : "否（只读）"}
                                  </dd>
                                </div>
                                <div>
                                  <dt>工具</dt>
                                  <dd>{permissionLabel(skill)}</dd>
                                </div>
                                <div>
                                  <dt>资源</dt>
                                  <dd>{skill.resourceCount} 个</dd>
                                </div>
                                <div>
                                  <dt>最近修改</dt>
                                  <dd>
                                    {new Date(skill.modifiedAt).toLocaleString(
                                      "zh-CN",
                                    )}
                                  </dd>
                                </div>
                                <div>
                                  <dt>检查</dt>
                                  <dd>
                                    {skill.checkStatus === "valid"
                                      ? "通过"
                                      : skill.checkStatus}
                                  </dd>
                                </div>
                              </dl>
                            </li>
                          ))}
                        </ul>
                        {recoverable.length > 0 && (
                          <section
                            className="recoverable-skills"
                            aria-label="可恢复的已删除 Skills"
                          >
                            <h4>可恢复的已删除 Skills</h4>
                            <ul>
                              {recoverable.map((item) => (
                                <li key={item.name}>
                                  <span>
                                    <strong>{item.name}</strong>
                                    <small>
                                      {item.source === "market"
                                        ? "市场"
                                        : "用户"}
                                      {item.version !== null
                                        ? ` · ${item.version}`
                                        : ""}{" "}
                                      ·{" "}
                                      {new Date(item.deletedAt).toLocaleString(
                                        "zh-CN",
                                      )}
                                    </small>
                                  </span>
                                  <button
                                    type="button"
                                    disabled={busyName !== null}
                                    onClick={() => void restoreDeleted(item)}
                                  >
                                    恢复
                                  </button>
                                </li>
                              ))}
                            </ul>
                          </section>
                        )}
                      </>
                    )}

                    {view === "editor" && (
                      <form
                        className="skill-editor"
                        onSubmit={(event) => void submitCheck(event)}
                      >
                        <label>
                          名称
                          <input
                            value={editor.name}
                            readOnly={isEditing}
                            pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                            required
                            onChange={(event) =>
                              setEditor({ ...editor, name: event.target.value })
                            }
                          />
                        </label>
                        <label>
                          描述
                          <input
                            value={editor.description}
                            maxLength={500}
                            required
                            onChange={(event) =>
                              setEditor({
                                ...editor,
                                description: event.target.value,
                              })
                            }
                          />
                        </label>
                        <label>
                          allowed-tools（逗号分隔，留空表示继承）
                          <input
                            value={editor.allowedTools}
                            onChange={(event) =>
                              setEditor({
                                ...editor,
                                allowedTools: event.target.value,
                              })
                            }
                          />
                        </label>
                        <label>
                          Skill 指令
                          <textarea
                            value={editor.instructions}
                            required
                            onChange={(event) =>
                              setEditor({
                                ...editor,
                                instructions: event.target.value,
                              })
                            }
                          />
                        </label>
                        <fieldset className="skill-resource-editor">
                          <legend>文本资源（仅 references/）</legend>
                          {editor.resources.map((resource, index) => (
                            <div key={`${index}:${resource.path}`}>
                              <input
                                aria-label={`资源 ${index + 1} 路径`}
                                value={resource.path}
                                placeholder="references/example.md"
                                onChange={(event) =>
                                  setEditor({
                                    ...editor,
                                    resources: editor.resources.map(
                                      (item, itemIndex) =>
                                        itemIndex === index
                                          ? {
                                              ...item,
                                              path: event.target.value,
                                            }
                                          : item,
                                    ),
                                  })
                                }
                              />
                              <textarea
                                aria-label={`资源 ${index + 1} 内容`}
                                value={resource.content}
                                onChange={(event) =>
                                  setEditor({
                                    ...editor,
                                    resources: editor.resources.map(
                                      (item, itemIndex) =>
                                        itemIndex === index
                                          ? {
                                              ...item,
                                              content: event.target.value,
                                            }
                                          : item,
                                    ),
                                  })
                                }
                              />
                              <button
                                type="button"
                                onClick={() =>
                                  setEditor({
                                    ...editor,
                                    resources: editor.resources.filter(
                                      (_, itemIndex) => itemIndex !== index,
                                    ),
                                  })
                                }
                              >
                                删除资源
                              </button>
                            </div>
                          ))}
                          <button
                            type="button"
                            disabled={editor.resources.length >= 16}
                            onClick={() =>
                              setEditor({
                                ...editor,
                                resources: [
                                  ...editor.resources,
                                  { path: "references/", content: "" },
                                ],
                              })
                            }
                          >
                            添加资源
                          </button>
                        </fieldset>
                        {check !== null && (
                          <div
                            className="skill-check"
                            data-valid={check.valid}
                            role="status"
                          >
                            <strong>
                              {check.valid ? "确定性检查通过" : "检查未通过"}
                            </strong>
                            {check.contentHash !== null && (
                              <code>{check.contentHash.slice(0, 16)}…</code>
                            )}
                            {check.errors.map((item) => (
                              <p key={item}>{item}</p>
                            ))}
                            {check.warnings.map((item) => (
                              <p key={item}>提示：{item}</p>
                            ))}
                          </div>
                        )}
                        <div className="skill-editor__actions">
                          <button type="submit" disabled={busyName !== null}>
                            {busyName !== null ? "检查中…" : "检查并预览"}
                          </button>
                          <button
                            type="button"
                            disabled={
                              check?.valid !== true || busyName !== null
                            }
                            onClick={() => void confirmInstall()}
                          >
                            {isEditing ? "确认保存" : "确认安装"}
                          </button>
                        </div>
                      </form>
                    )}

                    {view === "detail" && (
                      <div className="skill-detail">
                        <div className="skill-detail__actions">
                          {editor.originalName !== null && (
                            <button
                              type="button"
                              onClick={() => {
                                setDraft(null);
                                setCheck(null);
                                setView("editor");
                              }}
                            >
                              编辑
                            </button>
                          )}
                          {skills.find((item) => item.name === selectedName)
                            ?.source === "market" && (
                            <button type="button" onClick={copyMarketSkill}>
                              复制为用户 Skill
                            </button>
                          )}
                          {editor.originalName !== null && (
                            <button
                              type="button"
                              className="danger"
                              onClick={() => void removeSelected()}
                            >
                              删除
                            </button>
                          )}
                          {skills.find((item) => item.name === selectedName)
                            ?.source === "market" && (
                            <button
                              type="button"
                              className="danger"
                              onClick={() => void removeSelected()}
                            >
                              卸载
                            </button>
                          )}
                        </div>
                        <p>{editor.description}</p>
                        <h4>指令正文</h4>
                        <pre>{editor.instructions}</pre>
                        <h4>资源</h4>
                        <pre>
                          {editor.resources
                            .map((item) => item.path)
                            .join("\n") || "无"}
                        </pre>
                        <h4>历史版本</h4>
                        {history.length === 0 ? (
                          <p className="settings-empty">没有历史记录。</p>
                        ) : (
                          <ul className="skill-history-list">
                            {history.map((item) => (
                              <li key={item.historyId}>
                                <span>
                                  <strong>
                                    {item.action}
                                    {item.version !== null
                                      ? ` · ${item.version}`
                                      : ""}
                                  </strong>
                                  <small>
                                    {new Date(item.createdAt).toLocaleString(
                                      "zh-CN",
                                    )}{" "}
                                    · {item.author}
                                  </small>
                                </span>
                                <span>
                                  <button
                                    type="button"
                                    disabled={busyName !== null}
                                    onClick={() => void inspectHistory(item)}
                                  >
                                    查看 Diff
                                  </button>
                                  <button
                                    type="button"
                                    disabled={busyName !== null}
                                    onClick={() => void restore(item)}
                                  >
                                    回滚到此版本
                                  </button>
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                        {historyDetail !== null && currentDetail !== null && (
                          <section
                            className="skill-history-diff"
                            aria-label="Skill 历史版本 Diff"
                          >
                            <header>
                              <h4>历史版本与当前版本 Diff</h4>
                              <button
                                type="button"
                                onClick={() => setHistoryDetail(null)}
                              >
                                关闭
                              </button>
                            </header>
                            <div
                              data-changed={
                                historyDetail.description !==
                                currentDetail.description
                              }
                            >
                              <h5>描述</h5>
                              <pre>{historyDetail.description}</pre>
                              <pre>{currentDetail.description}</pre>
                            </div>
                            <div
                              data-changed={
                                historyDetail.instructions !==
                                currentDetail.instructions
                              }
                            >
                              <h5>指令正文</h5>
                              <pre>{historyDetail.instructions}</pre>
                              <pre>{currentDetail.instructions}</pre>
                            </div>
                            <div
                              data-changed={
                                JSON.stringify(historyDetail.resources) !==
                                JSON.stringify(currentDetail.resources)
                              }
                            >
                              <h5>资源</h5>
                              <pre>
                                {historyDetail.resources
                                  .map(
                                    (item) => `${item.path}\n${item.content}`,
                                  )
                                  .join("\n\n") || "无"}
                              </pre>
                              <pre>
                                {currentDetail.resources
                                  .map(
                                    (item) => `${item.path}\n${item.content}`,
                                  )
                                  .join("\n\n") || "无"}
                              </pre>
                            </div>
                          </section>
                        )}
                      </div>
                    )}
                  </>
                )}
              </>
            ) : (
              <ModelSettingsPanel />
            )}
          </main>
        </div>
      </section>
    </div>
  );
}
