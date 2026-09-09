import { useEffect, useState } from "react";

import {
  loadModelSettings,
  probeModel,
  saveModelSelection,
  type ModelProbe,
  type ModelProfile,
  type ModelSelection,
} from "@/features/models/api/models";

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : "模型设置请求失败";
}

export function ModelSettingsPanel() {
  const [profiles, setProfiles] = useState<readonly ModelProfile[]>([]);
  const [selection, setSelection] = useState<ModelSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState<string | null>(null);
  const [probe, setProbe] = useState<Readonly<Record<string, ModelProbe>>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    void loadModelSettings()
      .then((result) => {
        setProfiles(result.profiles);
        setSelection(result.selection);
      })
      .catch((reason: unknown) => setError(message(reason)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    queueMicrotask(load);
  }, []);

  const save = async () => {
    if (selection === null) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      setSelection(await saveModelSelection(selection));
      setNotice("模型选择已保存；当前 Run 不变，下一次 Run 生效。");
    } catch (reason) {
      setError(message(reason));
      load();
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
          <p>选择主 Agent 与 Goal 评估模型；密钥不会发送到浏览器。</p>
        </div>
        <button type="button" onClick={load}>
          刷新
        </button>
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
