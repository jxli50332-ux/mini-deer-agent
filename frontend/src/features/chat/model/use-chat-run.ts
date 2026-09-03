import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
} from "react";

import type { ChatTimelineItem } from "@/entities/message/model/types";
import type { PreparedTextAttachment } from "@/entities/attachment/model/text-attachments";
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
  type ChatRunFailure,
  type ChatRunState,
} from "@/features/chat/model/reducer";

export type ChatStreamRunner = (
  request: ChatStreamRequest,
) => AsyncIterable<ChatRunEvent>;
export type ChatRunCanceller = (request: ChatRunCancelRequest) => Promise<void>;

export interface UseChatRunOptions {
  readonly threadId: string;
  readonly streamRunner?: ChatStreamRunner;
  readonly cancelRunner?: ChatRunCanceller;
  readonly runReconciler?: ChatRunReconciler;
  readonly createMessageId?: () => string;
}

export interface UseChatRunResult {
  readonly state: ChatRunState;
  readonly isActive: boolean;
  readonly hydrateHistory: (
    threadId: string,
    timeline: readonly ChatTimelineItem[],
  ) => void;
  readonly submit: (
    message: string,
    attachments?: readonly PreparedTextAttachment[],
    submitOptions?: ChatSubmitOptions,
  ) => Promise<boolean>;
  readonly cancel: () => Promise<boolean>;
}

export interface ChatSubmitOptions {
  readonly humanInputResponse?: HumanInputResponse;
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
  const streamRunner = options.streamRunner ?? streamChatRun;
  const cancelRunner = options.cancelRunner ?? cancelChatRun;
  const runReconciler =
    options.runReconciler ?? reconcileChatRunAfterDisconnect;
  const createMessageId = options.createMessageId ?? defaultCreateMessageId;
  const [state, dispatch] = useReducer(
    chatRunReducer,
    threadId,
    createInitialChatRunState,
  );

  const activeOperationRef = useRef<ActiveOperation | null>(null);
  const nextOperationIdRef = useRef(1);
  const currentThreadIdRef = useRef(threadId);
  const previousThreadIdRef = useRef(threadId);

  useLayoutEffect(() => {
    // ref 只在提交阶段同步，避免 render 阶段读写可变外部状态。
    currentThreadIdRef.current = threadId;
    if (previousThreadIdRef.current === threadId) {
      return;
    }

    // 切换线程时先断开旧流，再清空旧状态；旧 promise 即使稍后恢复也不能派发事件。
    activeOperationRef.current?.controller.abort();
    activeOperationRef.current = null;
    previousThreadIdRef.current = threadId;
    dispatch({ type: "thread/reset", threadId });
  }, [threadId]);

  useEffect(
    () => () => {
      // 组件卸载后取消底层 fetch，并让异步循环通过 operation 身份检查停止派发。
      activeOperationRef.current?.controller.abort();
      activeOperationRef.current = null;
    },
    [],
  );

  const submit = useCallback(
    async (
      rawMessage: string,
      attachments: readonly PreparedTextAttachment[] = [],
      submitOptions: ChatSubmitOptions = {},
    ): Promise<boolean> => {
      if (activeOperationRef.current !== null) {
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
      activeOperationRef.current = operation;

      dispatch({
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
        },
      });

      const isCurrentOperation = () =>
        activeOperationRef.current?.id === operation.id &&
        currentThreadIdRef.current === operation.threadId;

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
          signal: operation.controller.signal,
          onRunId: (runId) => {
            // 响应头先建立取消寻址；旧 operation 的回调不能覆盖当前 Run。
            if (isCurrentOperation()) {
              operation.runId = runId;
            }
          },
        })) {
          if (!isCurrentOperation()) {
            return false;
          }
          operation.runId ??= event.runId;
          dispatch({ type: "run/event-received", event });
        }
        return isCurrentOperation();
      } catch (error) {
        if (!isCurrentOperation()) {
          return false;
        }

        const failure = toClientFailure(error);
        if (operation.controller.signal.aborted || failure === null) {
          dispatch({ type: "run/cancelled" });
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
                dispatch({ type: "run/status-reconciled", run });
                return true;
              }
            } catch {
              // 状态查询失败不能覆盖最初的连接错误，更不能伪装已经恢复。
              if (!isCurrentOperation()) {
                return false;
              }
            }
          }
          dispatch({ type: "run/client-failed", error: failure });
        }
        return false;
      } finally {
        if (activeOperationRef.current?.id === operation.id) {
          activeOperationRef.current = null;
        }
      }
    },
    [createMessageId, runReconciler, streamRunner, threadId],
  );

  const cancel = useCallback(async (): Promise<boolean> => {
    const operation = activeOperationRef.current;
    if (operation === null) {
      return false;
    }
    if (operation.cancelRequested) {
      return true;
    }
    operation.cancelRequested = true;

    if (operation.runId === null) {
      // 响应头尚未到达时没有可寻址 Run；断开连接会触发服务端同一取消状态机。
      dispatch({ type: "run/cancelled" });
      operation.controller.abort();
      return true;
    }

    dispatch({ type: "run/cancel-requested" });
    try {
      await cancelRunner({
        threadId: operation.threadId,
        runId: operation.runId,
      });
      // 不主动关闭 SSE；等待服务端 run_interrupted 作为唯一可信终态。
      return true;
    } catch (error) {
      const isCurrentOperation =
        activeOperationRef.current?.id === operation.id &&
        currentThreadIdRef.current === operation.threadId;
      if (!isCurrentOperation) {
        return false;
      }
      const failure = toClientFailure(error);
      dispatch({
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
  }, [cancelRunner]);

  const hydrateHistory = useCallback(
    (historyThreadId: string, timeline: readonly ChatTimelineItem[]): void => {
      // reducer 再次校验 Thread，旧查询即使迟到也不能覆盖已经切换的新页面。
      dispatch({
        type: "thread/history-loaded",
        threadId: historyThreadId,
        timeline,
      });
    },
    [],
  );

  return {
    state,
    isActive: isActiveState(state),
    hydrateHistory,
    submit,
    cancel,
  };
}
