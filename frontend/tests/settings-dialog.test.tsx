import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsDialog } from "@/features/settings/ui/SettingsDialog";

describe("SettingsDialog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("展示内置与用户 Skill 的来源和可编辑性", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((request: RequestInfo | URL) => {
        const url =
          typeof request === "string"
            ? request
            : request instanceof URL
              ? request.href
              : request.url;
        return Promise.resolve(
          Response.json(
            url.endsWith("/api/v1/skills/recoverable")
              ? { skills: [] }
              : {
                  skills: [
                    {
                      name: "structured-explainer",
                      description: "生成结构清晰的解释。",
                      source: "builtin",
                      enabled: true,
                      editable: false,
                      allowed_tools: [],
                      resource_paths: [],
                      resource_count: 0,
                      modified_at: "2026-09-09T00:00:00Z",
                      check_status: "valid",
                    },
                    {
                      name: "custom-review",
                      description: "使用自定义检查清单。",
                      source: "user",
                      enabled: false,
                      editable: true,
                      allowed_tools: ["read_file"],
                      resource_paths: ["references/checklist.md"],
                      resource_count: 1,
                      modified_at: "2026-09-09T00:00:00Z",
                      check_status: "valid",
                    },
                  ],
                  revision: 0,
                },
          ),
        );
      }),
    );

    render(<SettingsDialog open onClose={vi.fn()} />);

    expect(await screen.findByText("structured-explainer")).toBeVisible();
    expect(screen.getByText("custom-review")).toBeVisible();
    expect(screen.getByText("否（只读）")).toBeVisible();
    expect(screen.getByText("是")).toBeVisible();
    expect(screen.getByText("已停用")).toBeVisible();
  });

  it("支持切换模型页签、显示安全元数据和关闭", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((request: RequestInfo | URL) => {
        const url =
          typeof request === "string"
            ? request
            : request instanceof URL
              ? request.href
              : request.url;
        if (url.endsWith("/api/v1/models")) {
          return Promise.resolve(
            Response.json({
              models: [
                {
                  name: "primary-openai",
                  display_name: "Primary OpenAI",
                  provider: "openai",
                  model: "gpt-5",
                  base_url: null,
                  api_key_env: "MINI_DEER_API_KEY",
                  api_key_configured: true,
                  supports_tools: true,
                  supports_reasoning: true,
                  source: "file",
                },
              ],
              profile_revision: "profile-hash",
            }),
          );
        }
        if (url.endsWith("/api/v1/settings/model-selection")) {
          return Promise.resolve(
            Response.json({
              primary_model: "primary-openai",
              goal_model: null,
              revision: 0,
            }),
          );
        }
        return Promise.resolve(Response.json({ skills: [], revision: 0 }));
      }),
    );
    const onClose = vi.fn();
    render(<SettingsDialog open onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "模型" }));
    expect(
      (await screen.findAllByText("Primary OpenAI")).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("已配置")).toBeVisible();
    expect(screen.queryByText("MINI_DEER_API_KEY")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭设置" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("市场 Skill 保持只读并可复制为新用户 Skill", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((request: RequestInfo | URL) => {
        const url =
          typeof request === "string"
            ? request
            : request instanceof URL
              ? request.href
              : request.url;
        if (url.endsWith("/api/v1/skills/meeting-notes/history")) {
          return Promise.resolve(Response.json({ history: [] }));
        }
        if (url.endsWith("/api/v1/skills/recoverable")) {
          return Promise.resolve(Response.json({ skills: [] }));
        }
        if (url.endsWith("/api/v1/skills/meeting-notes")) {
          return Promise.resolve(
            Response.json({
              name: "meeting-notes",
              description: "整理会议记录。",
              source: "market",
              editable: false,
              enabled: true,
              allowed_tools: [],
              instructions: "提取行动项。",
              resources: [{ path: "references/template.md", content: "模板" }],
              revision: 2,
            }),
          );
        }
        return Promise.resolve(
          Response.json({
            skills: [
              {
                name: "meeting-notes",
                description: "整理会议记录。",
                source: "market",
                enabled: true,
                editable: false,
                allowed_tools: [],
                resource_paths: ["references/template.md"],
                resource_count: 1,
                modified_at: "2026-09-09T00:00:00Z",
                check_status: "valid",
              },
            ],
            revision: 2,
          }),
        );
      }),
    );
    render(<SettingsDialog open onClose={vi.fn()} />);

    fireEvent.click(
      await screen.findByRole("button", { name: "meeting-notes" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "复制为用户 Skill" }),
    );

    expect(screen.getByLabelText("名称")).toHaveValue("meeting-notes-custom");
    expect(screen.getByLabelText("Skill 指令")).toHaveValue("提取行动项。");
  });

  it("从保留的历史快照恢复已删除 Skill", async () => {
    const fetcher = vi.fn((request: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof request === "string"
          ? request
          : request instanceof URL
            ? request.href
            : request.url;
      if (url.endsWith("/api/v1/skills/recoverable")) {
        return Promise.resolve(
          Response.json({
            skills: [
              {
                name: "deleted-skill",
                history_id: "history-id",
                description: "可恢复",
                source: "user",
                version: null,
                deleted_at: "2026-09-09T00:00:00Z",
              },
            ],
          }),
        );
      }
      if (url.endsWith("/api/v1/skills/deleted-skill/rollback")) {
        if (typeof init?.body !== "string")
          throw new Error("expected JSON body");
        expect(JSON.parse(init.body)).toEqual({
          history_id: "history-id",
          revision: 0,
        });
        return Promise.resolve(Response.json({ name: "deleted-skill" }));
      }
      return Promise.resolve(Response.json({ skills: [], revision: 0 }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SettingsDialog open onClose={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "恢复" }));
    expect(
      await screen.findByText("已恢复 deleted-skill，将在下一次 Run 生效。"),
    ).toBeVisible();
  });

  it("把 AI Skill 创作模式和需求送入当前对话", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((request: RequestInfo | URL) => {
        const url =
          typeof request === "string"
            ? request
            : request instanceof URL
              ? request.href
              : request.url;
        return Promise.resolve(
          Response.json(
            url.endsWith("/api/v1/skills/drafts")
              ? { drafts: [] }
              : url.endsWith("/api/v1/skills/agent-settings")
                ? { creation_enabled: true, revision: 0 }
                : { skills: [], revision: 0 },
          ),
        );
      }),
    );
    const onStart = vi.fn();
    const onClose = vi.fn();
    render(
      <SettingsDialog open onClose={onClose} onStartSkillCreation={onStart} />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "草稿" }));
    fireEvent.change(await screen.findByLabelText("AI 创建模式"), {
      target: { value: "guided" },
    });
    fireEvent.change(screen.getByLabelText("需求"), {
      target: { value: "整理会议行动项" },
    });
    fireEvent.click(screen.getByRole("button", { name: "在当前对话开始创作" }));

    expect(onStart).toHaveBeenCalledWith("guided", "整理会议行动项");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("关闭自动安装后仍允许创建待人工确认的 Skill 草稿", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((request: RequestInfo | URL) => {
        const url =
          typeof request === "string"
            ? request
            : request instanceof URL
              ? request.href
              : request.url;
        return Promise.resolve(
          Response.json(
            url.endsWith("/api/v1/skills/drafts")
              ? { drafts: [] }
              : url.endsWith("/api/v1/skills/agent-settings")
                ? { creation_enabled: false, revision: 1 }
                : { skills: [], revision: 0 },
          ),
        );
      }),
    );
    const onStart = vi.fn();
    render(
      <SettingsDialog open onClose={vi.fn()} onStartSkillCreation={onStart} />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "草稿" }));
    expect(
      await screen.findByLabelText("允许 Agent 自动安装全新 Skill"),
    ).not.toBeChecked();
    expect(
      screen.getByRole("option", { name: "自动完成并安装" }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("需求"), {
      target: { value: "整理会议行动项" },
    });
    const submit = screen.getByRole("button", {
      name: "在当前对话开始创作",
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    expect(onStart).toHaveBeenCalledWith("balanced", "整理会议行动项");
  });

  it("自动创作要求并传递一次性授权使用的新 Skill 名称", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((request: RequestInfo | URL) => {
        const url =
          typeof request === "string"
            ? request
            : request instanceof URL
              ? request.href
              : request.url;
        return Promise.resolve(
          Response.json(
            url.endsWith("/api/v1/skills/drafts")
              ? { drafts: [] }
              : url.endsWith("/api/v1/skills/agent-settings")
                ? { creation_enabled: true, revision: 0 }
                : { skills: [], revision: 0 },
          ),
        );
      }),
    );
    const onStart = vi.fn().mockResolvedValue(undefined);
    render(
      <SettingsDialog open onClose={vi.fn()} onStartSkillCreation={onStart} />,
    );

    fireEvent.click(screen.getByRole("tab", { name: "草稿" }));
    fireEvent.change(await screen.findByLabelText("AI 创建模式"), {
      target: { value: "automatic" },
    });
    fireEvent.change(screen.getByLabelText(/新 Skill 名称/), {
      target: { value: "meeting-actions" },
    });
    fireEvent.change(screen.getByLabelText("需求"), {
      target: { value: "整理会议行动项" },
    });
    fireEvent.click(screen.getByRole("button", { name: "在当前对话开始创作" }));

    expect(onStart).toHaveBeenCalledWith(
      "automatic",
      "整理会议行动项",
      "meeting-actions",
    );
  });

  it("确认 Agent 草稿后立即在已安装列表展示完整 Skill 信息", async () => {
    let installed = false;
    const draft = {
      draft_id: "draft-daily",
      name: "daily-tip-demo",
      description: "演示用途每日提示。",
      instructions: "输出今天的日期和提示。",
      allowed_tools: [],
      resources: [{ path: "references/tips.md", content: "保持简洁。" }],
      revision: 1,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((request: RequestInfo | URL, init?: RequestInit) => {
        const url =
          typeof request === "string"
            ? request
            : request instanceof URL
              ? request.href
              : request.url;
        if (url.endsWith("/api/v1/skills/recoverable")) {
          return Promise.resolve(Response.json({ skills: [] }));
        }
        if (url.endsWith("/api/v1/skills/agent-settings")) {
          return Promise.resolve(
            Response.json({ creation_enabled: true, revision: 0 }),
          );
        }
        if (url.endsWith("/api/v1/skills/drafts")) {
          return Promise.resolve(
            Response.json({ drafts: installed ? [] : [draft] }),
          );
        }
        if (url.endsWith("/api/v1/skills/drafts/draft-daily/check")) {
          return Promise.resolve(
            Response.json({
              valid: true,
              errors: [],
              warnings: [],
              content_hash: "a".repeat(64),
            }),
          );
        }
        if (url.endsWith("/api/v1/skills/drafts/draft-daily/install")) {
          expect(init?.method).toBe("POST");
          installed = true;
          return Promise.resolve(
            Response.json({
              name: draft.name,
              description: draft.description,
              source: "user",
              editable: true,
              enabled: true,
              allowed_tools: [],
              instructions: draft.instructions,
              resources: draft.resources,
              revision: 1,
            }),
          );
        }
        return Promise.resolve(
          Response.json({
            skills: installed
              ? [
                  {
                    name: draft.name,
                    description: draft.description,
                    source: "user",
                    enabled: true,
                    editable: true,
                    allowed_tools: [],
                    resource_paths: ["references/tips.md"],
                    resource_count: 1,
                    modified_at: "2026-09-10T00:00:00Z",
                    check_status: "valid",
                  },
                ]
              : [],
            revision: installed ? 1 : 0,
          }),
        );
      }),
    );
    render(<SettingsDialog open onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("tab", { name: "草稿" }));
    fireEvent.click(await screen.findByRole("button", { name: "检查并确认" }));
    fireEvent.click(await screen.findByRole("button", { name: "确认安装" }));

    expect(
      await screen.findByText(
        "已保存 Skill“daily-tip-demo”，将在下一次 Run 生效。",
      ),
    ).toBeVisible();
    expect(screen.getByRole("tab", { name: "已安装" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.getByRole("button", { name: "daily-tip-demo" }),
    ).toBeVisible();
    expect(screen.getByText("演示用途每日提示。")).toBeVisible();
    expect(screen.getByText("1 个")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "草稿" }));
    expect(await screen.findByText("没有草稿。")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "检查并确认" }),
    ).not.toBeInTheDocument();
  });

  it("可从模型设置新增可立即选择的模型且 API Key 不回显", async () => {
    const firstRevision = "a".repeat(64);
    const secondRevision = "b".repeat(64);
    let added = false;
    const addedModel = {
      name: "local-team",
      display_name: "Local Team",
      provider: "openai-compatible",
      model: "team-v1",
      base_url: "http://127.0.0.1:11434/v1",
      api_key_env: "MINI_DEER_MODEL_LOCAL_TEAM_API_KEY",
      api_key_configured: true,
      supports_tools: true,
      supports_reasoning: false,
      source: "file",
    } as const;
    const fetcher = vi.fn((request: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof request === "string"
          ? request
          : request instanceof URL
            ? request.href
            : request.url;
      if (url.endsWith("/api/v1/models") && init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("missing body");
        expect(JSON.parse(init.body)).toMatchObject({
          name: "local-team",
          display_name: "Local Team",
          provider: "openai-compatible",
          model: "team-v1",
          base_url: "http://127.0.0.1:11434/v1",
          api_key: "secret-once",
          profile_revision: firstRevision,
        });
        added = true;
        return Promise.resolve(
          Response.json(
            { model: addedModel, profile_revision: secondRevision },
            { status: 201 },
          ),
        );
      }
      if (url.endsWith("/api/v1/models")) {
        return Promise.resolve(
          Response.json({
            models: added ? [addedModel] : [],
            profile_revision: added ? secondRevision : firstRevision,
          }),
        );
      }
      if (url.endsWith("/api/v1/settings/model-selection")) {
        return Promise.resolve(
          Response.json({
            primary_model: added ? "local-team" : "environment-default",
            goal_model: null,
            revision: added ? 1 : 0,
          }),
        );
      }
      if (url.endsWith("/api/v1/skills/recoverable")) {
        return Promise.resolve(Response.json({ skills: [] }));
      }
      return Promise.resolve(Response.json({ skills: [], revision: 0 }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SettingsDialog open onClose={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "模型" }));
    fireEvent.click(await screen.findByRole("button", { name: "添加模型" }));
    fireEvent.change(screen.getByLabelText(/配置名称/), {
      target: { value: "local-team" },
    });
    fireEvent.change(screen.getByLabelText("显示名称"), {
      target: { value: "Local Team" },
    });
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "openai-compatible" },
    });
    fireEvent.change(screen.getByLabelText("模型 ID"), {
      target: { value: "team-v1" },
    });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "http://127.0.0.1:11434/v1" },
    });
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "secret-once" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存新模型" }));

    expect(
      await screen.findByText(
        "已添加模型“Local Team”，现在可以测试连接或设为默认模型。",
      ),
    ).toBeVisible();
    expect((await screen.findAllByText("Local Team")).length).toBeGreaterThan(
      0,
    );
    expect(screen.queryByDisplayValue("secret-once")).not.toBeInTheDocument();
  });
});
