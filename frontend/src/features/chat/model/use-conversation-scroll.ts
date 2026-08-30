import { useCallback, useLayoutEffect, useRef, useState } from "react";

import type { ChatTimelineItem } from "@/entities/message/model/types";

const BOTTOM_THRESHOLD_PX = 64;

interface ConversationScrollOptions {
  readonly threadId: string;
  readonly items: readonly ChatTimelineItem[];
}

interface ScrollMetrics {
  readonly threadId: string;
  readonly firstItemId: string | null;
  readonly scrollHeight: number;
  readonly scrollTop: number;
}

function bottomScrollTop(viewport: HTMLElement): number {
  return Math.max(0, viewport.scrollHeight - viewport.clientHeight);
}

function isNearBottom(viewport: HTMLElement): boolean {
  return bottomScrollTop(viewport) - viewport.scrollTop <= BOTTOM_THRESHOLD_PX;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** 管理聊天视口的粘底、未读提示和历史前插锚点。 */
export function useConversationScroll({
  threadId,
  items,
}: ConversationScrollOptions) {
  const viewportRef = useRef<HTMLElement>(null);
  const metricsRef = useRef<ScrollMetrics | null>(null);
  const followsLatestRef = useRef(true);
  const [hasUnseenContent, setHasUnseenContent] = useState(false);

  const setViewport = useCallback((node: HTMLElement | null) => {
    viewportRef.current = node;
  }, []);

  const handleScroll = useCallback(() => {
    const viewport = viewportRef.current;
    if (viewport === null) {
      return;
    }

    const followsLatest = isNearBottom(viewport);
    followsLatestRef.current = followsLatest;
    if (followsLatest) {
      setHasUnseenContent(false);
    }

    const metrics = metricsRef.current;
    if (metrics !== null && metrics.threadId === threadId) {
      metricsRef.current = { ...metrics, scrollTop: viewport.scrollTop };
    }
  }, [threadId]);

  const scrollToLatest = useCallback(() => {
    const viewport = viewportRef.current;
    if (viewport === null) {
      return;
    }

    followsLatestRef.current = true;
    setHasUnseenContent(false);
    const top = bottomScrollTop(viewport);
    if (!prefersReducedMotion() && typeof viewport.scrollTo === "function") {
      viewport.scrollTo({ top, behavior: "smooth" });
    } else {
      viewport.scrollTop = top;
    }

    const metrics = metricsRef.current;
    if (metrics !== null && metrics.threadId === threadId) {
      metricsRef.current = { ...metrics, scrollTop: top };
    }
  }, [threadId]);

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (viewport === null) {
      return;
    }

    const previous = metricsRef.current;
    const firstItemId = items[0]?.id ?? null;
    const changedThread = previous?.threadId !== threadId;
    const previousFirstItemStillExists =
      previous?.firstItemId !== null &&
      previous?.firstItemId !== undefined &&
      items.some((item) => item.id === previous.firstItemId);
    const prependedHistory =
      !changedThread &&
      previous !== null &&
      previous.firstItemId !== firstItemId &&
      previousFirstItemStillExists;

    if (changedThread) {
      followsLatestRef.current = true;
      setHasUnseenContent(false);
      viewport.scrollTop = bottomScrollTop(viewport);
    } else if (prependedHistory && previous !== null) {
      const addedHeight = viewport.scrollHeight - previous.scrollHeight;
      viewport.scrollTop = Math.min(
        bottomScrollTop(viewport),
        Math.max(0, previous.scrollTop + addedHeight),
      );
    } else if (followsLatestRef.current) {
      setHasUnseenContent(false);
      viewport.scrollTop = bottomScrollTop(viewport);
    } else {
      setHasUnseenContent(true);
    }

    metricsRef.current = {
      threadId,
      firstItemId,
      scrollHeight: viewport.scrollHeight,
      scrollTop: viewport.scrollTop,
    };
  }, [items, threadId]);

  return {
    setViewport,
    hasUnseenContent,
    handleScroll,
    scrollToLatest,
  } as const;
}
