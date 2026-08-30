import { useMemo } from "react";

import type { ChatTimelineItem } from "@/entities/message/model/types";
import {
  projectConversation,
  type ConversationRunTimingSource,
} from "@/features/chat/model/project-conversation";
import type { ChatRunPhase } from "@/features/chat/model/reducer";
import { ConversationTurn } from "@/features/chat/ui/ConversationTurn";

interface MessageListProps {
  readonly items: readonly ChatTimelineItem[];
  readonly phase: ChatRunPhase;
  readonly startedAt?: string | null;
  readonly runs?: readonly ConversationRunTimingSource[];
}

export function MessageList({
  items,
  phase,
  startedAt = null,
  runs = [],
}: MessageListProps) {
  const turns = useMemo(
    () => projectConversation(items, phase, startedAt, runs),
    [items, phase, runs, startedAt],
  );

  return (
    <ol
      id="conversation-message-list"
      className="message-list"
      role="log"
      aria-live="polite"
      aria-label="对话消息"
    >
      {turns.map((turn) => (
        <ConversationTurn turn={turn} key={turn.id} />
      ))}
    </ol>
  );
}
