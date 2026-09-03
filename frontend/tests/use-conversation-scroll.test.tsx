import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  readonly isStreaming?: boolean;
  readonly streamText?: string;
}

function ScrollHarness({
  threadId = "thread-1",
  items,
  scrollHeight,
  clientHeight = 200,
  isStreaming = false,
  streamText = "",
}: ScrollHarnessProps) {
  const { setViewport, hasUnseenContent, handleScroll, scrollToLatest } =
    useConversationScroll({ threadId, items, isStreaming });
  const setViewportRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (node !== null) {
        Object.defineProperties(node, {
          scrollHeight: {
            configurable: true,
            get: () => Number(node.dataset.scrollHeight),
          },
          clientHeight: { configurable: true, value: clientHeight },
          scrollTo: { configurable: true, value: undefined },
        });
      }
      setViewport(node);
    },
    [clientHeight, setViewport],
  );

  return (
    <>
      <div
        ref={setViewportRef}
        data-testid="viewport"
        data-scroll-height={scrollHeight}
        onScroll={handleScroll}
      >
        <span>{streamText}</span>
      </div>
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

  it("流式文字更新同一条消息时仍自动跟随最新内容", async () => {
    const { rerender } = render(
      <ScrollHarness
        items={[FIRST_ITEM]}
        scrollHeight={600}
        isStreaming
        streamText="正在分析"
      />,
    );
    const viewport = screen.getByTestId("viewport");
    expect(viewport.scrollTop).toBe(400);

    rerender(
      <ScrollHarness
        items={[FIRST_ITEM]}
        scrollHeight={760}
        isStreaming
        streamText="正在分析并持续生成最新 COT 步骤"
      />,
    );

    await waitFor(() => expect(viewport.scrollTop).toBe(560));
  });

  it("用户在流式执行中上滚后不强制跟随 DOM 更新", async () => {
    const { rerender } = render(
      <ScrollHarness
        items={[FIRST_ITEM]}
        scrollHeight={600}
        isStreaming
        streamText="第一段"
      />,
    );
    const viewport = screen.getByTestId("viewport");
    viewport.scrollTop = 120;
    fireEvent.scroll(viewport);

    rerender(
      <ScrollHarness
        items={[FIRST_ITEM]}
        scrollHeight={760}
        isStreaming
        streamText="第一段和新增内容"
      />,
    );

    await waitFor(() => expect(viewport.scrollTop).toBe(120));
    expect(
      screen.getByRole("button", { name: "回到最新" }),
    ).toBeInTheDocument();
  });
});
