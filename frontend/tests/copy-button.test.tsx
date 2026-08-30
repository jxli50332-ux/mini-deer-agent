import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CopyButton } from "@/shared/ui/CopyButton";

describe("复制按钮", () => {
  it("成功复制完整文本并给出非阻塞反馈", async () => {
    const writeText = vi
      .fn<(text: string) => Promise<void>>()
      .mockResolvedValue();
    render(
      <CopyButton text="完整回答" label="复制回答" writeText={writeText} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "复制回答" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("完整回答"));
    expect(screen.getByRole("button", { name: "已复制" })).toBeInTheDocument();
  });

  it("浏览器拒绝权限时保留页面并提示手动复制", async () => {
    const writeText = vi
      .fn<(text: string) => Promise<void>>()
      .mockRejectedValue(new Error("denied"));
    render(
      <CopyButton text="仍可选择" label="复制回答" writeText={writeText} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "复制回答" }));

    expect(
      await screen.findByRole("button", { name: "复制失败" }),
    ).toHaveAttribute("title", "复制失败，请手动选择文本");
    expect(screen.getByText("复制失败")).toBeInTheDocument();
  });
});
