import type { TextAttachmentMetadata } from "@/entities/attachment/model/text-attachments";

export type MessageRole = "assistant" | "user";

export interface MessageTimelineItem {
  readonly kind: "message";
  readonly id: string;
  readonly role: MessageRole;
  readonly content: string;
  readonly attachments?: readonly TextAttachmentMetadata[];
}

export interface ToolTimelineItem {
  readonly kind: "tool";
  readonly id: string;
  readonly toolCallId: string;
  readonly name: string | null;
  readonly input: string;
  readonly result: string | null;
  readonly status: "pending" | "completed" | "failed" | "cancelled";
}

// 时间线使用判别联合，后续 reducer 收到 SSE 事件时可以安全区分消息和工具活动。
export type ChatTimelineItem = MessageTimelineItem | ToolTimelineItem;

export interface HistoryTimelineMetadata {
  /** 标识产生该项目的 Run，供历史追踪和后续重试使用。 */
  readonly runId: string;
  /** Thread 范围内的稳定顺序，不依赖可能相同的时间戳。 */
  readonly threadSequence: number;
  readonly createdAt: string;
}

// 历史 API 项目保留现有展示形状，并增加服务端持久化元数据。
export type ThreadHistoryItem = ChatTimelineItem & HistoryTimelineMetadata;
