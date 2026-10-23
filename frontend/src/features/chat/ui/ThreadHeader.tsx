import type { ChatRunPhase } from "@/features/chat/model/reducer";
import { StatusIndicator } from "@/shared/ui/StatusIndicator";
import { OfficeDocumentsButton } from "@/features/office/ui/OfficeDocumentCards";

interface ThreadHeaderProps {
  readonly phase: ChatRunPhase;
  readonly threadId: string;
  readonly runId: string | null;
  readonly modelProfile?: string | null;
  readonly navigationOpen: boolean;
  readonly onOpenNavigation: () => void;
  readonly onOpenBenchmarks: () => void;
}

const PHASE_LABELS: Record<ChatRunPhase, string> = {
  idle: "就绪",
  connecting: "正在连接",
  streaming: "正在生成",
  stopping: "正在停止",
  completed: "已完成",
  failed: "运行失败",
  cancelled: "已取消",
};

export function ThreadHeader({
  phase,
  threadId,
  runId,
  modelProfile = null,
  navigationOpen,
  onOpenNavigation,
  onOpenBenchmarks,
}: ThreadHeaderProps) {
  return (
    <header className="thread-header" data-phase={phase}>
      <button
        type="button"
        className="mobile-navigation-toggle"
        aria-label="打开会话导航"
        aria-controls="conversation-navigation"
        aria-expanded={navigationOpen}
        onClick={onOpenNavigation}
      >
        ☰
      </button>
      <div className="thread-header__identity">
        <p className="thread-header__eyebrow">当前线程</p>
        <h1>Mini Deer 对话</h1>
      </div>
      <div className="thread-header__status">
        <OfficeDocumentsButton />
        <button
          type="button"
          className="benchmark-open-button"
          onClick={onOpenBenchmarks}
        >
          能力基准
        </button>
        <StatusIndicator label={PHASE_LABELS[phase]} />
        {modelProfile !== null && (
          <span
            className="thread-id"
            title={`实际模型 Profile: ${modelProfile}`}
          >
            model {modelProfile}
          </span>
        )}
        <span className="thread-id" title={`thread_id: ${threadId}`}>
          thread {threadId.slice(0, 8)}
        </span>
        {runId !== null && (
          <span className="thread-id" title={`run_id: ${runId}`}>
            run {runId.slice(0, 8)}
          </span>
        )}
      </div>
    </header>
  );
}
