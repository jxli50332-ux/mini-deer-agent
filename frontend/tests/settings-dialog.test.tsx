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
});
