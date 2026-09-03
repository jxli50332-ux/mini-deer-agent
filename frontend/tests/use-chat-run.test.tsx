import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ChatStreamClientError,
  type ChatRunDetail,
} from "@/features/chat/api/chat-stream";
import type { ChatRunEvent } from "@/features/chat/model/events";
import {
  useChatRun,
  type ChatStreamRunner,
} from "@/features/chat/model/use-chat-run";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const THREAD_ID = "22222222-2222-4222-8222-222222222222";
const OTHER_THREAD_ID = "44444444-4444-4444-8444-444444444444";

function baseEvent(sequence: number) {
  return {
    eventId: `${RUN_ID}:${sequence}`,
    version: "1" as const,
    runId: RUN_ID,
    threadId: THREAD_ID,
    sequence,
  };
}

function started(): ChatRunEvent {
  return {
    ...baseEvent(1),
    event: "run_started",
    messageId: null,
    payload: { createdAt: "2026-08-25T15:00:00+00:00" },
  };
}

function aiDelta(sequence: number, text: string): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "ai_delta",
    messageId: "assistant-1",
    payload: { text },
  };
}

function completed(sequence: number): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "run_completed",
    messageId: null,
    payload: { finishReason: "stop" },
  };
}

function interrupted(sequence: number): ChatRunEvent {
  return {
    ...baseEvent(sequence),
    event: "run_interrupted",
    messageId: null,
    payload: { reason: "user_cancelled" },
  };
}

function persistedRun(
  status: ChatRunDetail["status"],
  overrides: Partial<ChatRunDetail> = {},
): ChatRunDetail {
  return {
    runId: RUN_ID,
    threadId: THREAD_ID,
    status,
    userMessageId: "user-local-1",
    createdAt: "2026-08-28T00:00:00+00:00",
    startedAt: "2026-08-28T00:00:01+00:00",
    finishedAt: status === "running" ? null : "2026-08-28T00:00:02+00:00",
    finishReason: status === "completed" ? "stop" : null,
    errorCode: status === "failed" ? "agent_execution_failed" : null,
    ...overrides,
  };
}

interface Deferred {
  readonly promise: Promise<void>;
  readonly resolve: () => void;
}

function deferred(): Deferred {
  let resolvePromise: (() => void) | undefined;
  const promise = new Promise<void>((resolve) => {
    resolvePromise = resolve;
  });
  return {
    promise,
    resolve: () => resolvePromise?.(),
  };
}

describe("useChatRun", () => {
  it("组合 runner 与 reducer，并把每条事件合并为最终时间线", async () => {
    let capturedMessage = "";
    let capturedSignal: AbortSignal | undefined;
    const runner: ChatStreamRunner = async function* (request) {
      // 保留真实异步边界，模拟 fetch 建立连接后的事件调度。
      await Promise.resolve();
      capturedMessage = request.message;
      capturedSignal = request.signal;
      yield started();
      yield aiDelta(2, "北");
      yield aiDelta(3, "京天气");
      yield completed(4);
    };
    const { result } = renderHook(() =>
      useChatRun({
        threadId: THREAD_ID,
        streamRunner: runner,
        createMessageId: () => "user-local-1",
      }),
    );

    let submitted = false;
    await act(async () => {
      submitted = await result.current.submit("  查询北京天气  ");
    });

    expect(submitted).toBe(true);
    expect(capturedMessage).toBe("查询北京天气");
    expect(capturedSignal).toBeInstanceOf(AbortSignal);
    expect(result.current.state.phase).toBe("completed");
    expect(result.current.state.timeline).toEqual([
      {
        kind: "message",
        id: "user-local-1",
        role: "user",
        content: "查询北京天气",
      },
      {
        kind: "message",
        id: "assistant-1",
        role: "assistant",
        content: "北京天气",
      },
    ]);
  });

  it("结构化回答同时进入请求元数据和隐藏的 optimistic 时间线", async () => {
    let capturedResponse: unknown;
    const response = {
      version: 1,
      kind: "human_input_response",
      request_id: "clarification:call-1",
      response_kind: "text",
      value: "Markdown",
    } as const;
    const runner: ChatStreamRunner = async function* (request) {
      await Promise.resolve();
      capturedResponse = request.humanInputResponse;
      yield started();
      yield completed(2);
    };
    const { result } = renderHook(() =>
      useChatRun({
        threadId: THREAD_ID,
        streamRunner: runner,
        createMessageId: () => "user-human-input-1",
      }),
    );

    await act(async () => {
      await result.current.submit("我选择 Markdown", [], {
        humanInputResponse: response,
      });
    });

    expect(capturedResponse).toEqual(response);
    expect(result.current.state.timeline[0]).toMatchObject({
      id: "user-human-input-1",
      hiddenFromUi: true,
      humanInputResponse: response,
    });
  });

  it("用 active operation guard 阻止同一时刻重复提交", async () => {
    const gate = deferred();
    const runner: ChatStreamRunner = async function* () {
      yield started();
      await gate.promise;
      yield completed(2);
    };
    const { result } = renderHook(() =>
      useChatRun({
        threadId: THREAD_ID,
        streamRunner: runner,
        createMessageId: () => "user-local-1",
      }),
    );

    let firstRequest: Promise<boolean> | undefined;
    act(() => {
      firstRequest = result.current.submit("第一条消息");
    });
    await waitFor(() => expect(result.current.state.phase).toBe("streaming"));

    let secondSubmitted = true;
    await act(async () => {
      secondSubmitted = await result.current.submit("重复消息");
    });
    expect(secondSubmitted).toBe(false);
    expect(result.current.state.timeline).toHaveLength(1);

    await act(async () => {
      gate.resolve();
      await firstRequest;
    });
    expect(result.current.state.phase).toBe("completed");
  });

  it("cancel 会请求服务端停止并等待 run_interrupted 可信终态", async () => {
    let capturedSignal: AbortSignal | undefined;
    const cancelRequested = deferred();
    const cancelCalls: Array<{ threadId: string; runId: string }> = [];
    const runner: ChatStreamRunner = async function* (request) {
      capturedSignal = request.signal;
      yield started();
      await cancelRequested.promise;
      yield interrupted(2);
    };
    const { result } = renderHook(() =>
      useChatRun({
        threadId: THREAD_ID,
        streamRunner: runner,
        cancelRunner: (request) => {
          cancelCalls.push(request);
          cancelRequested.resolve();
          return Promise.resolve();
        },
      }),
    );

    let request: Promise<boolean> | undefined;
    act(() => {
      request = result.current.submit("需要取消的消息");
    });
    await waitFor(() => expect(result.current.state.phase).toBe("streaming"));

    await act(async () => {
      expect(await result.current.cancel()).toBe(true);
    });
    await act(async () => {
      expect(await request).toBe(true);
    });
    expect(cancelCalls).toEqual([{ threadId: THREAD_ID, runId: RUN_ID }]);
    expect(result.current.state.phase).toBe("cancelled");
    expect(result.current.state.finishReason).toBe("user_cancelled");
    expect(capturedSignal?.aborted).toBe(false);
  });

  it("服务端取消请求失败时保持原 SSE，并允许 Run 自然完成", async () => {
    const finishGate = deferred();
    const runner: ChatStreamRunner = async function* () {
      yield started();
      await finishGate.promise;
      yield completed(2);
    };
    const { result } = renderHook(() =>
      useChatRun({
        threadId: THREAD_ID,
        streamRunner: runner,
        cancelRunner: () =>
          Promise.reject(
            new ChatStreamClientError("network_error", "无法连接取消接口", {
              retryable: true,
            }),
          ),
      }),
    );

    let request: Promise<boolean> | undefined;
    act(() => {
      request = result.current.submit("取消失败测试");
    });
    await waitFor(() => expect(result.current.state.phase).toBe("streaming"));

    await act(async () => {
      expect(await result.current.cancel()).toBe(false);
    });
    expect(result.current.state).toMatchObject({
      phase: "streaming",
      error: { code: "cancel_network_error", retryable: true },
    });

    await act(async () => {
      finishGate.resolve();
      expect(await request).toBe(true);
    });
    expect(result.current.state).toMatchObject({
      phase: "completed",
      error: null,
    });
  });

  it("把已归一化 client 错误派发为 client failure", async () => {
    const runner: ChatStreamRunner = async function* () {
      await Promise.resolve();
      throw new ChatStreamClientError(
        "network_error",
        "无法连接 Mini Deer Agent 后端",
        { retryable: true },
      );
    };
    const { result } = renderHook(() =>
      useChatRun({ threadId: THREAD_ID, streamRunner: runner }),
    );

    await act(async () => {
      expect(await result.current.submit("触发网络错误")).toBe(false);
    });

    expect(result.current.state).toMatchObject({
      phase: "failed",
      error: {
        source: "client",
        code: "network_error",
        retryable: true,
      },
    });
  });

  it("SSE 断线后自动查询 Run，并用持久化完成状态收敛页面", async () => {
    const runner: ChatStreamRunner = async function* () {
      await Promise.resolve();
      yield started();
      yield aiDelta(2, "已收到的部分回答");
      throw new ChatStreamClientError(
        "stream_inactive",
        "长时间未收到 Agent 心跳或事件，连接可能已经中断",
        { retryable: true },
      );
    };
    const reconciledRequests: Array<{
      threadId: string;
      runId: string;
      signal?: AbortSignal;
    }> = [];
    const { result } = renderHook(() =>
      useChatRun({
        threadId: THREAD_ID,
        streamRunner: runner,
        runReconciler: (request) => {
          reconciledRequests.push(request);
          return Promise.resolve(persistedRun("completed"));
        },
        createMessageId: () => "user-local-1",
      }),
    );

    await act(async () => {
      expect(await result.current.submit("断线状态核对")).toBe(true);
    });

    expect(reconciledRequests).toHaveLength(1);
    expect(reconciledRequests[0]).toMatchObject({
      threadId: THREAD_ID,
      runId: RUN_ID,
    });
    expect(reconciledRequests[0]?.signal).toBeInstanceOf(AbortSignal);
    expect(result.current.state).toMatchObject({
      phase: "completed",
      runId: RUN_ID,
      finishReason: "stop",
      error: null,
    });
  });

  it("Run 在核对预算后仍活动时保留原始连接错误", async () => {
    const runner: ChatStreamRunner = async function* () {
      await Promise.resolve();
      yield started();
      throw new ChatStreamClientError(
        "network_error",
        "无法连接 Mini Deer Agent 后端",
        { retryable: true },
      );
    };
    const { result } = renderHook(() =>
      useChatRun({
        threadId: THREAD_ID,
        streamRunner: runner,
        runReconciler: () => Promise.resolve(persistedRun("running")),
      }),
    );

    await act(async () => {
      expect(await result.current.submit("仍在执行")).toBe(false);
    });

    expect(result.current.state).toMatchObject({
      phase: "failed",
      error: {
        source: "client",
        code: "network_error",
        retryable: true,
      },
    });
  });

  it("Run 状态查询失败时不覆盖最初的 SSE 连接错误", async () => {
    const runner: ChatStreamRunner = async function* () {
      await Promise.resolve();
      yield started();
      throw new ChatStreamClientError(
        "incomplete_stream",
        "Agent 事件流在终止事件之前结束",
        { retryable: true },
      );
    };
    const { result } = renderHook(() =>
      useChatRun({
        threadId: THREAD_ID,
        streamRunner: runner,
        runReconciler: () => Promise.reject(new Error("查询服务不可用")),
      }),
    );

    await act(async () => {
      expect(await result.current.submit("核对失败")).toBe(false);
    });

    expect(result.current.state).toMatchObject({
      phase: "failed",
      error: {
        source: "client",
        code: "incomplete_stream",
        retryable: true,
      },
    });
  });

  it.each([
    ["failed" as const, "failed", "agent_execution_failed"],
    ["interrupted" as const, "cancelled", null],
  ])(
    "断线后把持久化 %s 状态收敛为页面 %s",
    async (status, expectedPhase, expectedErrorCode) => {
      const runner: ChatStreamRunner = async function* () {
        await Promise.resolve();
        yield started();
        throw new ChatStreamClientError(
          "network_error",
          "无法连接 Mini Deer Agent 后端",
          { retryable: true },
        );
      };
      const { result } = renderHook(() =>
        useChatRun({
          threadId: THREAD_ID,
          streamRunner: runner,
          runReconciler: () =>
            Promise.resolve(
              persistedRun(status, {
                finishReason:
                  status === "interrupted" ? "client_disconnected" : null,
              }),
            ),
        }),
      );

      await act(async () => {
        expect(await result.current.submit("核对服务端终态")).toBe(true);
      });

      expect(result.current.state.phase).toBe(expectedPhase);
      if (expectedErrorCode === null) {
        expect(result.current.state).toMatchObject({
          finishReason: "client_disconnected",
          error: null,
        });
      } else {
        expect(result.current.state.error).toMatchObject({
          source: "server",
          code: expectedErrorCode,
        });
      }
    },
  );

  it("协议错误不查询 Run，避免把事件损坏伪装成连接恢复", async () => {
    const runner: ChatStreamRunner = async function* () {
      await Promise.resolve();
      yield started();
      throw new ChatStreamClientError(
        "stream_protocol_error",
        "服务端返回了无法识别的 Agent 事件",
        { retryable: false },
      );
    };
    let reconciliationCount = 0;
    const { result } = renderHook(() =>
      useChatRun({
        threadId: THREAD_ID,
        streamRunner: runner,
        runReconciler: () => {
          reconciliationCount += 1;
          return Promise.resolve(persistedRun("completed"));
        },
      }),
    );

    await act(async () => {
      expect(await result.current.submit("协议错误")).toBe(false);
    });

    expect(reconciliationCount).toBe(0);
    expect(result.current.state).toMatchObject({
      phase: "failed",
      error: { code: "stream_protocol_error", retryable: false },
    });
  });

  it("线程切换会中止旧操作、重置状态并忽略迟到事件", async () => {
    const gate = deferred();
    let capturedSignal: AbortSignal | undefined;
    const runner: ChatStreamRunner = async function* (request) {
      capturedSignal = request.signal;
      yield started();
      await gate.promise;
      yield aiDelta(2, "不应进入新线程");
      yield completed(3);
    };
    const { result, rerender } = renderHook(
      ({ threadId }: { readonly threadId: string }) =>
        useChatRun({ threadId, streamRunner: runner }),
      { initialProps: { threadId: THREAD_ID } },
    );

    let request: Promise<boolean> | undefined;
    act(() => {
      request = result.current.submit("旧线程消息");
    });
    await waitFor(() => expect(result.current.state.phase).toBe("streaming"));

    rerender({ threadId: OTHER_THREAD_ID });
    await waitFor(() =>
      expect(result.current.state).toMatchObject({
        phase: "idle",
        threadId: OTHER_THREAD_ID,
        timeline: [],
      }),
    );
    expect(capturedSignal?.aborted).toBe(true);

    await act(async () => {
      gate.resolve();
      expect(await request).toBe(false);
    });
    expect(result.current.state.timeline).toEqual([]);
  });

  it("组件卸载会中止活动请求，旧 promise 不再派发状态", async () => {
    let capturedSignal: AbortSignal | undefined;
    const runner: ChatStreamRunner = async function* (request) {
      capturedSignal = request.signal;
      yield started();
      await new Promise<void>((_resolve, reject) => {
        request.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true },
        );
      });
    };
    const { result, unmount } = renderHook(() =>
      useChatRun({ threadId: THREAD_ID, streamRunner: runner }),
    );

    let request: Promise<boolean> | undefined;
    act(() => {
      request = result.current.submit("卸载测试");
    });
    await waitFor(() => expect(result.current.state.phase).toBe("streaming"));

    unmount();
    expect(capturedSignal?.aborted).toBe(true);
    expect(await request).toBe(false);
  });
});
