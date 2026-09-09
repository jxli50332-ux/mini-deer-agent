import type {
  ChatTimelineItem,
  MessageTimelineItem,
} from "@/entities/message/model/types";
import type { ChatRunPhase } from "@/features/chat/model/reducer";
import { completedRunSeconds } from "@/features/chat/model/run-timing";

export type ConversationTurnStatus =
  "streaming" | "final" | "failed" | "cancelled";

export type ConversationRunTimingView =
  | {
      readonly kind: "active";
      readonly startedAt: string;
    }
  | {
      readonly kind: "settled";
      readonly durationSeconds: number;
      readonly outcome: "completed" | "failed" | "cancelled";
      readonly finishReason?: string | null;
      readonly totalTokens?: number | null;
      readonly modelCalls?: number | null;
    };

export interface ConversationRunTimingSource {
  readonly runId: string;
  readonly userMessageId: string;
  readonly status:
    | "pending"
    | "running"
    | "completed"
    | "failed"
    | "cancelled"
    | "interrupted";
  readonly startedAt: string | null;
  readonly finishedAt: string | null;
  readonly finishReason?: string | null;
  readonly totalTokens?: number | null;
  readonly modelCalls?: number | null;
}

export interface ConversationTurnView {
  readonly id: string;
  readonly user: MessageTimelineItem | null;
  readonly steps: readonly ChatTimelineItem[];
  readonly status: ConversationTurnStatus;
  readonly timing?: ConversationRunTimingView;
}

interface MutableConversationTurn {
  readonly id: string;
  readonly user: MessageTimelineItem | null;
  readonly steps: ChatTimelineItem[];
}

function isUserMessage(
  item: ChatTimelineItem,
): item is MessageTimelineItem & { readonly role: "user" } {
  return item.kind === "message" && item.role === "user";
}

function statusFromPhase(phase: ChatRunPhase): ConversationTurnStatus {
  switch (phase) {
    case "connecting":
    case "streaming":
    case "stopping":
      return "streaming";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    case "idle":
    case "completed":
      return "final";
  }
}

function settledTimingFromRun(
  run: ConversationRunTimingSource | undefined,
): ConversationRunTimingView | undefined {
  if (
    run === undefined ||
    run.startedAt === null ||
    run.finishedAt === null ||
    run.status === "pending" ||
    run.status === "running"
  ) {
    return undefined;
  }
  const durationSeconds = completedRunSeconds(run.startedAt, run.finishedAt);
  if (durationSeconds === null) {
    return undefined;
  }
  return {
    kind: "settled",
    durationSeconds,
    outcome:
      run.status === "completed"
        ? "completed"
        : run.status === "failed"
          ? "failed"
          : "cancelled",
    ...(run.finishReason === undefined
      ? {}
      : { finishReason: run.finishReason }),
    ...(run.totalTokens === undefined ? {} : { totalTokens: run.totalTokens }),
    ...(run.modelCalls === undefined ? {} : { modelCalls: run.modelCalls }),
  };
}

/**
 * 把 reducer 的扁平业务时间线投影成仅供 UI 使用的稳定轮次。
 * 用户消息开启新轮次，其后的 Assistant 消息和工具保持服务端原顺序。
 */
export function projectConversation(
  timeline: readonly ChatTimelineItem[],
  phase: ChatRunPhase,
  activeRunStartedAt: string | null = null,
  runs: readonly ConversationRunTimingSource[] = [],
): readonly ConversationTurnView[] {
  const turns: MutableConversationTurn[] = [];
  let currentTurn: MutableConversationTurn | null = null;

  for (const item of timeline) {
    if (item.kind === "message" && item.hiddenFromUi === true) {
      continue;
    }
    if (isUserMessage(item)) {
      if (currentTurn !== null) {
        turns.push(currentTurn);
      }
      currentTurn = {
        id: `turn:${item.id}`,
        user: item,
        steps: [],
      };
      continue;
    }

    if (currentTurn === null) {
      // 兼容分页边界或旧数据从 Assistant/工具项目开始的情况。
      currentTurn = {
        id: `turn:${item.id}`,
        user: null,
        steps: [],
      };
    }
    currentTurn.steps.push(item);
  }

  if (currentTurn !== null) {
    turns.push(currentTurn);
  }

  const lastTurnIndex = turns.length - 1;
  const runByUserMessageId = new Map(
    runs.map((run) => [run.userMessageId, run] as const),
  );
  return turns.map((turn, index) => {
    const status =
      index === lastTurnIndex ? statusFromPhase(phase) : ("final" as const);
    const activeTiming =
      index === lastTurnIndex &&
      status === "streaming" &&
      activeRunStartedAt !== null
        ? ({
            kind: "active",
            startedAt: activeRunStartedAt,
          } satisfies ConversationRunTimingView)
        : undefined;
    const settledTiming = settledTimingFromRun(
      turn.user === null ? undefined : runByUserMessageId.get(turn.user.id),
    );
    const timing = activeTiming ?? settledTiming;
    return {
      ...turn,
      status,
      ...(timing === undefined ? {} : { timing }),
    };
  });
}
