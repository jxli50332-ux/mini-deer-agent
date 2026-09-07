import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import {
  FilePreview,
  ProjectFiles,
  type FileLoader,
} from "@/features/workspace/ui/ProjectFiles";
import { parseFilePage, type FilePage } from "@/entities/project/model/file";
const page: FilePage = {
  status: "text",
  lines: ["<script>alert(1)</script>", "中文"],
  startLine: 1,
  nextLine: 3,
  totalLines: 3,
  revision: "a".repeat(64),
  sizeBytes: 40,
};
const originalShow = Object.getOwnPropertyDescriptor(
  HTMLDialogElement.prototype,
  "showModal",
);
beforeAll(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
    configurable: true,
    value(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
  });
});
afterAll(() => {
  if (originalShow)
    Object.defineProperty(
      HTMLDialogElement.prototype,
      "showModal",
      originalShow,
    );
  else Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
});

describe("只读文件预览", () => {
  it("当前项目会话可以把相对路径引用到提问并关闭预览", () => {
    const onClose = vi.fn();
    const onReferenceFile = vi.fn();
    render(
      <FilePreview
        projectId="p"
        path="src/main.py"
        load={vi.fn().mockResolvedValue(page)}
        onClose={onClose}
        canReferenceCurrentThread
        onReferenceFile={onReferenceFile}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "引用到当前提问" }));
    expect(onReferenceFile).toHaveBeenCalledWith("src/main.py");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("其他项目或普通会话不能引用当前预览路径", () => {
    render(
      <FilePreview
        projectId="p"
        path="src/main.py"
        load={vi.fn().mockResolvedValue(page)}
        onClose={() => undefined}
        onReferenceFile={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "引用到当前提问" }),
    ).toBeDisabled();
    expect(screen.getByTitle("请先进入该项目的会话")).toBeInTheDocument();
  });

  it("点击文件加载纯文本与行号，翻页后保持连续编号", async () => {
    const directory = vi.fn().mockResolvedValue({
      items: [
        { name: "x.py", path: "x.py", kind: "file", status: "available" },
      ],
      truncated: false,
      truncationReason: null,
    });
    const file = vi
      .fn()
      .mockResolvedValueOnce(page)
      .mockResolvedValueOnce({
        ...page,
        startLine: 3,
        lines: ["第三行"],
        nextLine: null,
      });
    const { container } = render(
      <ProjectFiles
        projectId="p"
        rootName="sample"
        loadDirectory={directory}
        loadFile={file}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "展开目录 根目录" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "预览文件 x.py" }),
    );
    expect(await screen.findByText("中文")).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByLabelText("第 2 行")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "下一段" }));
    expect(await screen.findByText("第三行")).toBeVisible();
    expect(screen.getByLabelText("第 3 行")).toBeVisible();
    expect(file.mock.calls[1]?.slice(0, 3)).toEqual(["p", "x.py", 3]);
    expect(screen.getByRole("button", { name: "下一段" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "关闭源码预览" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("续读遇到版本改变不展示混合内容，重新加载可以恢复", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(page)
      .mockResolvedValueOnce({
        ...page,
        revision: "b".repeat(64),
        startLine: 3,
        lines: ["不应展示"],
      })
      .mockResolvedValueOnce({
        ...page,
        revision: "b".repeat(64),
        lines: ["新版本"],
      });
    render(
      <FilePreview
        projectId="p"
        path="x"
        load={load}
        onClose={() => undefined}
      />,
    );
    await screen.findByText("中文");
    fireEvent.click(screen.getByRole("button", { name: "下一段" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "文件已在外部修改",
    );
    expect(screen.queryByText("不应展示")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("新版本")).toBeVisible();
  });

  it.each([
    ["binary", "二进制"],
    ["too_large", "2 MiB"],
    ["unsupported_encoding", "UTF-8"],
    ["line_too_long", "长度上限"],
  ] as const)("明确显示 %s 状态", async (status, label) => {
    const load = vi
      .fn()
      .mockResolvedValue({ ...page, status, lines: [], nextLine: null });
    render(
      <FilePreview
        projectId="p"
        path="x"
        load={load}
        onClose={() => undefined}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(label),
    );
    expect(screen.queryByLabelText("源码内容")).not.toBeInTheDocument();
  });

  it("卸载取消在途正文请求并拒绝迟到响应", async () => {
    let resolve: (value: FilePage) => void = () => undefined;
    let signal: AbortSignal | undefined;
    const load: FileLoader = (_p, _f, _s, incoming) => {
      signal = incoming;
      return new Promise((done) => {
        resolve = done;
      });
    };
    const { unmount } = render(
      <FilePreview
        projectId="p"
        path="x"
        load={load}
        onClose={() => undefined}
      />,
    );
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(() => {
      resolve(page);
      return Promise.resolve();
    });
    expect(screen.queryByText("中文")).not.toBeInTheDocument();
  });

  it("解析器拒绝错项目、错路径和不连续游标，接受空文本", () => {
    const raw = {
      project_id: "p",
      path: "x",
      size_bytes: 0,
      status: "text",
      lines: [],
      start_line: 1,
      next_line: null,
      total_lines: 0,
      revision: "a".repeat(64),
    };
    expect(parseFilePage(raw, "p", "x", 1).lines).toEqual([]);
    expect(() => parseFilePage(raw, "q", "x", 1)).toThrow();
    expect(() => parseFilePage(raw, "p", "y", 1)).toThrow();
    expect(() =>
      parseFilePage({ ...raw, next_line: 1 }, "p", "x", 1),
    ).toThrow();
  });
});
