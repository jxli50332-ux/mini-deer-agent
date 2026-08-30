import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/features/chat/ui/Composer";

describe("文本附件输入", () => {
  it("清空原生文件输入框前先快照实时 FileList", async () => {
    const onSubmit = vi.fn(() => Promise.resolve(true));
    render(
      <Composer
        isActive={false}
        onSubmit={onSubmit}
        onCancel={() => Promise.resolve(true)}
      />,
    );

    const input = screen.getByLabelText<HTMLInputElement>("添加文本附件");
    const file = new File(["代号：云杉"], "brief.md", {
      type: "text/markdown",
    });
    let currentFiles: File[] = [file];
    const liveFileList = {
      get 0() {
        return currentFiles[0];
      },
      get length() {
        return currentFiles.length;
      },
      item(index: number) {
        return currentFiles[index] ?? null;
      },
    };
    Object.defineProperty(input, "files", {
      configurable: true,
      get: () => liveFileList,
    });
    Object.defineProperty(input, "value", {
      configurable: true,
      get: () => "C:\\fakepath\\brief.md",
      set: () => {
        // 真实浏览器的 FileList 绑定 input；清空 value 会同步把它变空。
        currentFiles = [];
      },
    });

    fireEvent.change(input);

    expect(await screen.findByText("brief.md")).toBeInTheDocument();
  });

  it("选择 UTF-8 文本后显示待发送卡片，并随问题一次提交", async () => {
    const onSubmit = vi.fn(() => Promise.resolve(true));
    render(
      <Composer
        isActive={false}
        onSubmit={onSubmit}
        onCancel={() => Promise.resolve(true)}
      />,
    );

    const file = new File(["代号：云杉"], "brief.md", {
      type: "text/markdown",
    });
    fireEvent.change(screen.getByLabelText("添加文本附件"), {
      target: { files: [file] },
    });

    expect(await screen.findByText("brief.md")).toBeInTheDocument();
    expect(screen.getByText(/15 B/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "向 Agent 提问" }), {
      target: { value: "附件里的代号是什么？" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
    expect(onSubmit).toHaveBeenCalledWith("附件里的代号是什么？", [
      {
        filename: "brief.md",
        mediaType: "text/markdown",
        sizeBytes: 15,
        content: "代号：云杉",
      },
    ]);
    expect(screen.queryByText("brief.md")).not.toBeInTheDocument();
  });

  it("在浏览器侧拒绝不支持的文件类型", async () => {
    render(
      <Composer
        isActive={false}
        onSubmit={() => Promise.resolve(true)}
        onCancel={() => Promise.resolve(true)}
      />,
    );

    fireEvent.change(screen.getByLabelText("添加文本附件"), {
      target: { files: [new File(["x"], "brief.pdf")] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "仅支持 .txt、.md、.json、.csv",
    );
    expect(screen.queryByText("brief.pdf")).not.toBeInTheDocument();
  });
});
