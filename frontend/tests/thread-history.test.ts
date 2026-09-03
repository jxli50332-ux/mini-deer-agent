import { describe, expect, it, vi } from "vitest";

import {
  fetchThreadHistoryPage,
  parseThreadHistoryPage,
  type HistoryFetchLike,
} from "@/features/threads/api/thread-history";

const THREAD_ID = "11111111-1111-4111-8111-111111111111";
const RUN_ID = "22222222-2222-4222-8222-222222222222";

function wirePage() {
  return {
    version: "1",
    thread_id: THREAD_ID,
    thread_exists: true,
    items: [
      {
        kind: "message",
        id: "message-1",
        run_id: RUN_ID,
        thread_sequence: 3,
        role: "user",
        content: "查询天气",
        hidden_from_ui: true,
        human_input_response: {
          version: 1,
          kind: "human_input_response",
          request_id: "clarification:call-1",
          response_kind: "text",
          value: "北京",
        },
        attachments: [
          {
            filename: "weather.csv",
            media_type: "text/csv",
            size_bytes: 28,
            content: "city,temp\n北京,24",
          },
        ],
        created_at: "2026-08-26T08:00:00+00:00",
      },
      {
        kind: "tool",
        id: `tool:${RUN_ID}:call-1`,
        run_id: RUN_ID,
        thread_sequence: 4,
        tool_call_id: "call-1",
        name: "get_weather",
        input: '{"city":"北京"}',
        result: "北京 24°C",
        status: "completed",
        created_at: "2026-08-26T08:00:01+00:00",
      },
    ],
    has_more: true,
    next_before_sequence: 3,
  };
}

describe("Thread history API client", () => {
  it("校验 wire 响应并投影为前端时间线字段", () => {
    const page = parseThreadHistoryPage(wirePage(), THREAD_ID);

    expect(page).toMatchObject({
      version: "1",
      threadId: THREAD_ID,
      threadExists: true,
      hasMore: true,
      nextBeforeSequence: 3,
    });
    expect(page.items[1]).toMatchObject({
      kind: "tool",
      toolCallId: "call-1",
      threadSequence: 4,
      status: "completed",
    });
    expect(page.items[0]).toMatchObject({
      kind: "message",
      hiddenFromUi: true,
      humanInputResponse: {
        request_id: "clarification:call-1",
        response_kind: "text",
        value: "北京",
      },
      attachments: [
        {
          filename: "weather.csv",
          mediaType: "text/csv",
          sizeBytes: 28,
          content: "city,temp\n北京,24",
        },
      ],
    });
  });

  it("发送游标查询且不读取错误响应正文", async () => {
    const fetcher = vi.fn<HistoryFetchLike>(() =>
      Promise.resolve(Response.json(wirePage())),
    );
    const page = await fetchThreadHistoryPage(
      { threadId: THREAD_ID, limit: 20, beforeSequence: 9 },
      { fetcher },
    );

    expect(page.items).toHaveLength(2);
    expect(fetcher).toHaveBeenCalledWith(
      `/api/v1/threads/${THREAD_ID}/messages?limit=20&before_sequence=9`,
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );

    const secret = "secret-database-detail";
    await expect(
      fetchThreadHistoryPage(
        { threadId: THREAD_ID },
        {
          fetcher: () => Promise.resolve(new Response(secret, { status: 500 })),
        },
      ),
    ).rejects.not.toThrow(secret);
  });

  it("拒绝乱序、重复身份和错误分页游标", () => {
    const valid = wirePage();
    const invalid = {
      ...valid,
      items: [
        valid.items[0]!,
        {
          ...valid.items[0]!,
          thread_sequence: 2,
        },
      ],
    };

    expect(() => parseThreadHistoryPage(invalid, THREAD_ID)).toThrow(
      "历史项目 ID 重复或顺序不严格递增",
    );
  });

  it("明确区分尚未创建的本地 Thread 与空的已存在 Thread", () => {
    const missing = parseThreadHistoryPage(
      {
        version: "1",
        thread_id: THREAD_ID,
        thread_exists: false,
        items: [],
        has_more: false,
        next_before_sequence: null,
      },
      THREAD_ID,
    );

    expect(missing.threadExists).toBe(false);
    expect(missing.items).toEqual([]);
  });
});
