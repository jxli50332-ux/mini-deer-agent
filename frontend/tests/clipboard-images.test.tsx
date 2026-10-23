import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/features/chat/ui/Composer";

const png =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=";

/** 模拟截图剪贴板，items 和 files 同时存在时也只能添加一次。 */
function pasteImage(file: File, text = "", filesOnly = false) {
  return fireEvent.paste(
    screen.getByRole("textbox", { name: "向 Agent 提问" }),
    {
      clipboardData: {
        items: filesOnly
          ? []
          : [{ kind: "file", type: file.type, getAsFile: () => file }],
        files: [file],
        getData: () => text,
      },
    },
  );
}

function imageFile(name = "image.png") {
  return new File(
    [Uint8Array.from(atob(png), (byte) => byte.charCodeAt(0))],
    name,
    { type: "image/png" },
  );
}

function renderComposer(disabled = false) {
  const onSubmit = vi.fn(() => Promise.resolve(true));
  render(
    <Composer
      isActive={false}
      disabled={disabled}
      onSubmit={onSubmit}
      onCancel={() => Promise.resolve(true)}
    />,
  );
  return onSubmit;
}

describe("输入框粘贴图片", () => {
  // 保护截图到视觉附件的完整入口，而非把图片内容作为文字插入草稿。
  it("粘贴无扩展名截图后显示单个缩略图，并复用图片发送流程", async () => {
    const onSubmit = renderComposer();
    expect(pasteImage(imageFile("clipboard"))).toBe(false);
    const thumbnail = await screen.findByRole("img", {
      name: "待发送图片 粘贴图片-1.png",
    });
    expect(thumbnail).toHaveAttribute("src", `data:image/png;base64,${png}`);
    expect(screen.getAllByRole("img")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(onSubmit).toHaveBeenCalledWith("请描述附件中的图片。", [
      expect.objectContaining({
        filename: "粘贴图片-1.png",
        mediaType: "image/png",
        content: `data:image/png;base64,${png}`,
      }),
    ]);
    expect(screen.queryByRole("img")).toBeNull();
  });

  // 普通文字和图文混合粘贴均保留原生光标、选区及 maxLength 处理。
  it("普通文字粘贴不被取消，图文同时存在时保留原生文字插入", async () => {
    renderComposer();
    const input = screen.getByRole("textbox", { name: "向 Agent 提问" });
    expect(
      fireEvent.paste(input, {
        clipboardData: {
          items: [{ kind: "string", type: "text/plain" }],
          files: [],
          getData: () => "文字",
        },
      }),
    ).toBe(true);
    expect(pasteImage(imageFile(), "图片说明")).toBe(true);
    await screen.findByRole("img", { name: "待发送图片 image.png" });
  });

  // 异步读取不能丢图或绕过总数上限，失败后也必须能继续添加。
  it("连续粘贴按顺序保留三张图，第四张超限且移除后仍能继续", async () => {
    renderComposer();
    for (let index = 1; index <= 4; index += 1) {
      pasteImage(imageFile(`${index}.png`));
    }
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "每条消息最多添加 3 个附件",
    );
    expect(screen.getAllByRole("img")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "移除附件 1.png" }));
    pasteImage(imageFile("new.png"));
    await screen.findByRole("img", { name: "待发送图片 new.png" });
    expect(screen.getAllByRole("img")).toHaveLength(3);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("只有 files 的浏览器仍能读取图片，且与文件选择共用数量限制", async () => {
    renderComposer();
    fireEvent.change(screen.getByLabelText("添加附件"), {
      target: { files: [imageFile("1.png"), imageFile("2.png")] },
    });
    await screen.findByRole("img", { name: "待发送图片 2.png" });
    pasteImage(imageFile("3.png"), "", true);
    await screen.findByRole("img", { name: "待发送图片 3.png" });
    pasteImage(imageFile("4.png"));
    expect(await screen.findByRole("alert")).toHaveTextContent("最多添加 3 个");
    expect(screen.getAllByRole("img")).toHaveLength(3);
  });

  // 粘贴不能绕过原有媒体类型和大小校验，也不能在输入被禁用时添加。
  it("拒绝不支持的图片格式及超限图片，之后仍能正常粘贴", async () => {
    renderComposer();
    pasteImage(new File(["GIF89a"], "a.gif", { type: "image/gif" }));
    expect(screen.getByRole("alert")).toHaveTextContent("仅支持 PNG、JPG/JPEG");
    const large = imageFile("large.png");
    Object.defineProperty(large, "size", { value: 4 * 1024 * 1024 + 1 });
    pasteImage(large);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("4 MiB"),
    );
    pasteImage(imageFile());
    await screen.findByRole("img", { name: "待发送图片 image.png" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("输入框禁用时不读取粘贴图片", async () => {
    renderComposer(true);
    pasteImage(imageFile());
    await waitFor(() => expect(screen.queryByRole("img")).toBeNull());
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  });
});
