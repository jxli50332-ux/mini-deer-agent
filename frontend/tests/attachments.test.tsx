import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/features/chat/ui/Composer";

describe("文本附件输入", () => {
  it("在输入区展示并切换可用模型", () => {
    const onModelChange = vi.fn();
    render(
      <Composer
        isActive={false}
        modelOptions={[
          { name: "default", displayName: "默认模型", available: true },
          { name: "glm", displayName: "GLM Flash", available: true },
        ]}
        selectedModel="default"
        onModelChange={onModelChange}
        onSubmit={() => Promise.resolve(true)}
        onCancel={() => Promise.resolve(true)}
      />,
    );

    fireEvent.change(screen.getByLabelText("当前模型"), {
      target: { value: "glm" },
    });

    expect(onModelChange).toHaveBeenCalledWith("glm");
  });

  it("外部文件引用追加到现有草稿并把焦点移回输入框", () => {
    const onDraftInsertionApplied = vi.fn();
    const { rerender } = render(
      <Composer
        isActive={false}
        draftInsertion={null}
        onDraftInsertionApplied={onDraftInsertionApplied}
        onSubmit={() => Promise.resolve(true)}
        onCancel={() => Promise.resolve(true)}
      />,
    );
    const input = screen.getByRole<HTMLTextAreaElement>("textbox", {
      name: "向 Agent 提问",
    });
    fireEvent.change(input, { target: { value: "解释这个入口" } });

    rerender(
      <Composer
        isActive={false}
        draftInsertion={{
          id: 1,
          text: '请读取并参考项目文件 "src/main.py"：',
        }}
        onDraftInsertionApplied={onDraftInsertionApplied}
        onSubmit={() => Promise.resolve(true)}
        onCancel={() => Promise.resolve(true)}
      />,
    );

    expect(input).toHaveValue(
      '解释这个入口\n\n请读取并参考项目文件 "src/main.py"：',
    );
    expect(input).toHaveFocus();
    expect(onDraftInsertionApplied).toHaveBeenCalledWith(1);
  });

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
      "不支持该文件类型，仅支持文本类附件",
    );
    expect(screen.queryByText("brief.pdf")).not.toBeInTheDocument();
  });

  it("接受代码文件并推导对应媒体类型", async () => {
    const onSubmit = vi.fn(() => Promise.resolve(true));
    render(
      <Composer
        isActive={false}
        onSubmit={onSubmit}
        onCancel={() => Promise.resolve(true)}
      />,
    );

    fireEvent.change(screen.getByLabelText("添加文本附件"), {
      target: { files: [new File(["print(1)"], "main.py")] },
    });

    expect(await screen.findByText("main.py")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "向 Agent 提问" }), {
      target: { value: "运行这段代码" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce());
    expect(onSubmit).toHaveBeenCalledWith("运行这段代码", [
      {
        filename: "main.py",
        mediaType: "text/x-python",
        sizeBytes: 8,
        content: "print(1)",
      },
    ]);
  });
});
