export type SkillSource = "builtin" | "user" | "market";

export interface SkillSummary {
  readonly name: string;
  readonly description: string;
  readonly source: SkillSource;
  readonly enabled: boolean;
  readonly editable: boolean;
  readonly allowedTools: readonly string[] | null;
  readonly resourcePaths: readonly string[];
  readonly resourceCount: number;
  readonly modifiedAt: string;
  readonly checkStatus: "valid";
}

interface SkillSummaryResponse {
  readonly name: string;
  readonly description: string;
  readonly source: SkillSource;
  readonly enabled: boolean;
  readonly editable: boolean;
  readonly allowed_tools: readonly string[] | null;
  readonly resource_paths: readonly string[];
  readonly resource_count: number;
  readonly modified_at: string;
  readonly check_status: "valid";
}

interface SkillListResponse {
  readonly skills: readonly SkillSummaryResponse[];
  readonly revision: number;
}

export interface SkillList {
  readonly skills: readonly SkillSummary[];
  readonly revision: number;
}

export interface SkillResource {
  readonly path: string;
  readonly content: string;
}

export interface SkillDetail {
  readonly name: string;
  readonly description: string;
  readonly source: SkillSource;
  readonly editable: boolean;
  readonly enabled: boolean;
  readonly allowedTools: readonly string[] | null;
  readonly instructions: string;
  readonly resources: readonly SkillResource[];
  readonly revision: number;
}

export interface SkillDraftInput {
  readonly name: string;
  readonly description: string;
  readonly instructions: string;
  readonly allowedTools: readonly string[] | null;
  readonly resources?: readonly SkillResource[];
}

export interface SkillDraft extends SkillDraftInput {
  readonly draftId: string;
  readonly revision: number;
}

export interface SkillCheck {
  readonly valid: boolean;
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
  readonly contentHash: string | null;
}

export interface SkillInstallAuthorization {
  readonly authorizationToken: string;
  readonly expectedName: string;
  readonly expiresAt: string;
}

export interface SkillAgentSettings {
  readonly creationEnabled: boolean;
  readonly revision: number;
}

export interface SkillHistory {
  readonly historyId: string;
  readonly action: "install" | "update" | "delete" | "rollback" | "import";
  readonly author: string;
  readonly createdAt: string;
  readonly description: string;
  readonly version: string | null;
}

export interface RecoverableSkill {
  readonly name: string;
  readonly historyId: string;
  readonly description: string;
  readonly source: "user" | "market";
  readonly version: string | null;
  readonly deletedAt: string;
}

function requestInit(method: string, body?: unknown): RequestInit {
  const result: RequestInit = {
    method,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
  };
  if (body !== undefined) result.body = JSON.stringify(body);
  return result;
}

async function requireJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    try {
      const payload = (await response.json()) as {
        detail?: { message?: string };
      };
      if (payload.detail?.message) message = payload.detail.message;
    } catch {
      // 非 JSON 错误沿用稳定的 HTTP 状态提示。
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function mapDetail(payload: {
  name: string;
  description: string;
  source: SkillSource;
  editable: boolean;
  enabled: boolean;
  allowed_tools: readonly string[] | null;
  instructions: string;
  resources: readonly SkillResource[];
  revision: number;
}): SkillDetail {
  return {
    name: payload.name,
    description: payload.description,
    source: payload.source,
    editable: payload.editable,
    enabled: payload.enabled,
    allowedTools: payload.allowed_tools,
    instructions: payload.instructions,
    resources: payload.resources,
    revision: payload.revision,
  };
}

export async function listSkills(signal?: AbortSignal): Promise<SkillList> {
  const request: RequestInit = { headers: { Accept: "application/json" } };
  if (signal !== undefined) request.signal = signal;
  const response = await fetch("/api/v1/skills", {
    ...request,
  });
  if (!response.ok)
    throw new Error(`无法读取 Skill 清单（HTTP ${response.status}）`);
  const payload = (await response.json()) as SkillListResponse;
  return {
    skills: payload.skills.map((skill) => ({
      name: skill.name,
      description: skill.description,
      source: skill.source,
      enabled: skill.enabled,
      editable: skill.editable,
      allowedTools: skill.allowed_tools,
      resourcePaths: skill.resource_paths,
      resourceCount: skill.resource_count,
      modifiedAt: skill.modified_at,
      checkStatus: skill.check_status,
    })),
    revision: payload.revision,
  };
}

export async function getSkill(name: string): Promise<SkillDetail> {
  return mapDetail(
    await requireJson(
      await fetch(`/api/v1/skills/${encodeURIComponent(name)}`),
    ),
  );
}

export async function setSkillEnabled(
  name: string,
  enabled: boolean,
  revision: number,
): Promise<void> {
  await requireJson(
    await fetch(
      `/api/v1/skills/${encodeURIComponent(name)}`,
      requestInit("PATCH", { enabled, revision }),
    ),
  );
}

export async function createSkillDraft(
  input: SkillDraftInput,
): Promise<SkillDraft> {
  const payload = await requireJson<{
    draft_id: string;
    revision: number;
    name: string;
    description: string;
    instructions: string;
    allowed_tools: readonly string[] | null;
    resources: readonly SkillResource[];
  }>(
    await fetch(
      "/api/v1/skills/drafts",
      requestInit("POST", {
        name: input.name,
        description: input.description,
        instructions: input.instructions,
        allowed_tools: input.allowedTools,
        resources: input.resources ?? [],
      }),
    ),
  );
  return {
    draftId: payload.draft_id,
    revision: payload.revision,
    name: payload.name,
    description: payload.description,
    instructions: payload.instructions,
    allowedTools: payload.allowed_tools,
    resources: payload.resources,
  };
}

export async function updateSkillDraft(
  draft: SkillDraft,
  input: SkillDraftInput,
): Promise<SkillDraft> {
  const payload = await requireJson<{
    draft_id: string;
    revision: number;
    name: string;
    description: string;
    instructions: string;
    allowed_tools: readonly string[] | null;
    resources: readonly SkillResource[];
  }>(
    await fetch(
      `/api/v1/skills/drafts/${encodeURIComponent(draft.draftId)}`,
      requestInit("PUT", {
        name: input.name,
        description: input.description,
        instructions: input.instructions,
        allowed_tools: input.allowedTools,
        resources: input.resources ?? [],
        revision: draft.revision,
      }),
    ),
  );
  return {
    draftId: payload.draft_id,
    revision: payload.revision,
    name: payload.name,
    description: payload.description,
    instructions: payload.instructions,
    allowedTools: payload.allowed_tools,
    resources: payload.resources,
  };
}

export async function listSkillDrafts(): Promise<readonly SkillDraft[]> {
  const payload = await requireJson<{
    drafts: readonly {
      draft_id: string;
      revision: number;
      name: string;
      description: string;
      version?: string | null;
      instructions: string;
      allowed_tools: readonly string[] | null;
      resources: readonly SkillResource[];
    }[];
  }>(await fetch("/api/v1/skills/drafts"));
  return payload.drafts.map((item) => ({
    draftId: item.draft_id,
    revision: item.revision,
    name: item.name,
    description: item.description,
    version: item.version ?? null,
    instructions: item.instructions,
    allowedTools: item.allowed_tools,
    resources: item.resources,
  }));
}

export async function checkSkillDraft(draftId: string): Promise<SkillCheck> {
  const payload = await requireJson<{
    valid: boolean;
    errors: readonly string[];
    warnings: readonly string[];
    content_hash: string | null;
  }>(
    await fetch(`/api/v1/skills/drafts/${draftId}/check`, requestInit("POST")),
  );
  return {
    valid: payload.valid,
    errors: payload.errors,
    warnings: payload.warnings,
    contentHash: payload.content_hash,
  };
}

export async function installSkillDraft(
  draft: SkillDraft,
  settingsRevision: number,
): Promise<SkillDetail> {
  return mapDetail(
    await requireJson(
      await fetch(
        `/api/v1/skills/drafts/${draft.draftId}/install`,
        requestInit("POST", {
          revision: draft.revision,
          settings_revision: settingsRevision,
          enabled: true,
        }),
      ),
    ),
  );
}

export async function createSkillInstallAuthorization(input: {
  readonly threadId: string;
  readonly expectedName: string;
  readonly requirement: string;
}): Promise<SkillInstallAuthorization> {
  const payload = await requireJson<{
    authorization_token: string;
    expected_name: string;
    expires_at: string;
  }>(
    await fetch(
      "/api/v1/skills/install-authorizations",
      requestInit("POST", {
        thread_id: input.threadId,
        expected_name: input.expectedName,
        requirement: input.requirement,
      }),
    ),
  );
  return {
    authorizationToken: payload.authorization_token,
    expectedName: payload.expected_name,
    expiresAt: payload.expires_at,
  };
}

export async function getSkillAgentSettings(): Promise<SkillAgentSettings> {
  const payload = await requireJson<{
    creation_enabled: boolean;
    revision: number;
  }>(await fetch("/api/v1/skills/agent-settings"));
  return {
    creationEnabled: payload.creation_enabled,
    revision: payload.revision,
  };
}

export async function saveSkillAgentSettings(
  settings: SkillAgentSettings,
): Promise<SkillAgentSettings> {
  const payload = await requireJson<{
    creation_enabled: boolean;
    revision: number;
  }>(
    await fetch(
      "/api/v1/skills/agent-settings",
      requestInit("PUT", {
        creation_enabled: settings.creationEnabled,
        revision: settings.revision,
      }),
    ),
  );
  return {
    creationEnabled: payload.creation_enabled,
    revision: payload.revision,
  };
}

export async function importSkillArchive(file: File): Promise<SkillDraft> {
  const response = await fetch("/api/v1/skills/import", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/zip" },
    body: file,
  });
  const payload = await requireJson<{
    draft_id: string;
    revision: number;
    name: string;
    description: string;
    instructions: string;
    allowed_tools: readonly string[] | null;
    resources: readonly SkillResource[];
  }>(response);
  return {
    draftId: payload.draft_id,
    revision: payload.revision,
    name: payload.name,
    description: payload.description,
    instructions: payload.instructions,
    allowedTools: payload.allowed_tools,
    resources: payload.resources,
  };
}

export async function deleteSkill(
  name: string,
  revision: number,
): Promise<void> {
  const response = await fetch(
    `/api/v1/skills/${encodeURIComponent(name)}?revision=${revision}`,
    { method: "DELETE", headers: { Accept: "application/json" } },
  );
  if (!response.ok) await requireJson(response);
}

export async function listSkillHistory(
  name: string,
): Promise<readonly SkillHistory[]> {
  const payload = await requireJson<{
    history: readonly {
      history_id: string;
      action: SkillHistory["action"];
      author: string;
      created_at: string;
      description: string;
      version: string | null;
    }[];
  }>(await fetch(`/api/v1/skills/${encodeURIComponent(name)}/history`));
  return payload.history.map((item) => ({
    historyId: item.history_id,
    action: item.action,
    author: item.author,
    createdAt: item.created_at,
    description: item.description,
    version: item.version ?? null,
  }));
}

export async function listRecoverableSkills(): Promise<
  readonly RecoverableSkill[]
> {
  const payload = await requireJson<{
    skills: readonly {
      name: string;
      history_id: string;
      description: string;
      source: "user" | "market";
      version: string | null;
      deleted_at: string;
    }[];
  }>(await fetch("/api/v1/skills/recoverable"));
  return payload.skills.map((item) => ({
    name: item.name,
    historyId: item.history_id,
    description: item.description,
    source: item.source,
    version: item.version,
    deletedAt: item.deleted_at,
  }));
}

export async function getSkillHistoryVersion(
  name: string,
  historyId: string,
): Promise<SkillDetail> {
  return mapDetail(
    await requireJson(
      await fetch(
        `/api/v1/skills/${encodeURIComponent(name)}/history/${encodeURIComponent(historyId)}`,
      ),
    ),
  );
}

export async function rollbackSkill(
  name: string,
  historyId: string,
  revision: number,
): Promise<SkillDetail> {
  return mapDetail(
    await requireJson(
      await fetch(
        `/api/v1/skills/${encodeURIComponent(name)}/rollback`,
        requestInit("POST", { history_id: historyId, revision }),
      ),
    ),
  );
}
