import { useEffect, useState } from "react";

import {
  elapsedRunSeconds,
  formatRunDuration,
} from "@/features/chat/model/run-timing";
import type { ConversationRunTimingView } from "@/features/chat/model/project-conversation";

interface RunTimingProps {
  readonly timing: ConversationRunTimingView;
}

/**
 * 展示服务端 Run 起点驱动的实时 wall-clock。
 * 秒数仅供视觉反馈，不进入 aria-live，避免读屏软件每秒重复播报。
 */
function ActiveRunTiming({ startedAt }: { readonly startedAt: string }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, []);

  const duration = elapsedRunSeconds(startedAt, now);
  const formatted = duration === null ? null : formatRunDuration(duration);
  if (formatted === null) {
    return null;
  }

  return (
    <div
      className="run-timing"
      data-testid="run-timing"
      aria-label="Agent 正在执行"
      aria-live="off"
    >
      <span className="run-timing__clock" aria-hidden="true">
        ◷
      </span>
      <span>执行中</span>
      <span className="run-timing__elapsed" aria-hidden="true">
        （{formatted}）
      </span>
    </div>
  );
}

const SETTLED_LABEL = {
  completed: "执行完成",
  failed: "执行失败",
  cancelled: "执行已停止",
} as const;

const CAPPED_REASON_LABEL: Readonly<Record<string, string>> = {
  token_capped: "Token 预算已达上限",
  turn_capped: "模型轮次预算已达上限",
  loop_capped: "重复工具调用已安全收敛",
};

export function RunTiming({ timing }: RunTimingProps) {
  if (timing.kind === "active") {
    return <ActiveRunTiming startedAt={timing.startedAt} />;
  }

  const formatted = formatRunDuration(timing.durationSeconds);
  if (formatted === null) {
    return null;
  }
  const label = SETTLED_LABEL[timing.outcome];
  const reasonLabel =
    timing.finishReason === undefined || timing.finishReason === null
      ? undefined
      : CAPPED_REASON_LABEL[timing.finishReason];
  const usageLabel = [
    timing.totalTokens === undefined || timing.totalTokens === null
      ? null
      : `${timing.totalTokens.toLocaleString("zh-CN")} tokens`,
    timing.modelCalls === undefined || timing.modelCalls === null
      ? null
      : `${timing.modelCalls} 次模型调用`,
  ]
    .filter((value): value is string => value !== null)
    .join("，");
  const detailLabel = [reasonLabel, usageLabel || null]
    .filter((value): value is string => value !== undefined && value !== null)
    .join("；");
  const ariaLabel = `${label}，用时 ${formatted}${
    detailLabel ? `；${detailLabel}` : ""
  }`;
  return (
    <div
      className="run-timing"
      data-testid="run-timing"
      data-outcome={timing.outcome}
      aria-label={ariaLabel}
    >
      <span className="run-timing__clock" aria-hidden="true">
        ◷
      </span>
      <span>{label}</span>
      <span className="run-timing__elapsed">，用时 {formatted}</span>
      {detailLabel && (
        <span className="run-timing__budget">；{detailLabel}</span>
      )}
    </div>
  );
}
