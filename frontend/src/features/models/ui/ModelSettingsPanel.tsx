import { useCallback, useEffect, useState, type FormEvent } from "react";

import {
  announceModelSettingsChanged,
  createModelProfile,
  loadModelSettings,
  probeModel,
  saveModelSelection,
  type ModelProbe,
  type ModelProfile,
  type ModelSelection,
} from "@/features/models/api/models";

interface ModelEditorState {
  readonly name: string;
  readonly displayName: string;
  readonly provider: "openai" | "openai-compatible";
  readonly model: string;
  readonly baseUrl: string;
  readonly apiKeyEnv: string;
  readonly apiKey: string;
  readonly supportsTools: boolean;
  readonly supportsReasoning: boolean;
}

const EMPTY_MODEL: ModelEditorState = {
  name: "",
  displayName: "",
  provider: "openai",
  model: "",
  baseUrl: "",
  apiKeyEnv: "",
  apiKey: "",
  supportsTools: true,
  supportsReasoning: false,
};

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : "模型设置请求失败";
}

export function ModelSettingsPanel() {
  const [profiles, setProfiles] = useState<readonly ModelProfile[]>([]);
  const [selection, setSelection] = useState<ModelSelection | null>(null);
  const [profileRevision, setProfileRevision] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editor, setEditor] = useState<ModelEditorState>(EMPTY_MODEL);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState<string | null>(null);
  const [probe, setProbe] = useState<Readonly<Record<string, ModelProbe>>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await loadModelSettings();
      setProfiles(result.profiles);
      setSelection(result.selection);
      setProfileRevision(result.profileRevision);
    } catch (reason) {
      setError(message(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!profileRevision) return;
    setCreating(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createModelProfile(
        {
          name: editor.name.trim(),
          displayName: editor.displayName.trim(),
          provider: editor.provider,
          model: editor.model.trim(),
          baseUrl:
            editor.provider === "openai-compatible"
              ? editor.baseUrl.trim() || null
              : null,
          apiKeyEnv: editor.apiKeyEnv.trim() || null,
          apiKey: editor.apiKey.trim() || null,
          supportsTools: editor.supportsTools,
          supportsReasoning: editor.supportsReasoning,
        },
        profileRevision,
      );
      setProfiles((current) => [...current, created.profile]);
      setProfileRevision(created.profileRevision);
      setEditor(EMPTY_MODEL);
      setShowCreate(false);
      setNotice(
        `已添加模型“${created.profile.displayName}”，现在可以测试连接或设为默认模型。`,
      );
      await load();
      announceModelSettingsChanged();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setCreating(false);
    }
  };

  const save = async () => {
    if (selection === null) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      setSelection(await saveModelSelection(selection));
      announceModelSettingsChanged();
      setNotice("模型选择已保存；当前 Run 不变，下一次 Run 生效。");
    } catch (reason) {
      const failure = message(reason);
      await load();
      setError(failure);
    } finally {
      setSaving(false);
    }
  };

  const test = async (name: string) => {
    setProbing(name);
    setError(null);
    try {
      const result = await probeModel(name);
      setProbe((current) => ({ ...current, [name]: result }));
    } catch (reason) {
      setError(message(reason));
    } finally {
      setProbing(null);
    }
  };

  if (loading && selection === null) {
    return (
      <p className="settings-empty" role="status">
        正在读取模型配置…
      </p>
    );
  }

  return (
    <div className="model-settings">
      <div className="settings-section-heading">
        <div>
          <h3>模型</h3>
          <p>新增或选择主 Agent 与 Goal 评估模型；已保存密钥不会回显。</p>
        </div>
        <div className="model-settings__heading-actions">
          <button
            type="button"
            onClick={() => setShowCreate((value) => !value)}
          >
            {showCreate ? "取消添加" : "添加模型"}
          </button>
          <button type="button" onClick={() => void load()}>
            刷新
          </button>
        </div>
      </div>
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
      {showCreate && (
        <form
          className="model-create-form"
          onSubmit={(event) => void create(event)}
        >
          <div className="model-create-form__grid">
            <label>
              配置名称
              <input
                required
                pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
                maxLength={64}
                placeholder="my-model"
                value={editor.name}
                onChange={(event) =>
                  setEditor({ ...editor, name: event.target.value })
                }
              />
              <small>使用小写字母、数字和连字符，保存后不可重复。</small>
            </label>
            <label>
              显示名称
              <input
                required
                maxLength={100}
                placeholder="My Model"
                value={editor.displayName}
                onChange={(event) =>
                  setEditor({ ...editor, displayName: event.target.value })
                }
              />
            </label>
            <label>
              Provider
              <select
                value={editor.provider}
                onChange={(event) =>
                  setEditor({
                    ...editor,
                    provider: event.target
                      .value as ModelEditorState["provider"],
                  })
                }
              >
                <option value="openai">OpenAI</option>
                <option value="openai-compatible">OpenAI Compatible</option>
              </select>
            </label>
            <label>
              模型 ID
              <input
                required
                maxLength={200}
                placeholder="gpt-5"
                value={editor.model}
                onChange={(event) =>
                  setEditor({ ...editor, model: event.target.value })
                }
              />
            </label>
            {editor.provider === "openai-compatible" && (
              <label className="model-create-form__wide">
                Base URL
                <input
                  required
                  type="url"
                  maxLength={2048}
                  placeholder="http://127.0.0.1:11434/v1"
                  value={editor.baseUrl}
                  onChange={(event) =>
                    setEditor({ ...editor, baseUrl: event.target.value })
                  }
                />
              </label>
            )}
            <label>
              API Key
              <input
                aria-label="API Key"
                type="password"
                autoComplete="new-password"
                maxLength={4096}
                placeholder="可留空，稍后通过环境变量配置"
                value={editor.apiKey}
                onChange={(event) =>
                  setEditor({ ...editor, apiKey: event.target.value })
                }
              />
              <small>填写时仅写入本机凭据存储，页面和读取 API 均不回显。</small>
            </label>
            <label>
              API Key 环境变量（可选）
              <input
                aria-label="API Key 环境变量（可选）"
                pattern="[A-Za-z_][A-Za-z0-9_]*"
                maxLength={128}
                placeholder="留空则自动生成名称"
                value={editor.apiKeyEnv}
                onChange={(event) =>
                  setEditor({ ...editor, apiKeyEnv: event.target.value })
                }
              />
            </label>
          </div>
          <div className="model-create-form__capabilities">
            <label>
              <input
                type="checkbox"
                checked={editor.supportsTools}
                onChange={(event) =>
                  setEditor({ ...editor, supportsTools: event.target.checked })
                }
              />
              支持工具调用
            </label>
            <label>
              <input
                type="checkbox"
                checked={editor.supportsReasoning}
                onChange={(event) =>
                  setEditor({
                    ...editor,
                    supportsReasoning: event.target.checked,
                  })
                }
              />
              支持推理
            </label>
          </div>
          <footer>
            <button type="submit" disabled={creating || !profileRevision}>
              {creating ? "添加中…" : "保存新模型"}
            </button>
          </footer>
        </form>
      )}
      {selection !== null && (
        <div className="model-selection-form">
          <label>
            主 Agent 模型
            <select
              value={selection.primaryModel}
              onChange={(event) =>
                setSelection({ ...selection, primaryModel: event.target.value })
              }
            >
              {profiles.map((item) => (
                <option
                  key={item.name}
                  value={item.name}
                  disabled={!item.supportsTools}
                >
                  {item.displayName}
                  {item.supportsTools ? "" : "（不支持工具）"}
                </option>
              ))}
            </select>
          </label>
          <label>
            Goal 评估模型
            <select
              value={selection.goalModel ?? ""}
              onChange={(event) =>
                setSelection({
                  ...selection,
                  goalModel: event.target.value || null,
                })
              }
            >
              <option value="">跟随主模型</option>
              {profiles.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.displayName}
                </option>
              ))}
            </select>
          </label>
          <button type="button" disabled={saving} onClick={() => void save()}>
            {saving ? "保存中…" : "保存选择"}
          </button>
        </div>
      )}
      <ul className="model-profile-list">
        {profiles.map((item) => (
          <li key={item.name}>
            <div>
              <strong>{item.displayName}</strong>
              <span>{item.provider}</span>
              <span>{item.source === "file" ? "配置文件" : "环境兼容"}</span>
            </div>
            <p>
              {item.model}
              {item.baseUrl !== null ? ` · ${item.baseUrl}` : ""}
            </p>
            <dl>
              <div>
                <dt>API Key</dt>
                <dd>
                  {item.apiKeyConfigured ? "已配置" : `缺失：${item.apiKeyEnv}`}
                </dd>
              </div>
              <div>
                <dt>工具调用</dt>
                <dd>{item.supportsTools ? "支持" : "不支持"}</dd>
              </div>
              <div>
                <dt>推理</dt>
                <dd>{item.supportsReasoning ? "支持" : "未声明"}</dd>
              </div>
            </dl>
            <footer>
              <button
                type="button"
                disabled={probing !== null}
                onClick={() => void test(item.name)}
              >
                {probing === item.name ? "检查中…" : "测试连接"}
              </button>
              {probe[item.name] !== undefined && (
                <span data-ok={probe[item.name]?.ok}>
                  {probe[item.name]?.message}
                </span>
              )}
            </footer>
          </li>
        ))}
      </ul>
    </div>
  );
}
