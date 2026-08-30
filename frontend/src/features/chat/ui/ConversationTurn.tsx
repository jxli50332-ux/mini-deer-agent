import type { MessageTimelineItem } from "@/entities/message/model/types";
import type { ConversationTurnView } from "@/features/chat/model/project-conversation";
import { MessageContent } from "@/features/chat/ui/MessageContent";
import { RunTiming } from "@/features/chat/ui/RunTiming";
import { ToolActivity } from "@/features/chat/ui/ToolActivity";
import { CopyButton } from "@/shared/ui/CopyButton";
import { formatAttachmentSize } from "@/entities/attachment/model/text-attachments";

interface ConversationTurnProps {
  readonly turn: ConversationTurnView;
}

function MessageRow({
  item,
  allowCopy = false,
}: {
  readonly item: MessageTimelineItem;
  readonly allowCopy?: boolean;
}) {
  const roleLabel = item.role === "assistant" ? "Mini Deer" : "你";

  return (
    <div className={`timeline-row timeline-row--${item.role}`}>
      <article className="message" aria-label={`${roleLabel}的消息`}>
        <span className="message__avatar" aria-hidden="true">
          {item.role === "assistant" ? "M" : "你"}
        </span>
        <div className="message__body">
          <p className="message__author">{roleLabel}</p>
          <MessageContent
            role={item.role}
            content={item.content}
            allowCopy={allowCopy}
          />
          {item.attachments !== undefined && item.attachments.length > 0 && (
            <ul className="message__attachments" aria-label="消息附件">
              {item.attachments.map((attachment, index) => (
                <li key={`${attachment.filename}:${index}`}>
                  <span aria-hidden="true">文</span>
                  <span>
                    <strong>{attachment.filename}</strong>
                    <small>
                      {attachment.mediaType} ·{" "}
                      {formatAttachmentSize(attachment.sizeBytes)}
                    </small>
                  </span>
                </li>
              ))}
            </ul>
          )}
          {allowCopy && item.content.trim().length > 0 && (
            <div className="message__actions">
              <CopyButton text={item.content} label="复制回答" />
            </div>
          )}
        </div>
      </article>
    </div>
  );
}

export function ConversationTurn({ turn }: ConversationTurnProps) {
  let lastAssistantMessageId: string | null = null;
  for (let index = turn.steps.length - 1; index >= 0; index -= 1) {
    const item = turn.steps[index];
    if (item?.kind === "message" && item.role === "assistant") {
      lastAssistantMessageId = item.id;
      break;
    }
  }

  return (
    <li
      className="conversation-turn"
      data-status={turn.status}
      aria-busy={turn.status === "streaming"}
    >
      {turn.user !== null && <MessageRow item={turn.user} />}
      {turn.steps.map((item) => {
        if (item.kind === "tool") {
          return (
            <div className="timeline-row timeline-row--tool" key={item.id}>
              <ToolActivity item={item} />
            </div>
          );
        }

        const allowCopy =
          turn.status === "final" && item.id === lastAssistantMessageId;
        return <MessageRow item={item} allowCopy={allowCopy} key={item.id} />;
      })}
      {turn.timing !== undefined && (
        <RunTiming
          timing={turn.timing}
          key={
            turn.timing.kind === "active"
              ? `active:${turn.timing.startedAt}`
              : `settled:${turn.timing.outcome}:${turn.timing.durationSeconds}`
          }
        />
      )}
    </li>
  );
}
