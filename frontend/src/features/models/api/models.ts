export interface ModelProfile {
  readonly name: string;
  readonly displayName: string;
  readonly provider: string;
  readonly model: string;
  readonly baseUrl: string | null;
  readonly apiKeyEnv: string;
  readonly apiKeyConfigured: boolean;
  readonly supportsTools: boolean;
  readonly supportsReasoning: boolean;
  readonly source: "environment" | "file";
}

export interface ModelSelection {
  readonly primaryModel: string;
  readonly goalModel: string | null;
  readonly revision: number;
}

export interface ModelProbe {
  readonly ok: boolean;
  readonly category: string;
  readonly message: string;
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    try {
      const payload = (await response.json()) as {
        detail?: { message?: string };
      };
      if (payload.detail?.message) message = payload.detail.message;
    } catch {
      // 保留稳定状态提示。
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function loadModelSettings(): Promise<{
  profiles: readonly ModelProfile[];
  selection: ModelSelection;
  profileRevision: string;
}> {
  const [list, selection] = await Promise.all([
    json<{
      models: readonly {
        name: string;
        display_name: string;
        provider: string;
        model: string;
        base_url: string | null;
        api_key_env: string;
        api_key_configured: boolean;
        supports_tools: boolean;
        supports_reasoning: boolean;
        source: "environment" | "file";
      }[];
      profile_revision: string;
    }>(await fetch("/api/v1/models")),
    json<{
      primary_model: string;
      goal_model: string | null;
      revision: number;
    }>(await fetch("/api/v1/settings/model-selection")),
  ]);
  return {
    profiles: list.models.map((item) => ({
      name: item.name,
      displayName: item.display_name,
      provider: item.provider,
      model: item.model,
      baseUrl: item.base_url,
      apiKeyEnv: item.api_key_env,
      apiKeyConfigured: item.api_key_configured,
      supportsTools: item.supports_tools,
      supportsReasoning: item.supports_reasoning,
      source: item.source,
    })),
    selection: {
      primaryModel: selection.primary_model,
      goalModel: selection.goal_model,
      revision: selection.revision,
    },
    profileRevision: list.profile_revision,
  };
}

export async function saveModelSelection(
  value: ModelSelection,
): Promise<ModelSelection> {
  const response = await json<{
    primary_model: string;
    goal_model: string | null;
    revision: number;
  }>(
    await fetch("/api/v1/settings/model-selection", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        primary_model: value.primaryModel,
        goal_model: value.goalModel,
        revision: value.revision,
      }),
    }),
  );
  return {
    primaryModel: response.primary_model,
    goalModel: response.goal_model,
    revision: response.revision,
  };
}

export async function probeModel(name: string): Promise<ModelProbe> {
  return json(
    await fetch(`/api/v1/models/${encodeURIComponent(name)}/probe`, {
      method: "POST",
      headers: { Accept: "application/json" },
    }),
  );
}
