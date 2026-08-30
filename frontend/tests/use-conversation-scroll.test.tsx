import { fireEvent, render, screen } from "@testing-library/react";
import { useCallback } from "react";
import { describe, expect, it } from "vitest";

import type { ChatTimelineItem } from "@/entities/message/model/types";
import { useConversationScroll } from "@/features/chat/model/use-conversation-scroll";

const FIRST_ITEM: ChatTimelineItem = {
  kind: "message",
  id: "user-1",
  role: "user",
  content: "第一问",
};

const SECOND_ITEM: ChatTimelineItem = {
  kind: "message",
  id: "assistant-1",
  role: "assistant",
  content: "第一答",
};

interface ScrollHarnessProps {
  readonly threadId?: string;
  readonly items: readonly ChatTimelineItem[];
  readonly scrollHeight: number;
  readonly clientHeight?: number;
}

function ScrollHarness({
  threadId = "thread-1",
  items,
  scrollHeight,
  clientHeight = 200,
}: ScrollHarnessProps) {
  const { setViewport, hasUnseenContent, handleScroll, scrollToLatest } =
    useConversationScroll({ threadId, items });
  const setViewportRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (node !== null) {
        Object.defineProperties(node, {
          scrollHeight: { configurable: true, value: scrollHeight },
          clientHeight: { configurable: true, value: clientHeight },
          scrollTo: { configurable: true, value: undefined },
        });
      }
      setViewport(node);
    },
    [clientHeight, scrollHeight, setViewport],
  );

  return (
    <>
      <div
        ref={setViewportRef}
        data-testid="viewport"
        onScroll={handleScroll}
      />
      {hasUnseenContent && (
        <button type="button" onClick={scrollToLatest}>
          回到最新
        </button>
      )}
    </>
  );
}

describe("对话粘底滚动", () => {
  it("贴近底部时随新内容增长自动跟随", () => {
    const { rerender } = render(
      <ScrollHarness items={[FIRST_ITEM]} scrollHeight={600} />,
    );
    const viewport = screen.getByTestId("viewport");
    expect(viewport.scrollTop).toBe(400);

    rerender(
      <ScrollHarness items={[FIRST_ITEM, SECOND_ITEM]} scrollHeight={720} />,
    );

    expect(viewport.scrollTop).toBe(520);
    expect(
      screen.queryByRole("button", { name: "回到最新" }),
    ).not.toBeInTheDocument();
  });

  it("用户上滚后不抢位置，并通过按钮恢复跟随", () => {
    const { rerender } = render(
      <ScrollHarness items={[FIRST_ITEM]} scrollHeight={600} />,
    );
    const viewport = screen.getByTestId("viewport");
    viewport.scrollTop = 120;
    fireEvent.scroll(viewport);

    rerender(
      <ScrollHarness items={[FIRST_ITEM, SECOND_ITEM]} scrollHeight={720} />,
    );

    expect(viewport.scrollTop).toBe(120);
    fireEvent.click(screen.getByRole("button", { name: "回到最新" }));
    expect(viewport.scrollTop).toBe(520);
    expect(
      screen.queryByRole("button", { name: "回到最新" }),
    ).not.toBeInTheDocument();
  });

  it("历史从顶部插入时补偿新增高度，保持原阅读锚点", () => {
    const { rerender } = render(
      <ScrollHarness items={[FIRST_ITEM, SECOND_ITEM]} scrollHeight={600} />,
    );
    const viewport = screen.getByTestId("viewport");
    viewport.scrollTop = 100;
    fireEvent.scroll(viewport);

    const olderItem: ChatTimelineItem = {
      kind: "message",
      id: "user-older",
      role: "user",
      content: "更早问题",
    };
    rerender(
      <ScrollHarness
        items={[olderItem, FIRST_ITEM, SECOND_ITEM]}
        scrollHeight={800}
      />,
    );

    expect(viewport.scrollTop).toBe(300);
    expect(
      screen.queryByRole("button", { name: "回到最新" }),
    ).not.toBeInTheDocument();
  });

  it("切换 Thread 时清除旧阅读位置并定位到新会话底部", () => {
    const { rerender } = render(
      <ScrollHarness items={[FIRST_ITEM]} scrollHeight={600} />,
    );
    const viewport = screen.getByTestId("viewport");
    viewport.scrollTop = 100;
    fireEvent.scroll(viewport);

    rerender(
      <ScrollHarness
        threadId="thread-2"
        items={[SECOND_ITEM]}
        scrollHeight={500}
      />,
    );

    expect(viewport.scrollTop).toBe(300);
    expect(
      screen.queryByRole("button", { name: "回到最新" }),
    ).not.toBeInTheDocument();
  });
});
