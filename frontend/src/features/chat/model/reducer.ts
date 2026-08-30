import type { ChatTimelineItem } from "@/entities/message/model/types";
import type { TextAttachmentMetadata } from "@/entities/attachment/model/text-attachments";
import type {
  AiDeltaEvent,
  ChatRunEvent,
  ToolCallDeltaEvent,
  ToolResultEvent,
} from "@/features/chat/model/events";

export type ChatRunPhase =
  | "idle"
  | "connecting"
  | "streaming"
  | "stopping"
  | "completed"
  | "failed"
  | "cancelled";

export interface ChatRunFailure {
  readonly source: "server" | "protocol" | "client";
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
}

export interface ChatRunState {
  readonly phase: ChatRunPhase;
  readonly threadId: string | null;
  readonly runId: string | null;
  readonly lastSequence: number;
  readonly startedAt: string | null;
  readonly finishReason: string | null;
  readonly timeline: readonly ChatTimelineItem[];
  readonly error: ChatRunFailure | null;
}

export type ChatRunAction =
  | {
      readonly type: "run/requested";
      readonly threadId: string;
      readonly userMessage: {
        readonly id: string;
        readonly content: string;
        readonly attachments?: readonly TextAttachmentMetadata[];
      };
    }
  | { readonly type: "run/event-received"; readonly event: ChatRunEvent }
  | {
      readonly type: "run/client-failed";
      readonly error: Omit<ChatRunFailure, "source">;
    }
  | {
      readonly type: "run/status-reconciled";
      readonly run: {
        readonly runId: string;
        readonly threadId: string;
        readonly status:
          | "pending"
          | "running"
          | "completed"
          | "failed"
          | "cancelled"
          | "interrupted";
        readonly finishReason: string | null;
        readonly errorCode: string | null;
      };
    }
  | { readonly type: "run/cancel-requested" }
  | {
      readonly type: "run/cancel-failed";
      readonly error: Omit<ChatRunFailure, "source">;
    }
  | { readonly type: "run/cancelled" }
  | {
      readonly type: "thread/history-loaded";
      readonly threadId: string;
      readonly timeline: readonly ChatTimelineItem[];
    }
  | { readonly type: "thread/reset"; readonly threadId?: string | null };

export function createInitialChatRunState(
  threadId: string | null = null,
): ChatRunState {
  return {
    phase: "idle",
    threadId,
    runId: null,
    lastSequence: 0,
    startedAt: null,
    finishReason: null,
    timeline: [],
    error: null,
  };
}

function isActivePhase(phase: ChatRunPhase): boolean {
  return (
    phase === "connecting" || phase === "streaming" || phase === "stopping"
  );
}

function settlePendingTools(
  timeline: readonly ChatTimelineItem[],
  status: "failed" | "cancelled",
): readonly ChatTimelineItem[] {
  return timeline.map((item) =>
    item.kind === "tool" && item.status === "pending"
      ? { ...item, status }
      : item,
  );
}

function protocolFailure(
  state: ChatRunState,
  code: string,
  message: string,
  sequence = state.lastSequence,
): ChatRunState {
  return {
    ...state,
    phase: "failed",
    lastSequence: sequence,
    timeline: settlePendingTools(state.timeline, "failed"),
    error: {
      source: "protocol",
      code,
      message,
      retryable: false,
    },
  };
}

function replaceTimelineItem(
  timeline: readonly ChatTimelineItem[],
  index: number,
  replacement: ChatTimelineItem,
): readonly ChatTimelineItem[] {
  return [
    ...timeline.slice(0, index),
    replacement,
    ...timeline.slice(index + 1),
  ];
}

function mergeHistoryTimeline(
  history: readonly ChatTimelineItem[],
  current: readonly ChatTimelineItem[],
): readonly ChatTimelineItem[] {
  const currentById = new Map(current.map((item) => [item.id, item]));
  const historyIds = new Set(history.map((item) => item.id));
  return [
    // 相同身份出现于历史和实时流时保留当前项，它通常包含更靠后的增量。
    ...history.map((item) => {
      const currentItem = currentById.get(item.id);
      return currentItem === undefined ? item : { ...item, ...currentItem };
    }),
    ...current.filter((item) => !historyIds.has(item.id)),
  ];
}

function reduceAiDelta(state: ChatRunState, event: AiDeltaEvent): ChatRunState {
  // provider 偶尔可能不提供 message ID；run 内回退 ID 至少能稳定合并当前回答。
  const messageId = event.messageId ?? `${event.runId}:assistant`;
  const index = state.timeline.findIndex((item) => item.id === messageId);

  if (index === -1) {
    return {
      ...state,
      lastSequence: event.sequence,
      timeline: [
        ...state.timeline,
        {
          kind: "message",
          id: messageId,
          role: "assistant",
          content: event.payload.text,
        },
      ],
    };
  }

  const current = state.timeline[index];
  if (current?.kind !== "message" || current.role !== "assistant") {
    return protocolFailure(
      state,
      "message_id_collision",
      "模型消息 ID 与已有时间线项目冲突",
      event.sequence,
    );
  }
  return {
    ...state,
    lastSequence: event.sequence,
    timeline: replaceTimelineItem(state.timeline, index, {
      ...current,
      content: current.content + event.payload.text,
    }),
  };
}

function toolNameConflicts(
  currentName: string | null,
  incomingName: string | null,
): boolean {
  return (
    currentName !== null &&
    incomingName !== null &&
    currentName !== incomingName
  );
}

function reduceToolCallDelta(
  state: ChatRunState,
  event: ToolCallDeltaEvent,
): ChatRunState {
  const index = state.timeline.findIndex(
    (item) =>
      item.kind === "tool" && item.toolCallId === event.payload.toolCallId,
  );

  if (index === -1) {
    return {
      ...state,
      lastSequence: event.sequence,
      timeline: [
        ...state.timeline,
        {
          kind: "tool",
          id: `tool:${event.runId}:${event.payload.toolCallId}`,
          toolCallId: event.payload.toolCallId,
          name: event.payload.name,
          input: event.payload.argumentsDelta,
          result: null,
          status: "pending",
        },
      ],
    };
  }

  const current = state.timeline[index];
  if (current?.kind !== "tool") {
    return protocolFailure(
      state,
      "tool_id_collision",
      "工具调用 ID 与已有时间线项目冲突",
      event.sequence,
    );
  }
  if (current.status !== "pending") {
    return protocolFailure(
      state,
      "tool_already_settled",
      "已结束的工具调用不能继续接收参数增量",
      event.sequence,
    );
  }
  if (toolNameConflicts(current.name, event.payload.name)) {
    return protocolFailure(
      state,
      "tool_name_mismatch",
      "同一工具调用出现互相冲突的工具名",
      event.sequence,
    );
  }

  return {
    ...state,
    lastSequence: event.sequence,
    timeline: replaceTimelineItem(state.timeline, index, {
      ...current,
      name: current.name ?? event.payload.name,
      input: current.input + event.payload.argumentsDelta,
    }),
  };
}

function reduceToolResult(
  state: ChatRunState,
  event: ToolResultEvent,
): ChatRunState {
  const index = state.timeline.findIndex(
    (item) =>
      item.kind === "tool" && item.toolCallId === event.payload.toolCallId,
  );

  if (index === -1) {
    // 即使上游没有发送可见参数分片，也保留工具结果，避免丢失 Agent 执行事实。
    return {
      ...state,
      lastSequence: event.sequence,
      timeline: [
        ...state.timeline,
        {
          kind: "tool",
          id: `tool:${event.runId}:${event.payload.toolCallId}`,
          toolCallId: event.payload.toolCallId,
          name: event.payload.name,
          input: "",
          result: event.payload.content,
          status: "completed",
        },
      ],
    };
  }

  const current = state.timeline[index];
  if (current?.kind !== "tool") {
    return protocolFailure(
      state,
      "tool_id_collision",
      "工具调用 ID 与已有时间线项目冲突",
      event.sequence,
    );
  }
  if (current.status !== "pending") {
    return protocolFailure(
      state,
      "duplicate_tool_result",
      "同一工具调用收到多个结束结果",
      event.sequence,
    );
  }
  if (toolNameConflicts(current.name, event.payload.name)) {
    return protocolFailure(
      state,
      "tool_name_mismatch",
      "工具结果名称与原工具调用不一致",
      event.sequence,
    );
  }

  return {
    ...state,
    lastSequence: event.sequence,
    timeline: replaceTimelineItem(state.timeline, index, {
      ...current,
      name: current.name ?? event.payload.name,
      result: event.payload.content,
      status: "completed",
    }),
  };
}

function reduceRunEvent(
  state: ChatRunState,
  event: ChatRunEvent,
): ChatRunState {
  if (state.threadId === null || event.threadId !== state.threadId) {
    return protocolFailure(
      state,
      "thread_id_mismatch",
      "事件不属于当前聊天线程",
      event.sequence,
    );
  }
  if (state.runId !== null && event.runId !== state.runId) {
    return protocolFailure(
      state,
      "run_id_mismatch",
      "事件不属于当前 Agent run",
      event.sequence,
    );
  }

  // 未来重连可能重放已经处理过的事件；旧 sequence 不得再次追加正文或工具参数。
  if (state.runId === event.runId && event.sequence <= state.lastSequence) {
    return state;
  }
  if (!isActivePhase(state.phase)) {
    return protocolFailure(
      state,
      "event_after_terminal_state",
      "已结束的 run 不能继续接收新事件",
      event.sequence,
    );
  }
  if (event.sequence !== state.lastSequence + 1) {
    return protocolFailure(
      state,
      "sequence_gap",
      "run 事件 sequence 出现缺口或乱序",
      event.sequence,
    );
  }

  if (state.runId === null) {
    if (
      (state.phase !== "connecting" && state.phase !== "stopping") ||
      event.event !== "run_started"
    ) {
      return protocolFailure(
        state,
        "missing_run_started",
        "第一条 run 事件必须是 run_started",
        event.sequence,
      );
    }
  } else if (
    (state.phase !== "streaming" && state.phase !== "stopping") ||
    event.event === "run_started"
  ) {
    return protocolFailure(
      state,
      "invalid_run_lifecycle",
      "run_started 只能作为本轮第一条事件",
      event.sequence,
    );
  }

  switch (event.event) {
    case "run_started":
      return {
        ...state,
        phase: state.phase === "stopping" ? "stopping" : "streaming",
        runId: event.runId,
        lastSequence: event.sequence,
        startedAt: event.payload.createdAt,
      };
    case "ai_delta":
      return reduceAiDelta(state, event);
    case "tool_call_delta":
      return reduceToolCallDelta(state, event);
    case "tool_result":
      return reduceToolResult(state, event);
    case "run_error":
      return {
        ...state,
        phase: "failed",
        lastSequence: event.sequence,
        timeline: settlePendingTools(state.timeline, "failed"),
        error: {
          source: "server",
          code: event.payload.code,
          message: event.payload.message,
          retryable: event.payload.retryable,
        },
      };
    case "run_interrupted":
      return {
        ...state,
        phase: "cancelled",
        lastSequence: event.sequence,
        finishReason: event.payload.reason,
        timeline: settlePendingTools(state.timeline, "cancelled"),
        error: null,
      };
    case "run_completed":
      if (
        state.timeline.some(
          (item) => item.kind === "tool" && item.status === "pending",
        )
      ) {
        return protocolFailure(
          state,
          "unsettled_tool_call",
          "run 完成时仍有工具调用没有结果",
          event.sequence,
        );
      }
      return {
        ...state,
        phase: "completed",
        lastSequence: event.sequence,
        finishReason: event.payload.finishReason,
        error: null,
      };
  }
}

export function chatRunReducer(
  state: ChatRunState,
  action: ChatRunAction,
): ChatRunState {
  switch (action.type) {
    case "run/requested": {
      // UI 连点由 hook 的 in-flight guard 阻止；reducer 仍保持幂等而不破坏当前流。
      if (isActivePhase(state.phase)) {
        return state;
      }
      if (
        action.threadId.length === 0 ||
        action.userMessage.id.length === 0 ||
        action.userMessage.content.trim().length === 0
      ) {
        return protocolFailure(
          state,
          "invalid_run_request",
          "本地 run 请求缺少线程或用户消息",
        );
      }

      const previousTimeline =
        state.threadId === action.threadId ? state.timeline : [];
      if (previousTimeline.some((item) => item.id === action.userMessage.id)) {
        return protocolFailure(
          state,
          "duplicate_message_id",
          "用户消息 ID 已存在于当前时间线",
        );
      }
      return {
        phase: "connecting",
        threadId: action.threadId,
        runId: null,
        lastSequence: 0,
        startedAt: null,
        finishReason: null,
        timeline: [
          ...previousTimeline,
          {
            kind: "message",
            id: action.userMessage.id,
            role: "user",
            content: action.userMessage.content,
            ...(action.userMessage.attachments?.length
              ? { attachments: action.userMessage.attachments }
              : {}),
          },
        ],
        error: null,
      };
    }
    case "run/event-received":
      return reduceRunEvent(state, action.event);
    case "run/client-failed":
      return {
        ...state,
        phase: "failed",
        timeline: settlePendingTools(state.timeline, "failed"),
        error: { source: "client", ...action.error },
      };
    case "run/status-reconciled": {
      if (!isActivePhase(state.phase)) {
        return state;
      }
      if (
        state.threadId !== action.run.threadId ||
        (state.runId !== null && state.runId !== action.run.runId)
      ) {
        return protocolFailure(
          state,
          "reconciled_run_id_mismatch",
          "持久化 Run 状态不属于当前运行",
        );
      }
      if (action.run.status === "pending" || action.run.status === "running") {
        return state;
      }
      if (action.run.status === "completed") {
        return {
          ...state,
          phase: "completed",
          runId: action.run.runId,
          finishReason: action.run.finishReason,
          error: null,
        };
      }
      if (action.run.status === "failed") {
        return {
          ...state,
          phase: "failed",
          runId: action.run.runId,
          timeline: settlePendingTools(state.timeline, "failed"),
          error: {
            source: "server",
            code: action.run.errorCode ?? "run_failed",
            message: "Run 已在服务端记录为失败",
            retryable: true,
          },
        };
      }
      return {
        ...state,
        phase: "cancelled",
        runId: action.run.runId,
        finishReason:
          action.run.finishReason ?? action.run.errorCode ?? "interrupted",
        timeline: settlePendingTools(state.timeline, "cancelled"),
        error: null,
      };
    }
    case "run/cancel-requested":
      return state.phase === "connecting" || state.phase === "streaming"
        ? { ...state, phase: "stopping", error: null }
        : state;
    case "run/cancel-failed":
      return state.phase === "stopping"
        ? {
            ...state,
            phase: "streaming",
            error: { source: "client", ...action.error },
          }
        : state;
    case "run/cancelled":
      return isActivePhase(state.phase)
        ? {
            ...state,
            phase: "cancelled",
            timeline: settlePendingTools(state.timeline, "cancelled"),
            error: null,
          }
        : state;
    case "thread/history-loaded":
      if (state.threadId !== action.threadId) {
        return state;
      }
      return {
        ...state,
        timeline: mergeHistoryTimeline(action.timeline, state.timeline),
      };
    case "thread/reset":
      return createInitialChatRunState(action.threadId ?? null);
  }
}
