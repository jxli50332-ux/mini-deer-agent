import { useEffect, useId, useRef, useState } from "react";

import {
  COT_NAVIGATION_EVENT,
  cotStepDomId,
  navigateToTodo,
  type CotNavigationDetail,
} from "@/features/chat/model/cot-navigation";
import type {
  CotStep,
  CotStepIcon,
  SubagentStepDetail,
} from "@/features/chat/model/project-cot";
import { MessageContent } from "@/features/chat/ui/MessageContent";

interface CotTimelineProps {
  readonly steps: readonly CotStep[];
}

const ICON_LABEL: Record<CotStepIcon, string> = {
  reasoning: "思",
  message: "述",
  search: "搜",
  web: "网",
  todo: "单",
  file: "文",
  task: "派",
  tool: "具",
};

const STATUS_LABEL = {
  pending: "进行中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  timed_out: "已超时",
} as const;

const LONG_REASONING_CHARACTER_LIMIT = 700;
const LONG_REASONING_LINE_LIMIT = 10;

function ReasoningDisclosure({ text }: { readonly text: string }) {
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();
  const isLong =
    text.length > LONG_REASONING_CHARACTER_LIMIT ||
    text.split(/\r?\n/).length > LONG_REASONING_LINE_LIMIT;

  if (!isLong) {
    return <MessageContent role="assistant" content={text} />;
  }

  return (
    <div className="cot-step__reasoning" data-expanded={expanded}>
      <div id={contentId} className="cot-step__reasoning-content">
        <MessageContent role="assistant" content={text} />
      </div>
      <button
        type="button"
        className="cot-step__reasoning-toggle"
        aria-expanded={expanded}
        aria-controls={contentId}
        onClick={() => setExpanded((current) => !current)}
      >
        {expanded ? "收起思考" : "展开完整思考"}
      </button>
    </div>
  );
}

function formatDuration(durationMs: number | null): string | null {
  if (durationMs === null) return null;
  if (durationMs < 1_000) return `${durationMs} ms`;
  return `${(durationMs / 1_000).toFixed(durationMs < 10_000 ? 1 : 0)} s`;
}

function SubagentDisclosure({ agent }: { readonly agent: SubagentStepDetail }) {
  const duration = formatDuration(agent.durationMs);
  const lifecycleFacts = [
    duration === null ? null : `耗时 ${duration}`,
    agent.totalTokens === null ? null : `${agent.totalTokens} tokens`,
    agent.modelCalls === null ? null : `${agent.modelCalls} 次模型调用`,
  ].filter((value): value is string => value !== null);

  return (
    <details
      className="subagent-step"
      data-status={agent.status}
      open={agent.status === "failed" || agent.status === "timed_out"}
    >
      <summary className="subagent-step__summary">
        <span className="subagent-step__identity">
          <strong>{agent.name}</strong>
          {agent.description !== null && <span>{agent.description}</span>}
        </span>
        <span className="subagent-step__status">
          {STATUS_LABEL[agent.status]}
        </span>
        <span className="subagent-step__toggle" aria-hidden="true">
          ▾
        </span>
      </summary>
      <div className="subagent-step__content">
        {lifecycleFacts.length > 0 && (
          <p className="subagent-step__facts">{lifecycleFacts.join(" · ")}</p>
        )}
        {agent.stopReason !== null && (
          <p className="subagent-step__stop">
            <strong>停止原因</strong>
            <span>{agent.stopReason}</span>
          </p>
        )}
        {agent.resultSummary !== null && (
          <div className="subagent-step__result">
            <strong>结果摘要</strong>
            <p>{agent.resultSummary}</p>
          </div>
        )}
        {agent.rawResult !== null && (
          <details className="subagent-step__raw">
            <summary>查看原始结果</summary>
            <pre>{agent.rawResult}</pre>
          </details>
        )}
        {agent.rawResult === null && agent.status === "running" && (
          <p className="subagent-step__placeholder">等待 Agent 返回结果……</p>
        )}
      </div>
    </details>
  );
}

function CotStepRow({
  step,
  highlighted,
}: {
  readonly step: CotStep;
  readonly highlighted: boolean;
}) {
  const isTextStep = step.kind === "reasoning" || step.kind === "message";
  const statusLabel =
    step.status === undefined ? null : STATUS_LABEL[step.status];

  return (
    <li
      id={cotStepDomId(step.id)}
      className="cot-step"
      data-kind={step.kind}
      data-highlighted={highlighted}
      {...(step.status === undefined ? {} : { "data-status": step.status })}
      {...(step.kind !== "tool"
        ? {}
        : {
            role: "status",
            "aria-label":
              `工具 ${step.toolName ?? "未知工具"} ${statusLabel ?? ""}`.trim(),
          })}
    >
      <span className="cot-step__rail" aria-hidden="true">
        <span className="cot-step__icon">{ICON_LABEL[step.icon]}</span>
      </span>
      <div className="cot-step__body">
        {step.subagent !== undefined ? (
          <SubagentDisclosure agent={step.subagent} />
        ) : (
          <>
            <div className="cot-step__main">
              {step.kind === "reasoning" ? (
                <ReasoningDisclosure text={step.text} />
              ) : isTextStep ? (
                <MessageContent role="assistant" content={step.text} />
              ) : step.icon === "todo" && step.todoContents !== undefined ? (
                <button
                  type="button"
                  className="cot-step__todo-link"
                  onClick={() => navigateToTodo(step.id)}
                >
                  {step.text}
                  <span aria-hidden="true">↘</span>
                </button>
              ) : (
                <span className="cot-step__label">{step.text}</span>
              )}
              {statusLabel !== null && step.status !== "completed" && (
                <span className="cot-step__status">{statusLabel}</span>
              )}
            </div>
            {step.detail !== undefined && (
              <p className="cot-step__detail">{step.detail}</p>
            )}
            {step.links !== undefined && step.links.length > 0 && (
              <ul className="cot-step__links" aria-label="步骤相关链接">
                {step.links.map((link) => (
                  <li key={link.url}>
                    <a
                      href={link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </li>
  );
}

export function CotTimeline({ steps }: CotTimelineProps) {
  const [expanded, setExpanded] = useState(false);
  const [highlightedStepId, setHighlightedStepId] = useState<string | null>(
    null,
  );
  const contentId = useId();
  const highlightTimerRef = useRef<number | null>(null);

  useEffect(() => {
    const handleNavigation = (event: Event) => {
      const { stepId } = (event as CustomEvent<CotNavigationDetail>).detail;
      if (!steps.some((step) => step.id === stepId)) {
        return;
      }
      setExpanded(true);
      setHighlightedStepId(stepId);
      if (highlightTimerRef.current !== null) {
        window.clearTimeout(highlightTimerRef.current);
      }
      window.setTimeout(() => {
        document
          .getElementById(cotStepDomId(stepId))
          ?.scrollIntoView?.({ behavior: "smooth", block: "center" });
      }, 0);
      highlightTimerRef.current = window.setTimeout(
        () => setHighlightedStepId(null),
        1400,
      );
    };
    window.addEventListener(COT_NAVIGATION_EVENT, handleNavigation);
    return () => {
      window.removeEventListener(COT_NAVIGATION_EVENT, handleNavigation);
      if (highlightTimerRef.current !== null) {
        window.clearTimeout(highlightTimerRef.current);
      }
    };
  }, [steps]);

  if (steps.length === 0) {
    return null;
  }

  const hiddenStepCount = Math.max(steps.length - 1, 0);
  const visibleSteps =
    expanded || hiddenStepCount === 0 ? steps : steps.slice(-1);

  return (
    <section className="cot-timeline" aria-label="思考与执行步骤">
      {hiddenStepCount > 0 && (
        <button
          type="button"
          className="cot-timeline__toggle"
          aria-expanded={expanded}
          aria-controls={contentId}
          onClick={() => setExpanded((current) => !current)}
        >
          <span className="cot-timeline__chevron" aria-hidden="true">
            ⌃
          </span>
          {expanded ? "收起步骤" : `查看其他 ${hiddenStepCount} 个步骤`}
        </button>
      )}
      <ol id={contentId} className="cot-timeline__steps">
        {visibleSteps.map((step) => (
          <CotStepRow
            key={step.id}
            step={step}
            highlighted={step.id === highlightedStepId}
          />
        ))}
      </ol>
    </section>
  );
}
