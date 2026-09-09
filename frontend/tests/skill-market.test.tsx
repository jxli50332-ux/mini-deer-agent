import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SkillMarketPanel } from "@/features/skill-market/ui/SkillMarketPanel";

describe("SkillMarketPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("先展示精确内容与权限预览，再用一次性令牌提交安装", async () => {
    const fetcher = vi.fn((request: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof request === "string"
          ? request
          : request instanceof URL
            ? request.href
            : request.url;
      if (url.includes("/skill-market/catalog")) {
        return Promise.resolve(
          Response.json({
            items: [
              {
                provider: "clawhub",
                remote_id: "publisher/meeting-notes",
                name: "meeting-notes",
                version: "1.1.0",
                description: "整理会议行动项。",
                publisher: "publisher",
                license: "MIT",
                tags: ["meeting"],
                canonical_url:
                  "https://clawhub.ai/publisher/skills/meeting-notes",
                required_tools: [],
                runtime_requirements: [],
                scan_status: "clean",
                published_at: "2026-09-09T00:00:00Z",
                compatible: true,
                compatibility_reason: "本地预检后可安装。",
              },
            ],
            synced_at: "2026-09-09T00:00:00Z",
            from_cache: false,
          }),
        );
      }
      if (url.endsWith("/api/v1/skills")) {
        return Promise.resolve(Response.json({ skills: [], revision: 0 }));
      }
      if (url.endsWith("/preview")) {
        return Promise.resolve(
          Response.json({
            confirmation_token: "a".repeat(32),
            action: "install",
            name: "meeting-notes",
            current_version: null,
            target_version: "1.1.0",
            content_hash: "b".repeat(64),
            enabled_after: true,
            allowed_tools_before: [],
            allowed_tools_after: ["web_search"],
            added_tools: ["web_search"],
            removed_tools: [],
            permission_changed: true,
            description_changed: false,
            instructions_changed: false,
            resources_changed: false,
            expires_at: "2026-09-09T00:10:00Z",
          }),
        );
      }
      if (url.endsWith("/install")) {
        expect(init?.method).toBe("POST");
        if (typeof init?.body !== "string")
          throw new Error("expected JSON body");
        expect(JSON.parse(init.body)).toEqual({
          confirmation_token: "a".repeat(32),
        });
        return Promise.resolve(Response.json({ name: "meeting-notes" }));
      }
      return Promise.resolve(new Response(null, { status: 404 }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SkillMarketPanel />);

    fireEvent.change(screen.getByPlaceholderText("搜索名称、描述或标签"), {
      target: { value: "meeting" },
    });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "检查安装并启用" }),
    );

    expect(
      await screen.findByRole("region", { name: "Skill 变更确认" }),
    ).toBeVisible();
    expect(screen.getAllByText("web_search")).toHaveLength(2);
    expect(screen.getByText("b".repeat(64))).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "确认权限变化并提交" }));

    await waitFor(() => {
      expect(
        screen.getByText("已安装 meeting-notes，下一次 Run 生效。"),
      ).toBeVisible();
    });
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("对市场安装提供带 revision 的回滚、卸载与恢复入口", async () => {
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    const fetcher = vi.fn((request: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof request === "string"
          ? request
          : request instanceof URL
            ? request.href
            : request.url;
      if (url.includes("/skill-market/catalog")) {
        return Promise.resolve(
          Response.json({
            items: [
              {
                provider: "clawhub",
                remote_id: "publisher/meeting-notes",
                name: "meeting-notes",
                version: "1.1.0",
                description: "整理会议行动项。",
                publisher: "publisher",
                license: "MIT",
                tags: ["meeting"],
                canonical_url:
                  "https://clawhub.ai/publisher/skills/meeting-notes",
                required_tools: [],
                runtime_requirements: [],
                scan_status: "clean",
                changelog: "新增负责人字段。",
                published_at: "2026-09-09T00:00:00Z",
                compatible: true,
                compatibility_reason: "兼容",
                file_paths: ["SKILL.md"],
                package_size: 123,
              },
            ],
            synced_at: "2026-09-09T00:00:00Z",
            from_cache: false,
          }),
        );
      }
      if (url.endsWith("/api/v1/skills")) {
        return Promise.resolve(
          Response.json({
            skills: [{ name: "meeting-notes", source: "market" }],
            revision: 4,
          }),
        );
      }
      if (url.endsWith("/api/v1/skills/meeting-notes/history")) {
        return Promise.resolve(
          Response.json({
            history: [
              {
                history_id: "history-1",
                action: "install",
                version: "1.0.0",
                created_at: "2026-09-08T00:00:00Z",
              },
            ],
          }),
        );
      }
      if (url.endsWith("/rollback")) {
        expect(init?.method).toBe("POST");
        if (typeof init?.body !== "string")
          throw new Error("expected JSON body");
        expect(JSON.parse(init.body)).toEqual({
          history_id: "history-1",
          revision: 4,
        });
        return Promise.resolve(Response.json({ name: "meeting-notes" }));
      }
      if (url.includes("/installation?revision=5")) {
        expect(init?.method).toBe("DELETE");
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(new Response(null, { status: 404 }));
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SkillMarketPanel />);

    fireEvent.change(screen.getByPlaceholderText("搜索名称、描述或标签"), {
      target: { value: "meeting" },
    });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));
    fireEvent.click(await screen.findByRole("button", { name: "回滚版本" }));
    fireEvent.click(await screen.findByRole("button", { name: /1\.0\.0/ }));
    expect(
      await screen.findByText("已回滚 meeting-notes，下一次 Run 生效。"),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "卸载" }));
    expect(
      await screen.findByText("已卸载 meeting-notes，下一次 Run 生效。"),
    ).toBeVisible();
    expect(
      await screen.findByRole("button", { name: "恢复历史" }),
    ).toBeVisible();
  });
});
