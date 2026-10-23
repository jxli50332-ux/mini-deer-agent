import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessageContent } from "@/features/chat/ui/MessageContent";
import {
  OfficeDocumentCards,
  OfficeDocumentsButton,
} from "@/features/office/ui/OfficeDocumentCards";
import { OfficeWorkspace } from "@/features/office/ui/OfficeWorkspace";
import type { ChatTimelineItem } from "@/entities/message/model/types";
import { textFileFromUrl } from "@/features/office/api/documents";

const filename = "财报.docx";
const wireDocument = {
  filename,
  size_bytes: 41764,
  modified_at: "2026-10-22T00:00:00Z",
};
const steps: ChatTimelineItem[] = [
  {
    kind: "tool",
    id: "create",
    toolCallId: "call-1",
    name: "word_create_document",
    input: JSON.stringify({ filename }),
    result: "created",
    status: "completed",
  },
  {
    kind: "tool",
    id: "paragraph",
    toolCallId: "call-2",
    name: "word_add_paragraph",
    input: JSON.stringify({ filename, text: "正文" }),
    result: "added",
    status: "completed",
  },
];

function stubService(missing = false) {
  const fetcher = vi.fn((url: string) =>
    Promise.resolve(
      url.endsWith("/preview")
        ? missing
          ? new Response("", { status: 404 })
          : Response.json({
              document: wireDocument,
              title: "财报",
              truncated: false,
              blocks: [
                { kind: "paragraph", text: "中文报告", heading_level: 1 },
                {
                  kind: "paragraph",
                  text: "正文<script>是文本",
                  heading_level: 0,
                },
                { kind: "table", rows: [["收入", "100"]] },
              ],
            })
        : Response.json({ documents: [wireDocument] }),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

function Workspace({
  activeSteps = steps,
}: {
  readonly activeSteps?: readonly ChatTimelineItem[];
}) {
  return (
    <OfficeWorkspace
      threadId="thread-1"
      refreshKey="completed"
      hasOfficeTools={activeSteps.length > 0}
    >
      <main>
        <OfficeDocumentsButton />
        <OfficeDocumentCards steps={activeSteps} />
        <MessageContent
          role="assistant"
          content={`[查看文档](?document=${encodeURIComponent(filename)})`}
        />
      </main>
    </OfficeWorkspace>
  );
}

describe("Office 文档交付", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState(null, "", "/");
    window.localStorage.removeItem("mini-deer-agent.layout.preview-width.v1");
  });

  // 用户宽度偏好跨面板重建保留，缩小窗口只能暂时限制宽度，不能覆盖偏好。
  it("预览分隔条支持键盘、复位和宽度记忆，窗口缩小时保留聊天空间", async () => {
    vi.stubGlobal("innerWidth", 1440);
    stubService();
    const first = render(<Workspace />);
    fireEvent.click(screen.getByRole("link", { name: "查看文档" }));
    await screen.findByRole("heading", { name: "中文报告" });
    const separator = screen.getByRole("separator", { name: "调整预览宽度" });
    expect(separator).toHaveAttribute("aria-valuenow", "600");
    fireEvent.keyDown(separator, { key: "ArrowLeft", shiftKey: true });
    expect(separator).toHaveAttribute("aria-valuenow", "640");
    fireEvent.keyDown(separator, { key: "Home" });
    expect(separator).toHaveAttribute("aria-valuenow", "360");
    fireEvent.keyDown(separator, { key: "End" });
    expect(separator).toHaveAttribute("aria-valuenow", "800");
    fireEvent.doubleClick(separator);
    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    expect(separator).toHaveAttribute("aria-valuenow", "610");
    first.unmount();
    render(<Workspace />);
    const restored = screen.getByRole("separator", { name: "调整预览宽度" });
    expect(restored).toHaveAttribute("aria-valuenow", "610");
    vi.stubGlobal("innerWidth", 1200);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    expect(restored).toHaveAttribute("aria-valuenow", "560");
    vi.stubGlobal("innerWidth", 1440);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    expect(restored).toHaveAttribute("aria-valuenow", "610");
  });

  // 捕获丢失或触摸取消后，后续指针移动不能继续误改面板尺寸。
  it("预览面板随拖动调宽，忽略其他指针并在取消后停止拖动", async () => {
    class TestPointerEvent extends MouseEvent {
      readonly pointerId: number;
      constructor(type: string, options: PointerEventInit = {}) {
        super(type, options);
        this.pointerId = options.pointerId ?? 1;
      }
    }
    vi.stubGlobal("PointerEvent", TestPointerEvent);
    vi.stubGlobal("innerWidth", 1440);
    stubService();
    render(<Workspace />);
    fireEvent.click(screen.getByRole("link", { name: "查看文档" }));
    await screen.findByRole("heading", { name: "中文报告" });
    const separator = screen.getByRole("separator", { name: "调整预览宽度" });
    const release = vi.fn();
    separator.setPointerCapture = vi.fn();
    separator.hasPointerCapture = () => true;
    separator.releasePointerCapture = release;
    fireEvent.pointerDown(separator, { pointerId: 1, clientX: 800, button: 0 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 650 });
    expect(separator).toHaveAttribute("aria-valuenow", "750");
    fireEvent.pointerMove(separator, { pointerId: 2, clientX: 200 });
    expect(separator).toHaveAttribute("aria-valuenow", "750");
    fireEvent.pointerCancel(separator, { pointerId: 1 });
    expect(release).toHaveBeenCalledWith(1);
    expect(separator).toHaveAttribute("data-resizing", "false");
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 400 });
    expect(separator).toHaveAttribute("aria-valuenow", "750");
    fireEvent.pointerDown(separator, { pointerId: 1, clientX: 800, button: 0 });
    fireEvent.lostPointerCapture(separator, { pointerId: 1 });
    fireEvent.pointerMove(separator, { pointerId: 1, clientX: 600 });
    expect(separator).toHaveAttribute("aria-valuenow", "750");
  });

  it("识别既有工作区文件链接，但不把外站和越界路径当作本地文件", () => {
    expect(textFileFromUrl("workspace-1/report.md")).toEqual({
      path: "workspace-1/report.md",
    });
    expect(
      textFileFromUrl("https://outside.invalid/workspace-1/report.md"),
    ).toBeNull();
    expect(textFileFromUrl("?file=workspace-1%2F..%2Fsecret.txt")).toBeNull();
  });

  it("同一文档只展示一张卡片，点击后在侧栏展示中文和表格并提供下载", async () => {
    stubService();
    const { container } = render(<Workspace />);
    const cards = await screen.findByRole("list", { name: "相关 Word 文档" });
    expect(within(cards).getAllByRole("link")).toHaveLength(1);
    fireEvent.click(within(cards).getByRole("link"));
    const panel = screen.getByRole("complementary", { name: "文件预览面板" });
    expect(
      await within(panel).findByRole("heading", { name: "中文报告" }),
    ).toBeVisible();
    expect(within(panel).getByRole("cell", { name: "收入" })).toBeVisible();
    expect(within(panel).getByText("正文<script>是文本")).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    expect(
      within(panel).getByRole("link", { name: "下载 Word" }),
    ).toHaveAttribute(
      "href",
      `/api/v1/office/documents/${encodeURIComponent(filename)}/download`,
    );
    expect(new URLSearchParams(window.location.search).get("document")).toBe(
      filename,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(window.location.search).toBe("");
  });

  it("页面链接可以直接恢复侧栏，文档消失时有明确提示并能返回列表", async () => {
    window.history.replaceState(
      null,
      "",
      `/?document=${encodeURIComponent(filename)}`,
    );
    stubService(true);
    render(<Workspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "文档已移动、删除或尚未生成",
    );
    fireEvent.click(screen.getByRole("button", { name: "← 全部文档" }));
    expect(
      await screen.findByText(filename, { selector: ".office-library strong" }),
    ).toBeVisible();
  });

  it("复制的是可访问的页面链接，正文中的文档链接也会打开侧栏", async () => {
    stubService();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<Workspace />);
    fireEvent.click(screen.getByRole("link", { name: "查看文档" }));
    await screen.findByRole("heading", { name: "中文报告" });
    fireEvent.click(screen.getByRole("button", { name: "复制链接" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledOnce());
    const copied = writeText.mock.calls[0]?.[0] as string;
    expect(new URL(copied).searchParams.get("document")).toBe(filename);
  });

  it("普通对话不额外请求 Office，点击文档入口时才加载已有产物", async () => {
    const fetcher = stubService();
    render(<Workspace activeSteps={[]} />);
    expect(fetcher).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "文件" }));
    expect(
      await screen.findByText(filename, { selector: ".office-library strong" }),
    ).toBeVisible();
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("切换会话会关闭文档，返回原会话也不会重新打开旧面板", async () => {
    stubService();
    const view = (threadId: string) => (
      <OfficeWorkspace threadId={threadId} refreshKey={threadId} hasOfficeTools>
        <MessageContent
          role="assistant"
          content={`[查看文档](?document=${encodeURIComponent(filename)})`}
        />
      </OfficeWorkspace>
    );
    const { rerender } = render(view("thread-1"));
    fireEvent.click(screen.getByRole("link", { name: "查看文档" }));
    await screen.findByRole("heading", { name: "中文报告" });
    rerender(view("thread-2"));
    await waitFor(() => expect(window.location.search).toBe(""));
    expect(screen.queryByRole("complementary")).toBeNull();
    rerender(view("thread-1"));
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("工作区 Markdown 从文件卡片打开，可切换源码并保留下载路径", async () => {
    const path = "workspace-1/报告.md";
    const content =
      "# Markdown 中文标题\n\n**重点**\n\n| 项目 | 数值 |\n| --- | --- |\n| 收入 | 100 |\n\n<script>alert('unsafe')</script>";
    const fetcher = vi.fn((url: string) =>
      Promise.resolve(
        url.includes("/text-preview?")
          ? Response.json({
              document: { ...wireDocument, filename: "报告.md" },
              title: "报告",
              kind: "markdown",
              content,
              blocks: [],
              truncated: false,
            })
          : Response.json({ documents: [] }),
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    const textSteps: ChatTimelineItem[] = [
      {
        kind: "tool",
        id: "text-create",
        toolCallId: "c1",
        name: "create_file",
        input: JSON.stringify({ path, content }),
        result: "created",
        status: "completed",
      },
    ];
    const { container } = render(<Workspace activeSteps={textSteps} />);
    fireEvent.click(
      screen.getByRole("list", { name: "相关文本文件" }).querySelector("a")!,
    );
    expect(
      await screen.findByRole("heading", { name: "Markdown 中文标题" }),
    ).toBeVisible();
    expect(screen.getByRole("cell", { name: "收入" })).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "源码" }));
    expect(screen.getByLabelText("文本源码")).toHaveTextContent(
      "# Markdown 中文标题",
    );
    expect(screen.getByLabelText("文本源码")).toHaveTextContent("<script>");
    const download = screen.getByRole("link", { name: "下载文件" });
    expect(
      new URL(
        download.getAttribute("href")!,
        window.location.origin,
      ).searchParams.get("path"),
    ).toBe(path);
    expect(new URLSearchParams(window.location.search).get("file")).toBe(path);
    fireEvent.click(screen.getByRole("button", { name: "预览" }));
    expect(
      screen.getByRole("heading", { name: "Markdown 中文标题" }),
    ).toBeVisible();
  });

  it("项目文本链接直接恢复侧栏并保留项目身份，不把代码解释成 HTML", async () => {
    const projectId = "00000000-0000-4000-8000-000000000001";
    window.history.replaceState(
      null,
      "",
      `/?file=src%2Fexample.py&preview_project=${projectId}`,
    );
    const fetcher = vi.fn((url: string) =>
      Promise.resolve(
        url.includes("/text-preview?")
          ? Response.json({
              document: { ...wireDocument, filename: "example.py" },
              title: "example",
              kind: "text",
              content: 'print("<h1>代码文本</h1>")\n',
              blocks: [],
              truncated: false,
            })
          : Response.json({ documents: [] }),
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    const { container } = render(<Workspace activeSteps={[]} />);
    expect(await screen.findByLabelText("文本源码")).toHaveTextContent(
      'print("<h1>代码文本</h1>")',
    );
    expect(container.querySelector(".word-preview h1")).toBeNull();
    const request = fetcher.mock.calls.find(([url]) =>
      url.includes("/text-preview?"),
    )?.[0];
    expect(
      new URL(request!, window.location.origin).searchParams.get("project_id"),
    ).toBe(projectId);
  });
});
