import { useMemo } from "react";

import type { ChatTimelineItem } from "@/entities/message/model/types";
import {
  projectConversation,
  type ConversationRunTimingSource,
} from "@/features/chat/model/project-conversation";
import type { ChatRunPhase } from "@/features/chat/model/reducer";
import { ConversationTurn } from "@/features/chat/ui/ConversationTurn";
import {
  deriveHumanInputThreadState,
  type HumanInputRequest,
  type HumanInputResponse,
} from "@/features/chat/model/human-input";

interface MessageListProps {
  readonly items: readonly ChatTimelineItem[];
  readonly phase: ChatRunPhase;
  readonly startedAt?: string | null;
  readonly runs?: readonly ConversationRunTimingSource[];
  readonly onSubmitHumanInput?: (
    request: HumanInputRequest,
    response: HumanInputResponse,
  ) => Promise<boolean>;
}

export function MessageList({
  items,
  phase,
  startedAt = null,
  runs = [],
  onSubmitHumanInput,
}: MessageListProps) {
  const turns = useMemo(
    () => projectConversation(items, phase, startedAt, runs),
    [items, phase, runs, startedAt],
  );
  const humanInputState = useMemo(
    () => deriveHumanInputThreadState(items),
    [items],
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
        <ConversationTurn
          turn={turn}
          humanInputState={humanInputState}
          {...(onSubmitHumanInput === undefined ? {} : { onSubmitHumanInput })}
          key={turn.id}
        />
      ))}
    </ol>
  );
}
