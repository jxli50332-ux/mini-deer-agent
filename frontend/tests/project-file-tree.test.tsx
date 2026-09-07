import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProjectFileTree } from "@/features/workspace/ui/ProjectFileTree";
import {
  parseDirectory,
  type DirectoryPage,
} from "@/entities/project/model/directory";
const empty: DirectoryPage = {
  items: [],
  truncated: false,
  truncationReason: null,
};

describe("项目文件树", () => {
  it("只在展开时加载子目录，刷新能看到新增项，忽略项不可展开", async () => {
    const root: DirectoryPage = {
      ...empty,
      items: [
        { name: "src", path: "src", kind: "directory", status: "available" },
        { name: ".env", path: ".env", kind: "unknown", status: "ignored" },
      ],
    };
    const load = vi
      .fn()
      .mockResolvedValueOnce(root)
      .mockResolvedValueOnce(empty)
      .mockResolvedValueOnce({
        ...empty,
        items: [
          { name: "new.py", path: "new.py", kind: "file", status: "available" },
        ],
      });
    render(<ProjectFileTree projectId="p" load={load} />);
    expect(load).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "展开目录 根目录" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "展开目录 src" }),
    );
    expect(await screen.findByText("空目录")).toBeVisible();
    expect(load.mock.calls[1]?.[1]).toBe("src");
    expect(screen.getByText("已忽略")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "刷新目录 根目录" }));
    expect(await screen.findByText("new.py")).toBeVisible();
    expect(screen.queryByText(".env")).not.toBeInTheDocument();
  });

  it("收起后取消请求，迟到结果不能恢复旧树；错误可刷新重试", async () => {
    let resolve: (page: DirectoryPage) => void = () => undefined;
    let signal: AbortSignal | undefined;
    const load = vi.fn((_id: string, _path: string, incoming: AbortSignal) => {
      signal = incoming;
      return new Promise<DirectoryPage>((done) => {
        resolve = done;
      });
    });
    const { unmount } = render(<ProjectFileTree projectId="p" load={load} />);
    fireEvent.click(screen.getByRole("button", { name: "展开目录 根目录" }));
    await waitFor(() => expect(load).toHaveBeenCalled());
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(() => {
      resolve(empty);
      return Promise.resolve();
    });
    const retry = vi
      .fn()
      .mockRejectedValueOnce(new Error("private detail"))
      .mockResolvedValueOnce({
        ...empty,
        truncated: true,
        truncationReason: "entry_limit",
      });
    render(<ProjectFileTree projectId="other" load={retry} />);
    fireEvent.click(screen.getByRole("button", { name: "展开目录 根目录" }));
    expect(await screen.findByRole("alert")).not.toHaveTextContent(
      "private detail",
    );
    fireEvent.click(screen.getByRole("button", { name: "刷新目录 根目录" }));
    expect(await screen.findByText(/仅显示部分内容/)).toBeVisible();
  });

  it("外部刷新版本变化时重新加载已经展开的目录", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce({
        ...empty,
        items: [
          {
            name: "before.txt",
            path: "before.txt",
            kind: "file",
            status: "available",
          },
        ],
      })
      .mockResolvedValueOnce({
        ...empty,
        items: [
          {
            name: "after.txt",
            path: "after.txt",
            kind: "file",
            status: "available",
          },
        ],
      });
    const { rerender } = render(
      <ProjectFileTree
        projectId="p"
        load={load}
        initiallyOpen
        refreshRevision={0}
      />,
    );
    expect(await screen.findByText("before.txt")).toBeVisible();

    rerender(
      <ProjectFileTree
        projectId="p"
        load={load}
        initiallyOpen
        refreshRevision={1}
      />,
    );
    expect(await screen.findByText("after.txt")).toBeVisible();
    expect(screen.queryByText("before.txt")).not.toBeInTheDocument();
  });

  it("响应身份或子项路径不匹配时拒绝，不能导航到别的项目或父目录", () => {
    const raw = {
      project_id: "p",
      path: "src",
      items: [],
      truncated: false,
      truncation_reason: null,
    };
    expect(parseDirectory(raw, "p", "src").items).toEqual([]);
    expect(() => parseDirectory(raw, "other", "src")).toThrow();
    expect(() =>
      parseDirectory(
        {
          ...raw,
          items: [
            { name: "x", path: "../x", kind: "directory", status: "available" },
          ],
        },
        "p",
        "src",
      ),
    ).toThrow();
  });
});
