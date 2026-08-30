import { describe, expect, it, vi } from "vitest";

import {
  cancelChatRun,
  ChatStreamClientError,
  fetchChatRun,
  reconcileChatRunAfterDisconnect,
  streamChatRun,
  type ChatStreamClientOptions,
  type ChatRunDetail,
  type FetchLike,
} from "@/features/chat/api/chat-stream";
import type { ChatRunEvent } from "@/features/chat/model/events";

const encoder = new TextEncoder();
const RUN_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_RUN_ID = "33333333-3333-4333-8333-333333333333";
const THREAD_ID = "22222222-2222-4222-8222-222222222222";
const MESSAGE_ID = "44444444-4444-4444-8444-444444444444";

function byteStream(chunks: readonly string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }
      controller.close();
    },
  });
}

function wireFrame(
  event: string,
  sequence: number,
  payload: Record<string, unknown>,
  options: {
    readonly runId?: string;
    readonly threadId?: string;
    readonly messageId?: string | null;
  } = {},
): string {
  const runId = options.runId ?? RUN_ID;
  return (
    `id: ${runId}:${sequence}\n` +
    `event: ${event}\n` +
    `data: ${JSON.stringify({
      version: "1",
      run_id: runId,
      thread_id: options.threadId ?? THREAD_ID,
      sequence,
      message_id: options.messageId ?? null,
      payload,
    })}\n\n`
  );
}

function successResponse(chunks: readonly string[], runId = RUN_ID): Response {
  return new Response(byteStream(chunks), {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "X-Run-ID": runId,
    },
  });
}

function runDetail(
  status: ChatRunDetail["status"],
  overrides: Partial<ChatRunDetail> = {},
): ChatRunDetail {
  return {
    runId: RUN_ID,
    threadId: THREAD_ID,
    status,
    userMessageId: MESSAGE_ID,
    createdAt: "2026-08-28T00:00:00+00:00",
    startedAt: "2026-08-28T00:00:01+00:00",
    finishedAt: status === "running" ? null : "2026-08-28T00:00:02+00:00",
    finishReason: status === "completed" ? "stop" : null,
    errorCode: status === "failed" ? "agent_execution_failed" : null,
    ...overrides,
  };
}

function runDetailResponse(detail: ChatRunDetail): Response {
  return Response.json({
    run_id: detail.runId,
    thread_id: detail.threadId,
    status: detail.status,
    user_message_id: detail.userMessageId,
    created_at: detail.createdAt,
    started_at: detail.startedAt,
    finished_at: detail.finishedAt,
    finish_reason: detail.finishReason,
    error_code: detail.errorCode,
  });
}

async function collectEvents(
  fetcher: FetchLike,
  options: { readonly signal?: AbortSignal } = {},
  clientOptions: Omit<ChatStreamClientOptions, "fetcher"> = {},
): Promise<ChatRunEvent[]> {
  const events: ChatRunEvent[] = [];
  for await (const event of streamChatRun(
    {
      threadId: THREAD_ID,
      messageId: MESSAGE_ID,
      message: "  查询北京天气  ",
      ...(options.signal === undefined ? {} : { signal: options.signal }),
    },
    { fetcher, ...clientOptions },
  )) {
    events.push(event);
  }
  return events;
}

async function captureClientError(
  promise: Promise<unknown>,
): Promise<ChatStreamClientError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ChatStreamClientError) {
      return error;
    }
    throw error;
  }
  throw new Error("预期 ChatStreamClientError，但请求成功了");
}

describe("POST SSE chat client", () => {
  it("发送同源版本化 POST，并逐条返回通过校验的事件", async () => {
    const observedRunIds: string[] = [];
    const fetcher = vi.fn<FetchLike>(() =>
      Promise.resolve(
        successResponse([
          wireFrame("run_started", 1, {
            created_at: "2026-08-25T15:00:00+00:00",
          }).slice(0, 45),
          wireFrame("run_started", 1, {
            created_at: "2026-08-25T15:00:00+00:00",
          }).slice(45) +
            wireFrame("run_completed", 2, { finish_reason: "stop" }),
        ]),
      ),
    );

    const events: ChatRunEvent[] = [];
    for await (const event of streamChatRun(
      {
        threadId: THREAD_ID,
        messageId: MESSAGE_ID,
        message: "  查询北京天气  ",
        attachments: [{ filename: "brief.md", content: "代号：云杉" }],
        onRunId: (runId) => observedRunIds.push(runId),
      },
      { fetcher },
    )) {
      events.push(event);
    }

    expect(events.map((event) => event.event)).toEqual([
      "run_started",
      "run_completed",
    ]);
    expect(observedRunIds).toEqual([RUN_ID]);
    expect(fetcher).toHaveBeenCalledOnce();
    const [url, init] = fetcher.mock.calls[0] ?? [];
    expect(url).toBe(`/api/v1/threads/${THREAD_ID}/runs/stream`);
    expect(init).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      body: JSON.stringify({
        message_id: MESSAGE_ID,
        message: "查询北京天气",
        attachments: [{ filename: "brief.md", content: "代号：云杉" }],
      }),
    });
    expect(new Headers(init?.headers).get("accept")).toBe("text/event-stream");
    expect(new Headers(init?.headers).get("content-type")).toBe(
      "application/json",
    );
  });

  it("在 fetch 前拒绝非法 thread ID 和空消息", async () => {
    const fetcher = vi.fn<FetchLike>();
    const invalidThread = (async () => {
      for await (const event of streamChatRun(
        { threadId: "not-a-uuid", messageId: MESSAGE_ID, message: "hello" },
        { fetcher },
      )) {
        throw new Error(`非法请求不应产生事件：${event.event}`);
      }
    })();

    await expect(invalidThread).rejects.toMatchObject({
      code: "invalid_request",
    });

    const emptyMessage = (async () => {
      for await (const event of streamChatRun(
        { threadId: THREAD_ID, messageId: MESSAGE_ID, message: "   " },
        { fetcher },
      )) {
        throw new Error(`空消息不应产生事件：${event.event}`);
      }
    })();
    await expect(emptyMessage).rejects.toMatchObject({
      code: "invalid_request",
    });

    const invalidMessageId = (async () => {
      for await (const event of streamChatRun(
        { threadId: THREAD_ID, messageId: "invalid", message: "hello" },
        { fetcher },
      )) {
        throw new Error(`非法请求不应产生事件：${event.event}`);
      }
    })();
    await expect(invalidMessageId).rejects.toMatchObject({
      code: "invalid_request",
    });
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("在 fetch 前拒绝不支持、过大或过多的文本附件", async () => {
    const fetcher = vi.fn<FetchLike>();
    const invalidRequests = [
      [{ filename: "brief.pdf", content: "x" }],
      [{ filename: "large.txt", content: "x".repeat(32 * 1024 + 1) }],
      [
        { filename: "1.txt", content: "1" },
        { filename: "2.txt", content: "2" },
        { filename: "3.txt", content: "3" },
        { filename: "4.txt", content: "4" },
      ],
    ];

    for (const attachments of invalidRequests) {
      const request = (async () => {
        for await (const event of streamChatRun(
          {
            threadId: THREAD_ID,
            messageId: MESSAGE_ID,
            message: "读取附件",
            attachments,
          },
          { fetcher },
        )) {
          throw new Error(`非法附件不应产生事件：${event.event}`);
        }
      })();
      await expect(request).rejects.toMatchObject({ code: "invalid_request" });
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("把 HTTP 状态映射为稳定且不含响应正文的客户端错误", async () => {
    const secret = "sk-secret-from-error-body";
    const error = await captureClientError(
      collectEvents(() =>
        Promise.resolve(new Response(secret, { status: 422 })),
      ),
    );

    expect(error).toMatchObject({
      code: "invalid_request",
      status: 422,
      retryable: false,
    });
    expect(error.message).not.toContain(secret);
  });

  it("拒绝非 SSE Content-Type、空 body 和缺失 X-Run-ID", async () => {
    const invalidType = await captureClientError(
      collectEvents(() =>
        Promise.resolve(
          new Response("not sse", {
            headers: { "Content-Type": "application/json" },
          }),
        ),
      ),
    );
    expect(invalidType.code).toBe("invalid_content_type");

    const emptyBody = await captureClientError(
      collectEvents(() =>
        Promise.resolve(
          new Response(null, {
            headers: {
              "Content-Type": "text/event-stream",
              "X-Run-ID": RUN_ID,
            },
          }),
        ),
      ),
    );
    expect(emptyBody.code).toBe("missing_response_body");

    const missingRunId = await captureClientError(
      collectEvents(() =>
        Promise.resolve(
          new Response(byteStream([]), {
            headers: { "Content-Type": "text/event-stream" },
          }),
        ),
      ),
    );
    expect(missingRunId.code).toBe("missing_run_id");
  });

  it("拒绝响应头 run ID 与事件 run ID 不一致", async () => {
    const error = await captureClientError(
      collectEvents(() =>
        Promise.resolve(
          successResponse(
            [
              wireFrame("run_started", 1, {
                created_at: "2026-08-25T15:00:00+00:00",
              }),
            ],
            OTHER_RUN_ID,
          ),
        ),
      ),
    );

    expect(error).toMatchObject({
      code: "stream_protocol_error",
      retryable: false,
    });
  });

  it("把事件 JSON 校验失败转换为脱敏协议错误", async () => {
    const secret = "sk-secret-in-invalid-json";
    const error = await captureClientError(
      collectEvents(() =>
        Promise.resolve(
          successResponse([
            `id: ${RUN_ID}:1\nevent: run_started\ndata: {${secret}\n\n`,
          ]),
        ),
      ),
    );

    expect(error.code).toBe("stream_protocol_error");
    expect(error.message).not.toContain(secret);
  });

  it("事件流没有正常终止事件时返回可重试的不完整错误", async () => {
    const error = await captureClientError(
      collectEvents(() =>
        Promise.resolve(
          successResponse([
            wireFrame("run_started", 1, {
              created_at: "2026-08-25T15:00:00+00:00",
            }),
          ]),
        ),
      ),
    );

    expect(error).toMatchObject({
      code: "incomplete_stream",
      retryable: true,
    });
  });

  it("把已连接但长期没有字节的流转换为可重试静默错误", async () => {
    let bodyCancelled = false;
    const stalledBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            wireFrame("run_started", 1, {
              created_at: "2026-08-28T00:00:00+00:00",
            }),
          ),
        );
      },
      cancel() {
        bodyCancelled = true;
      },
    });
    const fetcher: FetchLike = () =>
      Promise.resolve(
        new Response(stalledBody, {
          status: 200,
          headers: {
            "Content-Type": "text/event-stream; charset=utf-8",
            "X-Run-ID": RUN_ID,
          },
        }),
      );

    const error = await captureClientError(
      collectEvents(fetcher, {}, { inactivityTimeoutMilliseconds: 10 }),
    );

    expect(error).toMatchObject({
      code: "stream_inactive",
      retryable: true,
      status: null,
    });
    expect(error.message).toBe(
      "长时间未收到 Agent 心跳或事件，连接可能已经中断",
    );
    expect(bodyCancelled).toBe(true);
  });

  it("终止事件后出现新 frame 时返回协议错误", async () => {
    const error = await captureClientError(
      collectEvents(() =>
        Promise.resolve(
          successResponse([
            wireFrame("run_started", 1, {
              created_at: "2026-08-25T15:00:00+00:00",
            }) +
              wireFrame("run_completed", 2, { finish_reason: "stop" }) +
              wireFrame(
                "ai_delta",
                3,
                { text: "late" },
                { messageId: "assistant-1" },
              ),
          ]),
        ),
      ),
    );

    expect(error.code).toBe("stream_protocol_error");
  });

  it("AbortSignal 中止被区分为不可重试的 cancelled 语义", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetcher: FetchLike = (input, init) => {
      void input;
      expect(init?.signal?.aborted).toBe(true);
      return Promise.reject(new DOMException("aborted", "AbortError"));
    };

    const error = await captureClientError(
      collectEvents(fetcher, { signal: controller.signal }),
    );
    expect(error).toMatchObject({
      code: "aborted",
      retryable: false,
      status: null,
    });
  });

  it("显式取消使用 thread/run 路径，并把重复取消成功视为 204", async () => {
    const fetcher = vi.fn<FetchLike>(() =>
      Promise.resolve(new Response(null, { status: 204 })),
    );

    await cancelChatRun({ threadId: THREAD_ID, runId: RUN_ID }, { fetcher });

    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/threads/${THREAD_ID}/runs/${RUN_ID}/cancel`,
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("取消接口把 404 和 409 转换为稳定错误", async () => {
    await expect(
      cancelChatRun(
        { threadId: THREAD_ID, runId: RUN_ID },
        { fetcher: () => Promise.resolve(new Response(null, { status: 404 })) },
      ),
    ).rejects.toMatchObject({ code: "run_not_found", retryable: false });

    await expect(
      cancelChatRun(
        { threadId: THREAD_ID, runId: RUN_ID },
        { fetcher: () => Promise.resolve(new Response(null, { status: 409 })) },
      ),
    ).rejects.toMatchObject({ code: "run_not_cancellable", retryable: true });
  });

  it("查询并校验单个 Run 的持久化生命周期响应", async () => {
    const fetcher = vi.fn<FetchLike>(() =>
      Promise.resolve(runDetailResponse(runDetail("completed"))),
    );

    await expect(
      fetchChatRun({ threadId: THREAD_ID, runId: RUN_ID }, { fetcher }),
    ).resolves.toEqual(runDetail("completed"));
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/threads/${THREAD_ID}/runs/${RUN_ID}`,
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      }),
    );
  });

  it("Run 详情拒绝身份错配，并把不存在映射为稳定错误", async () => {
    await expect(
      fetchChatRun(
        { threadId: THREAD_ID, runId: RUN_ID },
        {
          fetcher: () =>
            Promise.resolve(
              runDetailResponse(
                runDetail("completed", { runId: OTHER_RUN_ID }),
              ),
            ),
        },
      ),
    ).rejects.toMatchObject({
      code: "invalid_run_response",
      retryable: false,
    });

    await expect(
      fetchChatRun(
        { threadId: THREAD_ID, runId: RUN_ID },
        { fetcher: () => Promise.resolve(new Response(null, { status: 404 })) },
      ),
    ).rejects.toMatchObject({ code: "run_not_found", retryable: false });
  });

  it("断线核对会有限等待活动 Run，直到持久化终态出现", async () => {
    const responses = [runDetail("running"), runDetail("interrupted")];
    const fetcher = vi.fn<FetchLike>(() => {
      const detail = responses.shift();
      if (detail === undefined) {
        throw new Error("查询次数超出预期");
      }
      return Promise.resolve(runDetailResponse(detail));
    });

    await expect(
      reconcileChatRunAfterDisconnect(
        { threadId: THREAD_ID, runId: RUN_ID },
        { fetcher, maxAttempts: 3, retryDelayMilliseconds: 0 },
      ),
    ).resolves.toMatchObject({ status: "interrupted" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("断线核对总预算耗尽时中止挂起的 Run 请求", async () => {
    let observedSignal: AbortSignal | undefined;
    const fetcher: FetchLike = (_input, init) => {
      observedSignal = init?.signal ?? undefined;
      return new Promise((_resolve, reject) => {
        observedSignal?.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true },
        );
      });
    };

    await expect(
      reconcileChatRunAfterDisconnect(
        { threadId: THREAD_ID, runId: RUN_ID },
        { fetcher, timeoutMilliseconds: 10 },
      ),
    ).rejects.toMatchObject({ code: "aborted", retryable: false });
    expect(observedSignal?.aborted).toBe(true);
  });
});
