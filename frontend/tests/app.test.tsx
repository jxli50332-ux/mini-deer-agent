import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/app/App";
import type { CurrentThreadRepository } from "@/entities/thread/model/current-thread-repository";
import {
  ChatStreamClientError,
  type ChatRunDetail,
} from "@/features/chat/api/chat-stream";
import type { ChatRunEvent } from "@/features/chat/model/events";
import type { ChatStreamRunner } from "@/features/chat/model/use-chat-run";
import { ChatPage } from "@/features/chat/ui/ChatPage";
import type { ThreadGoal } from "@/features/goals/api/thread-goal";
import type { ThreadHistoryPageLoader } from "@/features/threads/api/thread-history";
import type {
  ThreadDeleter,
  ThreadListLoader,
  ThreadTitleUpdater,
} from "@/features/threads/api/thread-list";
import type { ThreadRunsLoader } from "@/features/threads/api/thread-runs";

const RUN_ID = "11111111-1111-4111-8111-111111111111";
const THREAD_ID = "22222222-2222-4222-8222-222222222222";
const NEXT_RUN_ID = "33333333-3333-4333-8333-333333333333";
const NEXT_THREAD_ID = "44444444-4444-4444-8444-444444444444";
const OTHER_THREAD_ID = "55555555-5555-4555-8555-555555555555";
const MESSAGE_ID = "66666666-6666-4666-8666-666666666666";

function baseEvent(sequence: number, runId = RUN_ID, threadId = THREAD_ID) {
  return {
    eventId: `${runId}:${sequence}`,
    version: "1" as const,
    runId,
    threadId,
    sequence,
  };
}

function fixedThreadRepository(): CurrentThreadRepository {
  // 页面测试固定线程身份，避免依赖同一测试环境中的 localStorage 状态。
  return {
    getOrCreateCurrentThreadId: () => THREAD_ID,
    createNewCurrentThreadId: () => NEXT_THREAD_ID,
    selectCurrentThreadId: (threadId) => threadId,
  };
}

function emptyHistoryResponse(threadId: string): Response {
  return Response.json({
    version: "1",
    thread_id: threadId,
    thread_exists: false,
    items: [],
    has_more: false,
    next_before_sequence: null,
  });
}

function persistedRun(
  userMessageId: string,
  overrides: Partial<ChatRunDetail> = {},
): ChatRunDetail {
  return {
    runId: RUN_ID,
    threadId: THREAD_ID,
    status: "completed",
    userMessageId,
    createdAt: "2026-08-29T08:00:00Z",
    startedAt: "2026-08-29T08:00:01.200Z",
    finishedAt: "2026-08-29T08:00:04.900Z",
    finishReason: "stop",
    errorCode: null,
    ...overrides,
  };
}

describe("Mini Deer Agent 实时聊天页", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // 页面挂载会立即查询当前 Thread；默认返回尚未创建的空 Thread。
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const requestUrl =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        if (requestUrl.startsWith("/api/v1/projects")) {
          return Promise.resolve(
            Response.json({ items: [], next_offset: null }),
          );
        }
        if (requestUrl.startsWith("/api/v1/projects")) {
          return Promise.resolve(
            Response.json({ items: [], next_offset: null }),
          );
        }
        const match = requestUrl.match(/\/threads\/([^/]+)\/messages/);
        if (requestUrl.startsWith("/api/v1/threads?")) {
          return Promise.resolve(Response.json([]));
        }
        if (requestUrl.startsWith("/api/v1/projects")) {
          return Promise.resolve(
            Response.json({ items: [], next_offset: null }),
          );
        }
        if (match?.[1] === undefined) {
          return Promise.reject(new Error("测试只允许 Thread 查询"));
        }
        return Promise.resolve(emptyHistoryResponse(match[1]));
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("初始展示空对话、真实输入框和就绪状态", async () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Mini Deer 对话" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("log", { name: "对话消息" })).toBeInTheDocument();
    expect(await screen.findByLabelText("开始新对话")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "就绪" })).toBeInTheDocument();

    const messageInput = screen.getByRole("textbox", {
      name: "向 Agent 提问",
    });
    const sendButton = screen.getByRole("button", { name: "发送" });

    expect(messageInput).toBeEnabled();
    expect(sendButton).toBeDisabled();
    expect(
      screen.getByText("模型密钥不会进入浏览器", { exact: false }),
    ).toBeInTheDocument();
  });

  it("把输入、工具活动和模型增量连接到真实页面组件", async () => {
    const runner = vi.fn<ChatStreamRunner>(async function* (request) {
      await Promise.resolve();
      yield {
        ...baseEvent(1),
        event: "run_started",
        messageId: null,
        payload: { createdAt: "2026-08-25T15:00:00+00:00" },
      } satisfies ChatRunEvent;
      yield {
        ...baseEvent(2),
        event: "tool_call_delta",
        messageId: "assistant-tool-1",
        payload: {
          toolCallId: "call-weather-1",
          name: "get_weather",
          argumentsDelta: '{"city":',
          index: 0,
        },
      } satisfies ChatRunEvent;
      yield {
        ...baseEvent(3),
        event: "tool_call_delta",
        messageId: "assistant-tool-1",
        payload: {
          toolCallId: "call-weather-1",
          name: null,
          argumentsDelta: '"北京"}',
          index: 0,
        },
      } satisfies ChatRunEvent;
      yield {
        ...baseEvent(4),
        event: "tool_result",
        messageId: "tool-message-1",
        payload: {
          toolCallId: "call-weather-1",
          name: "get_weather",
          content: "北京 24°C",
        },
      } satisfies ChatRunEvent;
      yield {
        ...baseEvent(5),
        event: "ai_delta",
        messageId: "assistant-final-1",
        payload: { text: "北京当前" },
      } satisfies ChatRunEvent;
      yield {
        ...baseEvent(6),
        event: "ai_delta",
        messageId: "assistant-final-1",
        payload: { text: "天气为 24°C。" },
      } satisfies ChatRunEvent;
      yield {
        ...baseEvent(7),
        event: "run_completed",
        messageId: null,
        payload: { finishReason: "stop" },
      } satisfies ChatRunEvent;
      expect(request.threadId).toBe(THREAD_ID);
      expect(request.message).toBe("请查询北京天气");
    });

    render(
      <ChatPage
        streamRunner={runner}
        currentThreadRepository={fixedThreadRepository()}
        createMessageId={() => "user-local-1"}
      />,
    );
    const textbox = screen.getByRole("textbox", { name: "向 Agent 提问" });
    fireEvent.change(textbox, { target: { value: "请查询北京天气" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "已完成" }),
      ).toBeInTheDocument(),
    );
    expect(runner).toHaveBeenCalledOnce();
    expect(screen.getByText("请查询北京天气")).toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: "工具 get_weather 已完成" }),
    ).toBeInTheDocument();
    const toolStep = screen.getByRole("status", {
      name: "工具 get_weather 已完成",
    });
    expect(within(toolStep).getByText("查询 北京 天气")).toBeInTheDocument();
    expect(toolStep.querySelector("details")).toBeNull();
    expect(screen.queryByText(/"city": "北京"/)).not.toBeInTheDocument();
    expect(screen.queryByText("北京 24°C")).not.toBeInTheDocument();
    expect(screen.getByText("北京当前天气为 24°C。")).toBeInTheDocument();
    expect(textbox).toBeEnabled();
  });

  it("运行中停止 Goal 时同时停止续跑状态和当前 Run", async () => {
    let releaseRun: (() => void) | undefined;
    const runGate = new Promise<void>((resolve) => {
      releaseRun = resolve;
    });
    const runner = vi.fn<ChatStreamRunner>(async function* () {
      yield {
        ...baseEvent(1),
        event: "run_started",
        messageId: null,
        payload: { createdAt: "2026-09-08T02:00:00Z" },
      } satisfies ChatRunEvent;
      await runGate;
      yield {
        ...baseEvent(2),
        event: "run_interrupted",
        messageId: null,
        payload: { reason: "user_cancelled" },
      } satisfies ChatRunEvent;
    });
    const activeGoal: ThreadGoal = {
      version: 1,
      revision: "77777777-7777-4777-8777-777777777777",
      objective: "完成当前修复",
      continuationCount: 1,
      maxContinuations: 6,
      noProgressCount: 0,
      lastEvaluation: null,
      status: "active",
      stopReason: null,
      createdAt: "2026-09-08T01:00:00Z",
      updatedAt: "2026-09-08T01:00:00Z",
    };
    let currentGoal = activeGoal;
    const goalStopper = vi.fn(() => {
      currentGoal = {
        ...activeGoal,
        revision: "88888888-8888-4888-8888-888888888888",
        status: "stopped" as const,
        stopReason: "user_stopped",
      };
      // 真实 Goal stop API 会在响应前收敛服务端 Run。
      releaseRun?.();
      return Promise.resolve(currentGoal);
    });
    const cancelRunner = vi.fn(() => {
      releaseRun?.();
      return Promise.resolve();
    });
    render(
      <ChatPage
        streamRunner={runner}
        cancelRunner={cancelRunner}
        currentThreadRepository={fixedThreadRepository()}
        createMessageId={() => MESSAGE_ID}
        goalLoader={() => Promise.resolve(currentGoal)}
        goalStopper={goalStopper}
      />,
    );

    expect(await screen.findByText("完成当前修复")).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "向 Agent 提问" }), {
      target: { value: "开始执行" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await screen.findByRole("status", { name: "正在生成" });
    fireEvent.click(screen.getByRole("button", { name: "停止执行与续跑" }));

    await waitFor(() => {
      expect(goalStopper).toHaveBeenCalledExactlyOnceWith({
        threadId: THREAD_ID,
        revision: activeGoal.revision,
      });
      expect(cancelRunner).not.toHaveBeenCalled();
    });
    expect(await screen.findByText("用户已停止")).toBeVisible();
  });

  it("Run 结束后用服务端时间定格当前轮次耗时", async () => {
    let completed = false;
    const runner: ChatStreamRunner = async function* () {
      await Promise.resolve();
      yield {
        ...baseEvent(1),
        event: "run_started",
        messageId: null,
        payload: { createdAt: "2026-08-29T08:00:01.200Z" },
      } satisfies ChatRunEvent;
      yield {
        ...baseEvent(2),
        event: "ai_delta",
        messageId: "assistant-duration-1",
        payload: { text: "计时回答" },
      } satisfies ChatRunEvent;
      completed = true;
      yield {
        ...baseEvent(3),
        event: "run_completed",
        messageId: null,
        payload: { finishReason: "stop" },
      } satisfies ChatRunEvent;
    };
    const threadRunsLoader = vi.fn<ThreadRunsLoader>(() =>
      Promise.resolve(completed ? [persistedRun(MESSAGE_ID)] : []),
    );

    render(
      <ChatPage
        streamRunner={runner}
        currentThreadRepository={fixedThreadRepository()}
        createMessageId={() => MESSAGE_ID}
        threadRunsLoader={threadRunsLoader}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "向 Agent 提问" }), {
      target: { value: "测试终态耗时" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    expect(
      await screen.findByLabelText("执行完成，用时 3 秒"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Agent 正在执行")).not.toBeInTheDocument();
    expect(threadRunsLoader).toHaveBeenCalledTimes(2);
  });

  it("在页面展示可重试的 SSE 静默超时，并恢复输入能力", async () => {
    const runner: ChatStreamRunner = async function* () {
      await Promise.resolve();
      throw new ChatStreamClientError(
        "stream_inactive",
        "长时间未收到 Agent 心跳或事件，连接可能已经中断",
        { retryable: true },
      );
    };
    render(
      <ChatPage
        streamRunner={runner}
        currentThreadRepository={fixedThreadRepository()}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "向 Agent 提问" }), {
      target: { value: "测试错误" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "长时间未收到 Agent 心跳或事件，连接可能已经中断",
    );
    expect(alert).toHaveTextContent("可以稍后重新发送");
    expect(
      screen.getByRole("textbox", { name: "向 Agent 提问" }),
    ).toBeEnabled();
  });

  it("默认页面链路在 SSE 缺少终止帧后查询 Run 并收敛为完成", async () => {
    const userMessageId = "66666666-6666-4666-8666-666666666666";
    const fetcher = vi.fn(
      (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const requestUrl =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        if (requestUrl.startsWith("/api/v1/projects")) {
          return Promise.resolve(
            Response.json({ items: [], next_offset: null }),
          );
        }
        if (requestUrl.startsWith("/api/v1/threads?")) {
          return Promise.resolve(Response.json([]));
        }
        if (requestUrl.includes(`/threads/${THREAD_ID}/messages`)) {
          return Promise.resolve(emptyHistoryResponse(THREAD_ID));
        }
        if (requestUrl.endsWith("/runs/stream") && init?.method === "POST") {
          const body =
            `id: ${RUN_ID}:1\nevent: run_started\ndata: ${JSON.stringify({
              version: "1",
              run_id: RUN_ID,
              thread_id: THREAD_ID,
              sequence: 1,
              message_id: null,
              payload: { created_at: "2026-08-28T00:00:00+00:00" },
            })}\n\n` +
            `id: ${RUN_ID}:2\nevent: ai_delta\ndata: ${JSON.stringify({
              version: "1",
              run_id: RUN_ID,
              thread_id: THREAD_ID,
              sequence: 2,
              message_id: "assistant-recovered-1",
              payload: { text: "已持久化回答" },
            })}\n\n`;
          return Promise.resolve(
            new Response(body, {
              headers: {
                "Content-Type": "text/event-stream",
                "X-Run-ID": RUN_ID,
              },
            }),
          );
        }
        if (requestUrl.endsWith(`/runs/${RUN_ID}`)) {
          return Promise.resolve(
            Response.json({
              run_id: RUN_ID,
              thread_id: THREAD_ID,
              status: "completed",
              user_message_id: userMessageId,
              created_at: "2026-08-28T00:00:00+00:00",
              started_at: "2026-08-28T00:00:00+00:00",
              finished_at: "2026-08-28T00:00:01+00:00",
              finish_reason: "stop",
              error_code: null,
            }),
          );
        }
        return Promise.reject(new Error(`未处理的测试请求：${requestUrl}`));
      },
    );
    vi.stubGlobal("fetch", fetcher);

    render(
      <ChatPage
        currentThreadRepository={fixedThreadRepository()}
        createMessageId={() => userMessageId}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "向 Agent 提问" }), {
      target: { value: "触发断线核对" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() =>
      expect(
        screen.getByRole("status", { name: "已完成" }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("已持久化回答")).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([input, init]) => {
        const requestUrl =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.href
              : input.url;
        return requestUrl.endsWith(`/runs/${RUN_ID}`) && init?.method === "GET";
      }),
    ).toBe(true);
  });

  it("当前 Run 继续后台执行时创建新 Thread 并并发发送", async () => {
    let releaseFirstRun: () => void = () => undefined;
    const firstRunGate = new Promise<void>((resolve) => {
      releaseFirstRun = resolve;
    });
    const requestedThreadIds: string[] = [];
    const requestedSignals: AbortSignal[] = [];
    let runNumber = 0;
    const runner = vi.fn<ChatStreamRunner>(async function* (request) {
      runNumber += 1;
      const currentRunNumber = runNumber;
      const runId = currentRunNumber === 1 ? RUN_ID : NEXT_RUN_ID;
      requestedThreadIds.push(request.threadId);
      if (request.signal !== undefined) requestedSignals.push(request.signal);

      yield {
        ...baseEvent(1, runId, request.threadId),
        event: "run_started",
        messageId: null,
        payload: { createdAt: "2026-08-25T15:00:00+00:00" },
      } satisfies ChatRunEvent;
      if (currentRunNumber === 1) {
        // 保持第一轮运行中，验证切换后旧 SSE 仍在后台消费。
        await firstRunGate;
      }
      yield {
        ...baseEvent(2, runId, request.threadId),
        event: "ai_delta",
        messageId: `${runId}:assistant`,
        payload: { text: `第 ${currentRunNumber} 轮回答` },
      } satisfies ChatRunEvent;
      yield {
        ...baseEvent(3, runId, request.threadId),
        event: "run_completed",
        messageId: null,
        payload: { finishReason: "stop" },
      } satisfies ChatRunEvent;
    });
    const createNewCurrentThreadId = vi.fn(() => NEXT_THREAD_ID);
    const repository: CurrentThreadRepository = {
      getOrCreateCurrentThreadId: () => THREAD_ID,
      createNewCurrentThreadId,
      selectCurrentThreadId: (threadId) => threadId,
    };
    const threadListLoader: ThreadListLoader = () =>
      Promise.resolve([
        {
          threadId: OTHER_THREAD_ID,
          title: "其他会话",
          status: "idle",
          projectId: null,
          createdAt: "2026-08-26T08:00:00+00:00",
          updatedAt: "2026-08-26T09:00:00+00:00",
        },
      ]);

    render(
      <ChatPage
        streamRunner={runner}
        currentThreadRepository={repository}
        createMessageId={() => globalThis.crypto.randomUUID()}
        threadListLoader={threadListLoader}
      />,
    );

    const textbox = screen.getByRole("textbox", { name: "向 Agent 提问" });
    const newThreadButton = screen.getByRole("button", { name: "新会话" });
    fireEvent.change(textbox, { target: { value: "第一轮问题" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await screen.findByRole("status", { name: "正在生成" });
    expect(newThreadButton).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "切换到会话 其他会话" }),
    ).toBeEnabled();

    fireEvent.click(newThreadButton);

    await waitFor(() =>
      expect(
        screen.getByTitle(`thread_id: ${NEXT_THREAD_ID}`),
      ).toBeInTheDocument(),
    );
    expect(createNewCurrentThreadId).toHaveBeenCalledOnce();
    expect(await screen.findByLabelText("开始新对话")).toBeInTheDocument();
    expect(screen.queryByText("第一轮问题")).not.toBeInTheDocument();

    const nextThreadTextbox = screen.getByRole("textbox", {
      name: "向 Agent 提问",
    });
    fireEvent.change(nextThreadTextbox, { target: { value: "第二轮问题" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(runner).toHaveBeenCalledTimes(2));
    await screen.findByText("第 2 轮回答");

    expect(requestedThreadIds).toEqual([THREAD_ID, NEXT_THREAD_ID]);
    expect(requestedSignals[0]?.aborted).toBe(false);
    releaseFirstRun();
    await waitFor(() => expect(requestedSignals[0]?.aborted).toBe(false));
  });

  it("从真实最近列表切换 Thread，并只展示目标历史", async () => {
    const selectCurrentThreadId = vi.fn((threadId: string) => threadId);
    const repository: CurrentThreadRepository = {
      getOrCreateCurrentThreadId: () => THREAD_ID,
      createNewCurrentThreadId: () => OTHER_THREAD_ID,
      selectCurrentThreadId,
    };
    const threadListLoader: ThreadListLoader = () =>
      Promise.resolve([
        {
          threadId: NEXT_THREAD_ID,
          title: "目标会话",
          status: "idle",
          projectId: null,
          createdAt: "2026-08-26T09:00:00+00:00",
          updatedAt: "2026-08-26T10:00:00+00:00",
        },
        {
          threadId: THREAD_ID,
          title: "旧会话",
          status: "idle",
          projectId: null,
          createdAt: "2026-08-26T08:00:00+00:00",
          updatedAt: "2026-08-26T09:00:00+00:00",
        },
      ]);
    const historyPageLoader = vi.fn<ThreadHistoryPageLoader>((request) =>
      Promise.resolve({
        version: "1",
        threadId: request.threadId,
        threadExists: true,
        items: [
          {
            kind: "message",
            id: `${request.threadId}:message`,
            role: "user",
            content:
              request.threadId === THREAD_ID ? "旧会话消息" : "目标会话消息",
            runId: RUN_ID,
            threadSequence: 1,
            createdAt: "2026-08-26T08:00:00+00:00",
          },
        ],
        hasMore: false,
        nextBeforeSequence: null,
      }),
    );

    render(
      <ChatPage
        currentThreadRepository={repository}
        historyPageLoader={historyPageLoader}
        threadListLoader={threadListLoader}
      />,
    );

    expect(await screen.findByText("旧会话消息")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "切换到会话 目标会话" }),
    );

    expect(await screen.findByText("目标会话消息")).toBeInTheDocument();
    expect(screen.queryByText("旧会话消息")).not.toBeInTheDocument();
    expect(selectCurrentThreadId).toHaveBeenCalledWith(NEXT_THREAD_ID);
    expect(
      screen.getByRole("button", { name: "切换到会话 目标会话" }),
    ).toHaveAttribute("aria-current", "page");
    expect(historyPageLoader).toHaveBeenLastCalledWith(
      expect.objectContaining({ threadId: NEXT_THREAD_ID }),
    );
  });

  it("展示服务端标题，改名失败时保留输入并允许原地重试", async () => {
    const thread = {
      threadId: THREAD_ID,
      title: "原始标题",
      status: "idle" as const,
      projectId: null,
      createdAt: "2026-08-26T08:00:00+00:00",
      updatedAt: "2026-08-26T09:00:00+00:00",
    };
    const threadListLoader: ThreadListLoader = () => Promise.resolve([thread]);
    const threadTitleUpdater = vi
      .fn<ThreadTitleUpdater>()
      .mockRejectedValueOnce(new Error("改名服务暂时不可用"))
      .mockResolvedValueOnce({
        ...thread,
        title: "新的会话标题",
        updatedAt: "2026-08-26T10:00:00+00:00",
      });

    render(
      <ChatPage
        currentThreadRepository={fixedThreadRepository()}
        threadListLoader={threadListLoader}
        threadTitleUpdater={threadTitleUpdater}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "会话操作 原始标题" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "重命名会话 原始标题" }),
    );
    const titleInput = screen.getByRole("textbox", { name: "会话标题" });
    fireEvent.change(titleInput, { target: { value: "新的会话标题" } });
    fireEvent.click(screen.getByRole("button", { name: "保存标题" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "改名服务暂时不可用",
    );
    expect(titleInput).toHaveValue("新的会话标题");

    fireEvent.click(screen.getByRole("button", { name: "保存标题" }));
    expect(
      await screen.findByRole("button", { name: "切换到会话 新的会话标题" }),
    ).toBeInTheDocument();
    expect(threadTitleUpdater).toHaveBeenCalledTimes(2);
  });

  it("确认删除当前会话后切换到全新 Thread 并清空旧历史", async () => {
    const currentThread = {
      threadId: THREAD_ID,
      title: "准备删除的会话",
      status: "idle" as const,
      projectId: null,
      createdAt: "2026-08-30T08:00:00+00:00",
      updatedAt: "2026-08-30T09:00:00+00:00",
    };
    const createNewCurrentThreadId = vi.fn(() => NEXT_THREAD_ID);
    const repository: CurrentThreadRepository = {
      getOrCreateCurrentThreadId: () => THREAD_ID,
      createNewCurrentThreadId,
      selectCurrentThreadId: (threadId) => threadId,
    };
    const threadDeleter = vi.fn<ThreadDeleter>().mockResolvedValue(undefined);
    const historyPageLoader = vi.fn<ThreadHistoryPageLoader>((request) =>
      Promise.resolve({
        version: "1",
        threadId: request.threadId,
        threadExists: request.threadId === THREAD_ID,
        items:
          request.threadId === THREAD_ID
            ? [
                {
                  kind: "message" as const,
                  id: "message-before-delete",
                  role: "user" as const,
                  content: "删除前的历史",
                  runId: RUN_ID,
                  threadSequence: 1,
                  createdAt: "2026-08-30T08:00:00+00:00",
                },
              ]
            : [],
        hasMore: false,
        nextBeforeSequence: null,
      }),
    );

    render(
      <ChatPage
        currentThreadRepository={repository}
        historyPageLoader={historyPageLoader}
        threadListLoader={() => Promise.resolve([currentThread])}
        threadDeleter={threadDeleter}
      />,
    );

    expect(await screen.findByText("删除前的历史")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "会话操作 准备删除的会话" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "删除会话 准备删除的会话" }),
    );
    expect(screen.getByText("此操作不可撤销")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "确认删除 准备删除的会话" }),
    );

    await waitFor(() =>
      expect(createNewCurrentThreadId).toHaveBeenCalledOnce(),
    );
    expect(threadDeleter).toHaveBeenCalledWith({ threadId: THREAD_ID });
    expect(screen.getByText("新对话")).toBeInTheDocument();
    expect(await screen.findByLabelText("开始新对话")).toBeInTheDocument();
    expect(screen.queryByText("删除前的历史")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "删除会话 准备删除的会话" }),
    ).not.toBeInTheDocument();
  });

  it("删除失败时保留会话并在确认区域显示错误", async () => {
    const thread = {
      threadId: THREAD_ID,
      title: "不能删除的会话",
      status: "idle" as const,
      projectId: null,
      createdAt: "2026-08-30T08:00:00+00:00",
      updatedAt: "2026-08-30T09:00:00+00:00",
    };
    const threadDeleter = vi
      .fn<ThreadDeleter>()
      .mockRejectedValue(new Error("删除服务暂时不可用"));

    render(
      <ChatPage
        currentThreadRepository={fixedThreadRepository()}
        threadListLoader={() => Promise.resolve([thread])}
        threadDeleter={threadDeleter}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "会话操作 不能删除的会话",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "删除会话 不能删除的会话" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "确认删除 不能删除的会话" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "删除服务暂时不可用",
    );
    expect(
      screen.getByRole("button", { name: "确认删除 不能删除的会话" }),
    ).toBeEnabled();
  });

  it("挂载时恢复持久化消息，并与后续实时消息使用同一时间线", async () => {
    const historyPageLoader: ThreadHistoryPageLoader = (request) =>
      Promise.resolve({
        version: "1",
        threadId: request.threadId,
        threadExists: true,
        items: [
          {
            kind: "message",
            id: "history-user-1",
            role: "user",
            content: "刷新前的问题",
            runId: RUN_ID,
            threadSequence: 1,
            createdAt: "2026-08-26T08:00:00+00:00",
          },
          {
            kind: "message",
            id: "history-assistant-1",
            role: "assistant",
            content: "刷新前的回答",
            runId: RUN_ID,
            threadSequence: 2,
            createdAt: "2026-08-26T08:00:01+00:00",
          },
        ],
        hasMore: false,
        nextBeforeSequence: null,
      });
    const threadRunsLoader: ThreadRunsLoader = () =>
      Promise.resolve([
        persistedRun("history-user-1", {
          startedAt: "2026-08-26T08:00:00Z",
          finishedAt: "2026-08-26T08:00:05Z",
        }),
      ]);

    render(
      <ChatPage
        currentThreadRepository={fixedThreadRepository()}
        historyPageLoader={historyPageLoader}
        threadRunsLoader={threadRunsLoader}
      />,
    );

    expect(await screen.findByText("刷新前的问题")).toBeInTheDocument();
    expect(screen.getByText("刷新前的回答")).toBeInTheDocument();
    expect(screen.getByLabelText("执行完成，用时 5 秒")).toBeInTheDocument();
    expect(screen.queryByLabelText("开始新对话")).not.toBeInTheDocument();
  });

  it("刷新后恢复最新 Todo，并在输入框上方独立展示", async () => {
    const historyPageLoader: ThreadHistoryPageLoader = (request) =>
      Promise.resolve({
        version: "1",
        threadId: request.threadId,
        threadExists: true,
        items: [
          {
            kind: "message",
            id: "history-todo-user",
            role: "user",
            content: "完成复杂任务",
            runId: RUN_ID,
            threadSequence: 1,
            createdAt: "2026-08-30T07:00:00+00:00",
          },
          {
            kind: "tool",
            id: "history-todo-tool",
            toolCallId: "call-todo-history",
            name: "write_todos",
            input: "{}",
            result: JSON.stringify({
              todos: [
                { content: "分析需求", status: "completed" },
                { content: "改造界面", status: "in_progress" },
              ],
            }),
            status: "completed",
            runId: RUN_ID,
            threadSequence: 2,
            createdAt: "2026-08-30T07:00:01+00:00",
          },
          {
            kind: "message",
            id: "history-todo-assistant",
            role: "assistant",
            content: "正在处理。",
            runId: RUN_ID,
            threadSequence: 3,
            createdAt: "2026-08-30T07:00:02+00:00",
          },
        ],
        hasMore: false,
        nextBeforeSequence: null,
      });

    const { container } = render(
      <ChatPage
        currentThreadRepository={fixedThreadRepository()}
        historyPageLoader={historyPageLoader}
      />,
    );

    expect(await screen.findByText("正在处理。")).toBeInTheDocument();
    expect(screen.getByText("更新任务清单")).toBeInTheDocument();
    const todoHeader = screen.getByRole("button", { name: /Todos/ });
    const composerRegion = container.querySelector(".composer-region");
    expect(composerRegion?.firstElementChild).toHaveClass("todo-panel");
    fireEvent.click(todoHeader);
    expect(screen.getByText("分析需求")).toBeVisible();
    expect(screen.getByText("改造界面")).toBeVisible();
  });

  it("刷新后从持久历史恢复搜索来源卡和 Assistant 引用", async () => {
    const searchResult = JSON.stringify({
      query: "Mini Deer",
      total_results: 1,
      results: [
        {
          title: "示例研究",
          url: "https://example.com/research",
          content: "刷新后仍可读取的搜索摘要。",
        },
      ],
    });
    const historyPageLoader: ThreadHistoryPageLoader = (request) =>
      Promise.resolve({
        version: "1",
        threadId: request.threadId,
        threadExists: true,
        items: [
          {
            kind: "message",
            id: "history-search-user",
            role: "user",
            content: "搜索并给出来源",
            runId: RUN_ID,
            threadSequence: 1,
            createdAt: "2026-08-30T08:00:00+00:00",
          },
          {
            kind: "tool",
            id: "history-search-tool",
            toolCallId: "call-search-history",
            name: "web_search",
            input: '{"query":"Mini Deer"}',
            result: searchResult,
            status: "completed",
            runId: RUN_ID,
            threadSequence: 2,
            createdAt: "2026-08-30T08:00:01+00:00",
          },
          {
            kind: "message",
            id: "history-search-assistant",
            role: "assistant",
            content:
              "刷新后的搜索回答 [citation:示例研究](https://example.com/research)",
            runId: RUN_ID,
            threadSequence: 3,
            createdAt: "2026-08-30T08:00:02+00:00",
          },
        ],
        hasMore: false,
        nextBeforeSequence: null,
      });

    render(
      <ChatPage
        currentThreadRepository={fixedThreadRepository()}
        historyPageLoader={historyPageLoader}
      />,
    );

    expect(await screen.findByText("刷新后的搜索回答")).toBeInTheDocument();
    expect(screen.getByText("参考来源（1）")).toBeInTheDocument();
    const tool = screen.getByRole("status", { name: "工具 web_search 已完成" });
    expect(within(tool).getByText("搜索“Mini Deer”")).toBeInTheDocument();
    expect(
      within(tool).getByRole("link", { name: "示例研究" }),
    ).toHaveAttribute("href", "https://example.com/research");
    expect(
      within(tool).queryByText("刷新后仍可读取的搜索摘要。"),
    ).not.toBeInTheDocument();
  });

  it("刷新后从持久历史恢复网页读取卡和正文引用", async () => {
    const fetchResult = JSON.stringify({
      requested_url: "https://example.com/article",
      url: "https://example.com/article",
      title: "已读取的文章",
      content: "刷新后仍能看到的网页正文摘要。",
      characters: 15,
      truncated: false,
    });
    const historyPageLoader: ThreadHistoryPageLoader = (request) =>
      Promise.resolve({
        version: "1",
        threadId: request.threadId,
        threadExists: true,
        items: [
          {
            kind: "message",
            id: "history-fetch-user",
            role: "user",
            content: "读取网页后回答",
            runId: RUN_ID,
            threadSequence: 1,
            createdAt: "2026-08-30T09:00:00+00:00",
          },
          {
            kind: "tool",
            id: "history-fetch-tool",
            toolCallId: "call-fetch-history",
            name: "web_fetch",
            input: '{"url":"https://example.com/article"}',
            result: fetchResult,
            status: "completed",
            runId: RUN_ID,
            threadSequence: 2,
            createdAt: "2026-08-30T09:00:01+00:00",
          },
          {
            kind: "message",
            id: "history-fetch-assistant",
            role: "assistant",
            content:
              "正文结论 [citation:已读取的文章](https://example.com/article)",
            runId: RUN_ID,
            threadSequence: 3,
            createdAt: "2026-08-30T09:00:02+00:00",
          },
        ],
        hasMore: false,
        nextBeforeSequence: null,
      });

    render(
      <ChatPage
        currentThreadRepository={fixedThreadRepository()}
        historyPageLoader={historyPageLoader}
      />,
    );

    expect(await screen.findByText("正文结论")).toBeInTheDocument();
    expect(screen.getByText("参考来源（1）")).toBeInTheDocument();
    const tool = screen.getByRole("status", { name: "工具 web_fetch 已完成" });
    expect(within(tool).getByText("读取网页")).toBeInTheDocument();
    expect(within(tool).getByText("已读取的文章")).toBeInTheDocument();
    expect(
      within(tool).queryByText("刷新后仍能看到的网页正文摘要。"),
    ).not.toBeInTheDocument();
  });

  it("加载更早消息后把每个 Run 的耗时恢复到自己的轮次", async () => {
    const historyPageLoader: ThreadHistoryPageLoader = (request) =>
      Promise.resolve(
        request.beforeSequence === undefined
          ? {
              version: "1",
              threadId: THREAD_ID,
              threadExists: true,
              items: [
                {
                  kind: "message",
                  id: "history-user-2",
                  role: "user",
                  content: "较新的问题",
                  runId: NEXT_RUN_ID,
                  threadSequence: 3,
                  createdAt: "2026-08-29T08:01:00Z",
                },
                {
                  kind: "message",
                  id: "history-assistant-2",
                  role: "assistant",
                  content: "较新的回答",
                  runId: NEXT_RUN_ID,
                  threadSequence: 4,
                  createdAt: "2026-08-29T08:01:02Z",
                },
              ],
              hasMore: true,
              nextBeforeSequence: 3,
            }
          : {
              version: "1",
              threadId: THREAD_ID,
              threadExists: true,
              items: [
                {
                  kind: "message",
                  id: "history-user-1",
                  role: "user",
                  content: "更早的问题",
                  runId: RUN_ID,
                  threadSequence: 1,
                  createdAt: "2026-08-29T08:00:00Z",
                },
                {
                  kind: "message",
                  id: "history-assistant-1",
                  role: "assistant",
                  content: "更早的回答",
                  runId: RUN_ID,
                  threadSequence: 2,
                  createdAt: "2026-08-29T08:00:05Z",
                },
              ],
              hasMore: false,
              nextBeforeSequence: null,
            },
      );
    const threadRunsLoader: ThreadRunsLoader = () =>
      Promise.resolve([
        persistedRun("history-user-2", {
          runId: NEXT_RUN_ID,
          startedAt: "2026-08-29T08:01:00Z",
          finishedAt: "2026-08-29T08:01:02Z",
        }),
        persistedRun("history-user-1", {
          startedAt: "2026-08-29T08:00:00Z",
          finishedAt: "2026-08-29T08:00:05Z",
        }),
      ]);

    render(
      <ChatPage
        currentThreadRepository={fixedThreadRepository()}
        historyPageLoader={historyPageLoader}
        threadRunsLoader={threadRunsLoader}
      />,
    );

    expect(
      await screen.findByLabelText("执行完成，用时 2 秒"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "加载更早消息" }));
    expect(await screen.findByText("更早的问题")).toBeInTheDocument();
    expect(screen.getByLabelText("执行完成，用时 5 秒")).toBeInTheDocument();
    expect(screen.getAllByTestId("run-timing")).toHaveLength(2);
  });
});
