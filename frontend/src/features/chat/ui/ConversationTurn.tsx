import type {
  ChatTimelineItem,
  MessageTimelineItem,
} from "@/entities/message/model/types";
import type { ConversationTurnView } from "@/features/chat/model/project-conversation";
import { projectCotSteps } from "@/features/chat/model/project-cot";
import { CotTimeline } from "@/features/chat/ui/CotTimeline";
import { MessageContent } from "@/features/chat/ui/MessageContent";
import { RunTiming } from "@/features/chat/ui/RunTiming";
import { HumanInputCard } from "@/features/chat/ui/HumanInputCard";
import type {
  HumanInputRequest,
  HumanInputResponse,
  HumanInputThreadState,
} from "@/features/chat/model/human-input";
import { CopyButton } from "@/shared/ui/CopyButton";
import { formatAttachmentSize } from "@/entities/attachment/model/text-attachments";

interface ConversationTurnProps {
  readonly turn: ConversationTurnView;
  readonly humanInputState?: HumanInputThreadState;
  readonly onSubmitHumanInput?: (
    request: HumanInputRequest,
    response: HumanInputResponse,
  ) => Promise<boolean>;
}

const EMPTY_HUMAN_INPUT_STATE: HumanInputThreadState = {
  requestsByToolItemId: new Map(),
  answeredResponses: new Map(),
  latestOpenRequestId: null,
};

function MessageRow({
  item,
  allowCopy = false,
  showReasoning = true,
}: {
  readonly item: MessageTimelineItem;
  readonly allowCopy?: boolean;
  readonly showReasoning?: boolean;
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
          {showReasoning &&
            item.reasoning !== undefined &&
            item.reasoning.length > 0 && (
              <details className="message__reasoning">
                <summary className="message__reasoning-summary">
                  思考过程
                </summary>
                <div className="message__reasoning-content">
                  <MessageContent role={item.role} content={item.reasoning} />
                </div>
              </details>
            )}
          <MessageContent
            role={item.role}
            content={item.content}
            allowCopy={allowCopy}
          />
          {item.attachments !== undefined && item.attachments.length > 0 && (
            <ul className="message__attachments" aria-label="消息附件">
              {item.attachments.map((attachment, index) => (
                <li key={`${attachment.filename}:${index}`}>
                  <details className="message__attachment">
                    <summary className="message__attachment-summary">
                      <span
                        aria-hidden="true"
                        className="message__attachment-icon"
                      >
                        文
                      </span>
                      <span className="message__attachment-meta">
                        <strong>{attachment.filename}</strong>
                        <small>
                          {attachment.mediaType} ·{" "}
                          {formatAttachmentSize(attachment.sizeBytes)}
                        </small>
                      </span>
                    </summary>
                    <pre className="message__attachment-content">
                      {attachment.content}
                    </pre>
                  </details>
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

export function ConversationTurn({
  turn,
  humanInputState = EMPTY_HUMAN_INPUT_STATE,
  onSubmitHumanInput,
}: ConversationTurnProps) {
  let lastAssistantMessageId: string | null = null;
  for (let index = turn.steps.length - 1; index >= 0; index -= 1) {
    const item = turn.steps[index];
    if (item?.kind === "message" && item.role === "assistant") {
      lastAssistantMessageId = item.id;
      break;
    }
  }

  // 澄清卡是用户交互、最终回复是交付物，都必须直接可见；其余内容投影为统一 COT。
  const clarificationSteps: ChatTimelineItem[] = [];
  const cotSourceSteps: ChatTimelineItem[] = [];
  const finalSteps: ChatTimelineItem[] = [];
  for (const item of turn.steps) {
    const isClarification =
      item.kind === "tool" && humanInputState.requestsByToolItemId.has(item.id);
    const isFinalAssistant =
      item.kind === "message" &&
      item.role === "assistant" &&
      item.id === lastAssistantMessageId;
    if (isClarification) {
      clarificationSteps.push(item);
    } else if (isFinalAssistant) {
      finalSteps.push(item);
      // 最终正文直接展示，但它携带的 reasoning 仍属于完整 COT。
      cotSourceSteps.push(item);
    } else {
      cotSourceSteps.push(item);
    }
  }

  const cotSteps = projectCotSteps(cotSourceSteps, lastAssistantMessageId);

  const renderStep = (item: ChatTimelineItem) => {
    if (item.kind === "tool") {
      const humanInputRequest = humanInputState.requestsByToolItemId.get(
        item.id,
      );
      if (humanInputRequest !== undefined) {
        const answeredResponse = humanInputState.answeredResponses.get(
          humanInputRequest.requestId,
        );
        const canSubmit =
          answeredResponse === undefined &&
          humanInputState.latestOpenRequestId === humanInputRequest.requestId &&
          onSubmitHumanInput !== undefined;
        return (
          <div className="timeline-row timeline-row--tool" key={item.id}>
            <HumanInputCard
              request={humanInputRequest}
              {...(answeredResponse === undefined ? {} : { answeredResponse })}
              {...(!canSubmit
                ? {}
                : {
                    onSubmit: (response) =>
                      onSubmitHumanInput(humanInputRequest, response),
                  })}
            />
          </div>
        );
      }
      return null;
    }

    const allowCopy =
      turn.status === "final" && item.id === lastAssistantMessageId;
    return (
      <MessageRow
        item={item}
        allowCopy={allowCopy}
        showReasoning={false}
        key={item.id}
      />
    );
  };

  return (
    <li
      className="conversation-turn"
      data-status={turn.status}
      aria-busy={turn.status === "streaming"}
    >
      {turn.user !== null && <MessageRow item={turn.user} />}
      {clarificationSteps.map(renderStep)}
      <CotTimeline steps={cotSteps} />
      {finalSteps.map(renderStep)}
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
