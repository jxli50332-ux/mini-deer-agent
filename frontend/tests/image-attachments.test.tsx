import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "@/features/chat/ui/Composer";
import { ConversationTurn } from "@/features/chat/ui/ConversationTurn";
import {
  validateAttachmentPayloads,
  MAX_IMAGE_ATTACHMENT_BYTES,
} from "@/entities/attachment/model/attachments";
import { parseThreadHistoryPage } from "@/features/threads/api/thread-history";
import { streamChatRun, type FetchLike } from "@/features/chat/api/chat-stream";

const png =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=";
const dataUrl = `data:image/png;base64,${png}`;
const size = atob(png).length;
const threadId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";

describe("图片附件", () => {
  // 保护图片视觉输入，不允许改扩展名的文本或外链进入图片元素。
  it("混合附件计算原始大小并拒绝伪装和超限图片", () => {
    expect(
      validateAttachmentPayloads([
        { filename: "图.png", content: dataUrl },
        { filename: "说明.md", content: "中文" },
      ]),
    ).toMatchObject([
      { mediaType: "image/png", sizeBytes: size },
      { mediaType: "text/markdown", sizeBytes: 6 },
    ]);
    expect(() =>
      validateAttachmentPayloads([
        { filename: "fake.png", content: "data:image/png;base64,eA==" },
      ]),
    ).toThrow("实际格式");
    expect(() =>
      validateAttachmentPayloads([
        { filename: "remote.png", content: "https://example.com/a.png" },
      ]),
    ).toThrow("图片内容");
    expect(() =>
      validateAttachmentPayloads([
        {
          filename: "large.png",
          content: `data:image/png;base64,${"A".repeat(4 * Math.ceil(MAX_IMAGE_ATTACHMENT_BYTES / 3) + 40)}`,
        },
      ]),
    ).toThrow("4 MiB");
  });

  it("选择图片显示缩略图，只有图片也能发送且仍可移除附件", async () => {
    const onSubmit = vi.fn(() => Promise.resolve(true));
    render(
      <Composer
        isActive={false}
        onSubmit={onSubmit}
        onCancel={() => Promise.resolve(true)}
      />,
    );
    const file = new File(
      [Uint8Array.from(atob(png), (c) => c.charCodeAt(0))],
      "图.png",
      { type: "image/png" },
    );
    fireEvent.change(screen.getByLabelText("添加附件"), {
      target: { files: [file] },
    });
    expect(
      await screen.findByRole("img", { name: "待发送图片 图.png" }),
    ).toHaveAttribute("src", dataUrl);
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith("请描述附件中的图片。", [
        {
          filename: "图.png",
          mediaType: "image/png",
          sizeBytes: size,
          content: dataUrl,
        },
      ]),
    );
    expect(screen.queryByRole("img")).toBeNull();
    fireEvent.change(screen.getByLabelText("添加附件"), {
      target: { files: [file] },
    });
    await screen.findByRole("img", { name: "待发送图片 图.png" });
    fireEvent.click(screen.getByRole("button", { name: "移除附件 图.png" }));
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("文件系统未提供 MIME 时仍可依据真实 PNG 内容读取", async () => {
    render(
      <Composer
        isActive={false}
        onSubmit={() => Promise.resolve(true)}
        onCancel={() => Promise.resolve(true)}
      />,
    );
    const file = new File(
      [Uint8Array.from(atob(png), (c) => c.charCodeAt(0))],
      "unknown-type.png",
    );
    fireEvent.change(screen.getByLabelText("添加附件"), {
      target: { files: [file] },
    });
    expect(
      await screen.findByRole("img", { name: "待发送图片 unknown-type.png" }),
    ).toHaveAttribute("src", dataUrl);
  });

  it("历史图片恢复后可展开和下载，页面不展示 Base64 正文", () => {
    const page = parseThreadHistoryPage(
      {
        version: "1",
        thread_id: threadId,
        thread_exists: true,
        has_more: false,
        next_before_sequence: null,
        items: [
          {
            kind: "message",
            id: "user-image",
            run_id: runId,
            thread_sequence: 1,
            role: "user",
            content: "描述图片",
            created_at: "2026-10-22T00:00:00Z",
            attachments: [
              {
                filename: "图.png",
                media_type: "image/png",
                size_bytes: size,
                content: dataUrl,
              },
            ],
          },
        ],
      },
      threadId,
    );
    const item = page.items[0];
    if (item?.kind !== "message") throw new Error("missing user");
    render(
      <ConversationTurn
        turn={{ id: "turn", user: item, steps: [], status: "final" }}
      />,
    );
    expect(screen.getByRole("img", { name: "图片 图.png" })).toHaveAttribute(
      "src",
      dataUrl,
    );
    fireEvent.click(screen.getByText("图.png", { selector: "strong" }));
    expect(screen.getByRole("link", { name: "下载原图" })).toHaveAttribute(
      "download",
      "图.png",
    );
    expect(screen.getByRole("link", { name: "下载原图" })).toHaveAttribute(
      "href",
      "/api/v1/attachments/user-image/0/download",
    );
    expect(screen.queryByText(dataUrl)).toBeNull();
  });

  it("HTTP 客户端保留图片内容，不经过 UTF-8 文本限制", async () => {
    const fetcher = vi.fn<FetchLike>(() =>
      Promise.resolve(new Response("", { status: 400 })),
    );
    try {
      for await (const event of streamChatRun(
        {
          threadId,
          messageId: runId,
          message: "看图",
          attachments: [{ filename: "图.png", content: dataUrl }],
        },
        { fetcher },
      ))
        void event;
    } catch {
      /* 只检查已发出的请求，模拟后端拒绝不影响附件序列化断言。 */
    }
    expect(fetcher).toHaveBeenCalledOnce();
    const init = fetcher.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toMatchObject({
      attachments: [{ filename: "图.png", content: dataUrl }],
    });
  });
});
