import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import type { ChatTimelineItem } from "@/entities/message/model/types";
import type { PreparedAttachment } from "@/entities/attachment/model/attachments";
import {
  cancelChatRun,
  ChatStreamClientError,
  reconcileChatRunAfterDisconnect,
  streamChatRun,
  type ChatRunCancelRequest,
  type ChatRunDetail,
  type ChatRunReconciler,
  type ChatStreamRequest,
} from "@/features/chat/api/chat-stream";
import type { ChatRunEvent } from "@/features/chat/model/events";
import type { HumanInputResponse } from "@/features/chat/model/human-input";
import {
  chatRunReducer,
  createInitialChatRunState,
  type ChatRunAction,
  type ChatRunFailure,
  type ChatRunState,
} from "@/features/chat/model/reducer";

export type ChatStreamRunner = (
  request: ChatStreamRequest,
) => AsyncIterable<ChatRunEvent>;
export type ChatRunCanceller = (request: ChatRunCancelRequest) => Promise<void>;
const TERMINAL_EVENT_NAMES = new Set([
  "run_completed",
  "run_error",
  "run_interrupted",
]);

export interface UseChatRunOptions {
  readonly threadId: string;
  readonly streamRunner?: ChatStreamRunner;
  readonly cancelRunner?: ChatRunCanceller;
  readonly runReconciler?: ChatRunReconciler;
  readonly createMessageId?: () => string;
  readonly onRunRequested?: (threadId: string) => void;
  readonly onRunStarted?: (threadId: string, runId: string) => void;
  readonly onRunSettled?: (threadId: string, runId: string) => void;
  readonly onEventReceived?: (event: ChatRunEvent) => void;
}

export interface UseChatRunResult {
  readonly state: ChatRunState;
  readonly isActive: boolean;
  readonly activeThreadIds: readonly string[];
  readonly hydrateHistory: (
    threadId: string,
    timeline: readonly ChatTimelineItem[],
  ) => void;
  readonly submit: (
    message: string,
    attachments?: readonly PreparedAttachment[],
    submitOptions?: ChatSubmitOptions,
  ) => Promise<boolean>;
  readonly cancel: () => Promise<boolean>;
}

export interface ChatSubmitOptions {
  readonly humanInputResponse?: HumanInputResponse;
  readonly benchmarkCaseId?: string;
  readonly goalResumeRevision?: string;
  readonly skillInstallAuthorizationToken?: string;
}

interface ActiveOperation {
  readonly id: number;
  readonly threadId: string;
  readonly controller: AbortController;
  runId: string | null;
  cancelRequested: boolean;
}

function defaultCreateMessageId(): string {
  return globalThis.crypto.randomUUID();
}

function toClientFailure(
  error: unknown,
): Omit<ChatRunFailure, "source"> | null {
  if (error instanceof ChatStreamClientError) {
    if (error.code === "aborted") {
      return null;
    }
    return {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
    };
  }

  // 未知异常只转换成固定公开信息，不把 SDK、浏览器或用户正文泄露给 UI。
  return {
    code: "unexpected_client_error",
    message: "聊天客户端发生未知错误",
    retryable: true,
  };
}

function isActiveState(state: ChatRunState): boolean {
  return (
    state.phase === "connecting" ||
    state.phase === "streaming" ||
    state.phase === "stopping"
  );
}

function isUncertainConnectionFailure(error: unknown): boolean {
  return (
    error instanceof ChatStreamClientError &&
    (error.code === "stream_inactive" ||
      error.code === "network_error" ||
      error.code === "incomplete_stream")
  );
}

function isTerminalRun(detail: ChatRunDetail): boolean {
  return detail.status !== "pending" && detail.status !== "running";
}

/**
 * 连接一次 POST SSE run 与纯 reducer，并管理浏览器异步任务的完整生命周期。
 * 页面组件只调用 submit/cancel 和读取 state，不接触 fetch 或 AbortController。
 */
export function useChatRun(options: UseChatRunOptions): UseChatRunResult {
  const { threadId } = options;
  const onRunRequested = options.onRunRequested;
  const onRunStarted = options.onRunStarted;
  const onRunSettled = options.onRunSettled;
  const onEventReceived = options.onEventReceived;
  const streamRunner = options.streamRunner ?? streamChatRun;
  const cancelRunner = options.cancelRunner ?? cancelChatRun;
  const runReconciler =
    options.runReconciler ?? reconcileChatRunAfterDisconnect;
  const createMessageId = options.createMessageId ?? defaultCreateMessageId;
  const [renderedState, setRenderedState] = useState(() =>
    createInitialChatRunState(threadId),
  );
  const [activeThreadIds, setActiveThreadIds] = useState<readonly string[]>([]);

  const statesRef = useRef(
    new Map<string, ChatRunState>([
      [threadId, createInitialChatRunState(threadId)],
    ]),
  );
  const activeOperationsRef = useRef(new Map<string, ActiveOperation>());
  const nextOperationIdRef = useRef(1);
  const currentThreadIdRef = useRef(threadId);
  const previousThreadIdRef = useRef(threadId);

  useLayoutEffect(() => {
    // 切换只替换当前视图；其他 Thread 的状态和 SSE 消费继续独立推进。
    currentThreadIdRef.current = threadId;
    if (previousThreadIdRef.current === threadId) {
      return;
    }
    previousThreadIdRef.current = threadId;
    const next =
      statesRef.current.get(threadId) ?? createInitialChatRunState(threadId);
    statesRef.current.set(threadId, next);
    setRenderedState(next);
  }, [threadId]);

  useEffect(
    () => () => {
      // 页面卸载才终止全部本地订阅；普通 Thread 切换不会触碰后台 Run。
      for (const operation of activeOperationsRef.current.values()) {
        operation.controller.abort();
      }
      activeOperationsRef.current.clear();
    },
    [],
  );

  const dispatchForThread = useCallback(
    (targetThreadId: string, action: ChatRunAction): void => {
      const current =
        statesRef.current.get(targetThreadId) ??
        createInitialChatRunState(targetThreadId);
      const next = chatRunReducer(current, action);
      statesRef.current.set(targetThreadId, next);
      if (currentThreadIdRef.current === targetThreadId) {
        setRenderedState(next);
      }
    },
    [],
  );

  const submit = useCallback(
    async (
      rawMessage: string,
      attachments: readonly PreparedAttachment[] = [],
      submitOptions: ChatSubmitOptions = {},
    ): Promise<boolean> => {
      if (activeOperationsRef.current.has(threadId)) {
        return false;
      }

      const message = rawMessage.trim();
      if (message.length === 0) {
        return false;
      }

      const userMessageId = createMessageId();
      if (userMessageId.length === 0) {
        return false;
      }

      const operation: ActiveOperation = {
        id: nextOperationIdRef.current,
        threadId,
        controller: new AbortController(),
        runId: null,
        cancelRequested: false,
      };
      nextOperationIdRef.current += 1;
      activeOperationsRef.current.set(threadId, operation);
      setActiveThreadIds((current) =>
        current.includes(threadId) ? current : [...current, threadId],
      );
      onRunRequested?.(threadId);

      dispatchForThread(threadId, {
        type: "run/requested",
        threadId,
        userMessage: {
          id: userMessageId,
          content: message,
          attachments: attachments.map(
            ({ filename, mediaType, sizeBytes, content }) => ({
              filename,
              mediaType,
              sizeBytes,
              content,
            }),
          ),
          ...(submitOptions.humanInputResponse === undefined
            ? {}
            : {
                hiddenFromUi: true,
                humanInputResponse: submitOptions.humanInputResponse,
              }),
          ...(submitOptions.goalResumeRevision === undefined
            ? {}
            : { hiddenFromUi: true }),
        },
      });

      const isCurrentOperation = () =>
        activeOperationsRef.current.get(operation.threadId)?.id ===
        operation.id;

      try {
        for await (const event of streamRunner({
          threadId,
          messageId: userMessageId,
          message,
          attachments: attachments.map(({ filename, content }) => ({
            filename,
            content,
          })),
          ...(submitOptions.humanInputResponse === undefined
            ? {}
            : { humanInputResponse: submitOptions.humanInputResponse }),
          ...(submitOptions.benchmarkCaseId === undefined
            ? {}
            : { benchmarkCaseId: submitOptions.benchmarkCaseId }),
          ...(submitOptions.goalResumeRevision === undefined
            ? {}
            : { goalResumeRevision: submitOptions.goalResumeRevision }),
          ...(submitOptions.skillInstallAuthorizationToken === undefined
            ? {}
            : {
                skillInstallAuthorizationToken:
                  submitOptions.skillInstallAuthorizationToken,
              }),
          signal: operation.controller.signal,
          onRunId: (runId) => {
            // 响应头先建立取消寻址；旧 operation 的回调不能覆盖当前 Run。
            if (isCurrentOperation()) {
              operation.runId = runId;
              onRunStarted?.(operation.threadId, runId);
            }
          },
        })) {
          if (!isCurrentOperation()) {
            return false;
          }
          if (operation.runId === null) {
            operation.runId = event.runId;
            if (event.event === "run_started") {
              onRunStarted?.(operation.threadId, event.runId);
            }
          }
          dispatchForThread(operation.threadId, {
            type: "run/event-received",
            event,
          });
          onEventReceived?.(event);
          if (TERMINAL_EVENT_NAMES.has(event.event)) {
            onRunSettled?.(operation.threadId, event.runId);
          }
        }
        return isCurrentOperation();
      } catch (error) {
        if (!isCurrentOperation()) {
          return false;
        }

        const failure = toClientFailure(error);
        if (operation.controller.signal.aborted || failure === null) {
          dispatchForThread(operation.threadId, { type: "run/cancelled" });
        } else {
          if (operation.runId !== null && isUncertainConnectionFailure(error)) {
            try {
              const run = await runReconciler({
                threadId: operation.threadId,
                runId: operation.runId,
                signal: operation.controller.signal,
              });
              if (!isCurrentOperation()) {
                return false;
              }
              if (isTerminalRun(run)) {
                dispatchForThread(operation.threadId, {
                  type: "run/status-reconciled",
                  run,
                });
                onRunSettled?.(operation.threadId, run.runId);
                return true;
              }
              // 服务端仍在运行时不能只丢掉本地 operation；主动取消后再次
              // 核对终态，避免下一次提交稳定命中 thread_busy。
              await cancelRunner({
                threadId: operation.threadId,
                runId: operation.runId,
              });
              const cancelledRun = await runReconciler({
                threadId: operation.threadId,
                runId: operation.runId,
                signal: operation.controller.signal,
              });
              if (!isCurrentOperation()) {
                return false;
              }
              if (isTerminalRun(cancelledRun)) {
                dispatchForThread(operation.threadId, {
                  type: "run/status-reconciled",
                  run: cancelledRun,
                });
                onRunSettled?.(operation.threadId, cancelledRun.runId);
                return true;
              }
            } catch {
              // 状态查询失败不能覆盖最初的连接错误，更不能伪装已经恢复。
              if (!isCurrentOperation()) {
                return false;
              }
            }
          }
          dispatchForThread(operation.threadId, {
            type: "run/client-failed",
            error: failure,
            ...(operation.runId === null && failure.code === "run_conflict"
              ? { optimisticMessageId: userMessageId }
              : {}),
          });
        }
        return false;
      } finally {
        if (
          activeOperationsRef.current.get(operation.threadId)?.id ===
          operation.id
        ) {
          activeOperationsRef.current.delete(operation.threadId);
          setActiveThreadIds((current) =>
            current.filter((item) => item !== operation.threadId),
          );
        }
      }
    },
    [
      createMessageId,
      cancelRunner,
      dispatchForThread,
      onRunRequested,
      onRunSettled,
      onRunStarted,
      onEventReceived,
      runReconciler,
      streamRunner,
      threadId,
    ],
  );

  const cancel = useCallback(async (): Promise<boolean> => {
    const operation = activeOperationsRef.current.get(threadId) ?? null;
    if (operation === null) {
      return false;
    }
    if (operation.cancelRequested) {
      return true;
    }
    operation.cancelRequested = true;

    if (operation.runId === null) {
      // 响应头尚未到达时没有可寻址 Run；断开连接会触发服务端同一取消状态机。
      dispatchForThread(operation.threadId, { type: "run/cancelled" });
      operation.controller.abort();
      return true;
    }

    dispatchForThread(operation.threadId, { type: "run/cancel-requested" });
    try {
      await cancelRunner({
        threadId: operation.threadId,
        runId: operation.runId,
      });
      // 不主动关闭 SSE；等待服务端 run_interrupted 作为唯一可信终态。
      return true;
    } catch (error) {
      const isLiveOperation =
        activeOperationsRef.current.get(operation.threadId)?.id ===
        operation.id;
      if (!isLiveOperation) {
        return false;
      }
      const failure = toClientFailure(error);
      dispatchForThread(operation.threadId, {
        type: "run/cancel-failed",
        error:
          failure === null
            ? {
                code: "cancel_failed",
                message: "停止请求失败，当前 Run 可能仍在继续",
                retryable: true,
              }
            : { ...failure, code: `cancel_${failure.code}` },
      });
      operation.cancelRequested = false;
      return false;
    }
  }, [cancelRunner, dispatchForThread, threadId]);

  const hydrateHistory = useCallback(
    (historyThreadId: string, timeline: readonly ChatTimelineItem[]): void => {
      // reducer 再次校验 Thread，旧查询即使迟到也不能覆盖已经切换的新页面。
      dispatchForThread(historyThreadId, {
        type: "thread/history-loaded",
        threadId: historyThreadId,
        timeline,
      });
    },
    [dispatchForThread],
  );

  return {
    state: renderedState,
    isActive: isActiveState(renderedState),
    activeThreadIds,
    hydrateHistory,
    submit,
    cancel,
  };
}
