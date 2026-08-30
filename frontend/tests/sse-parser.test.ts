import { describe, expect, it } from "vitest";

import {
  IncrementalSseParser,
  parseSseStream,
  SseInactivityTimeoutError,
  SseParseError,
  type SseFrame,
  type SseStreamOptions,
} from "@/shared/api/sse-parser";

const encoder = new TextEncoder();

function byteStream(chunks: readonly Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
}

async function collectFrames(
  stream: ReadableStream<Uint8Array>,
  options: SseStreamOptions = {},
): Promise<SseFrame[]> {
  const frames: SseFrame[] = [];
  for await (const frame of parseSseStream(stream, options)) {
    frames.push(frame);
  }
  return frames;
}

describe("增量 SSE parser", () => {
  it("可以把跨网络 chunk 的一个 frame 重新拼接完整", async () => {
    const frames = await collectFrames(
      byteStream([
        encoder.encode("id: run-1:1\nevent: run_sta"),
        encoder.encode('rted\ndata: {"sequence":1}\n\n'),
      ]),
    );

    expect(frames).toEqual([
      {
        id: "run-1:1",
        event: "run_started",
        data: '{"sequence":1}',
      },
    ]);
  });

  it("可以从同一个 chunk 提取多个 frame", async () => {
    const frames = await collectFrames(
      byteStream([
        encoder.encode(
          'event: ai_delta\ndata: {"text":"北"}\n\n' +
            'event: ai_delta\ndata: {"text":"京"}\n\n',
        ),
      ]),
    );

    expect(frames.map((frame) => frame.data)).toEqual([
      '{"text":"北"}',
      '{"text":"京"}',
    ]);
  });

  it("兼容 CRLF、注释、多行 data、默认事件名和 retry", async () => {
    const frames = await collectFrames(
      byteStream([
        encoder.encode(
          ": heartbeat\r\n" +
            "id: event-3\r\n" +
            "retry: 1500\r\n" +
            "data: first line\r\n" +
            "data: second line\r\n\r\n",
        ),
      ]),
    );

    expect(frames).toEqual([
      {
        id: "event-3",
        event: "message",
        data: "first line\nsecond line",
        retry: 1500,
      },
    ]);
  });

  it("忽略独立心跳注释，并继续解析后续业务事件", async () => {
    const frames = await collectFrames(
      byteStream([
        encoder.encode(
          ": heartbeat\n\n" +
            'id: run-1:2\nevent: ai_delta\ndata: {"sequence":2}\n\n',
        ),
      ]),
    );

    expect(frames).toEqual([
      {
        id: "run-1:2",
        event: "ai_delta",
        data: '{"sequence":2}',
      },
    ]);
  });

  it("长时间收不到字节时取消底层流并报告静默超时", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
    });

    const collect = collectFrames(stream, {
      inactivityTimeoutMilliseconds: 10,
    });

    await expect(collect).rejects.toBeInstanceOf(SseInactivityTimeoutError);
    await expect(collect).rejects.toMatchObject({
      timeoutMilliseconds: 10,
    });
    expect(cancelled).toBe(true);
  });

  it("注释心跳属于连接活动，会重新开始静默计时", async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        setTimeout(() => {
          controller.enqueue(encoder.encode(": heartbeat\n\n"));
        }, 30);
        setTimeout(() => {
          controller.enqueue(
            encoder.encode(
              'id: run-1:2\nevent: ai_delta\ndata: {"sequence":2}\n\n',
            ),
          );
          controller.close();
        }, 60);
      },
    });

    const frames = await collectFrames(stream, {
      inactivityTimeoutMilliseconds: 50,
    });

    expect(frames).toEqual([
      {
        id: "run-1:2",
        event: "ai_delta",
        data: '{"sequence":2}',
      },
    ]);
  });

  it("CRLF 即使跨 chunk 也只被识别为一个换行", async () => {
    const frames = await collectFrames(
      byteStream([
        encoder.encode("event: tool_result\r"),
        encoder.encode("\ndata: done\r\n\r"),
        encoder.encode("\n"),
      ]),
    );

    expect(frames).toEqual([{ event: "tool_result", data: "done" }]);
  });

  it("中文 UTF-8 字节跨 chunk 时不会产生乱码", async () => {
    const fullFrame = encoder.encode("event: ai_delta\ndata: 北京天气\n\n");
    const prefixLength = encoder.encode("event: ai_delta\ndata: 北").length;
    // 在“京”的三个 UTF-8 字节内部切开，模拟真实网络最不利分片。
    const splitInsideChineseCharacter = prefixLength + 1;

    const frames = await collectFrames(
      byteStream([
        fullFrame.slice(0, splitInsideChineseCharacter),
        fullFrame.slice(splitInsideChineseCharacter),
      ]),
    );

    expect(frames).toEqual([{ event: "ai_delta", data: "北京天气" }]);
  });

  it("响应结束时拒绝没有空行终止的截断 frame", async () => {
    const collect = collectFrames(
      byteStream([encoder.encode("event: ai_delta\ndata: incomplete")]),
    );

    await expect(collect).rejects.toBeInstanceOf(SseParseError);
    await expect(collect).rejects.toMatchObject({
      name: "SseParseError",
      code: "truncated_frame",
    });
  });

  it("限制未闭合单行大小，避免异常响应无限占用内存", () => {
    const parser = new IncrementalSseParser({ maxLineCharacters: 8 });

    expect(() => parser.push("data: 12345")).toThrowError(
      expect.objectContaining({ code: "line_too_large" }),
    );
  });
});
