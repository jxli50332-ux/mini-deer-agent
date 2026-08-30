export interface SseFrame {
  readonly event: string;
  readonly data: string;
  readonly id?: string;
  readonly retry?: number;
}

export interface SseParserOptions {
  readonly maxLineCharacters?: number;
  readonly maxEventCharacters?: number;
}

export interface SseStreamOptions extends SseParserOptions {
  readonly inactivityTimeoutMilliseconds?: number;
}

export type SseParseErrorCode =
  | "invalid_limit"
  | "invalid_utf8"
  | "line_too_large"
  | "event_too_large"
  | "truncated_frame"
  | "parser_closed";

export class SseParseError extends Error {
  readonly code: SseParseErrorCode;

  constructor(code: SseParseErrorCode, message: string) {
    super(message);
    this.name = "SseParseError";
    this.code = code;
  }
}

export class SseInactivityTimeoutError extends Error {
  readonly timeoutMilliseconds: number;

  constructor(timeoutMilliseconds: number) {
    super(`SSE 流连续 ${timeoutMilliseconds} 毫秒没有收到字节`);
    this.name = "SseInactivityTimeoutError";
    this.timeoutMilliseconds = timeoutMilliseconds;
  }
}

const DEFAULT_MAX_LINE_CHARACTERS = 1_048_576;
const DEFAULT_MAX_EVENT_CHARACTERS = 4_194_304;

interface MutableFrameState {
  event?: string;
  id?: string;
  retry?: number;
  dataLines: string[];
  dataCharacters: number;
  hasRecognizedField: boolean;
}

function createFrameState(): MutableFrameState {
  return {
    dataLines: [],
    dataCharacters: 0,
    hasRecognizedField: false,
  };
}

function normalizeLimit(
  name: string,
  value: number | undefined,
  fallback: number,
): number {
  const resolved = value ?? fallback;
  if (!Number.isSafeInteger(resolved) || resolved <= 0) {
    throw new SseParseError("invalid_limit", `${name} 必须是大于 0 的安全整数`);
  }
  return resolved;
}

interface ExtractedLine {
  readonly line: string;
  readonly consumedCharacters: number;
}

/**
 * 从文本缓冲区取出一行，同时兼容 LF、CRLF 和单独 CR。
 * 非结束状态下会保留末尾 CR，因为下一块开头可能是配对的 LF。
 */
function extractLine(buffer: string, isFinal: boolean): ExtractedLine | null {
  for (let index = 0; index < buffer.length; index += 1) {
    const character = buffer[index];
    if (character === "\n") {
      return {
        line: buffer.slice(0, index),
        consumedCharacters: index + 1,
      };
    }

    if (character !== "\r") {
      continue;
    }

    if (index + 1 === buffer.length && !isFinal) {
      return null;
    }

    const hasFollowingLineFeed = buffer[index + 1] === "\n";
    return {
      line: buffer.slice(0, index),
      consumedCharacters: index + (hasFollowingLineFeed ? 2 : 1),
    };
  }

  if (isFinal && buffer.length > 0) {
    return {
      line: buffer,
      consumedCharacters: buffer.length,
    };
  }
  return null;
}

/**
 * 增量解析已经解码的 SSE 文本。该类不知道 fetch、React 或聊天事件，
 * 因此可以复用于任何遵循 text/event-stream 的浏览器接口。
 */
export class IncrementalSseParser {
  readonly #maxLineCharacters: number;
  readonly #maxEventCharacters: number;
  #buffer = "";
  #frame = createFrameState();
  #closed = false;

  constructor(options: SseParserOptions = {}) {
    this.#maxLineCharacters = normalizeLimit(
      "maxLineCharacters",
      options.maxLineCharacters,
      DEFAULT_MAX_LINE_CHARACTERS,
    );
    this.#maxEventCharacters = normalizeLimit(
      "maxEventCharacters",
      options.maxEventCharacters,
      DEFAULT_MAX_EVENT_CHARACTERS,
    );
  }

  /** 追加一段完整 UTF-16 文本，并返回其中刚刚闭合的 SSE frame。 */
  push(chunk: string): SseFrame[] {
    this.#assertOpen();
    this.#buffer += chunk;
    const frames = this.#drainLines(false);

    // 没有换行的恶意或损坏响应不能无限占用浏览器内存。
    this.#assertLineSize(this.#buffer);
    return frames;
  }

  /**
   * 标记输入结束。SSE frame 必须以空行闭合；有字段但没有空行说明响应被截断。
   */
  finish(): SseFrame[] {
    this.#assertOpen();
    const frames = this.#drainLines(true);
    this.#closed = true;

    if (this.#frame.hasRecognizedField) {
      throw new SseParseError(
        "truncated_frame",
        "SSE 响应结束时仍有未被空行闭合的 frame",
      );
    }
    return frames;
  }

  #drainLines(isFinal: boolean): SseFrame[] {
    const frames: SseFrame[] = [];
    while (true) {
      const extracted = extractLine(this.#buffer, isFinal);
      if (extracted === null) {
        break;
      }
      this.#buffer = this.#buffer.slice(extracted.consumedCharacters);
      this.#assertLineSize(extracted.line);
      const frame = this.#consumeLine(extracted.line);
      if (frame !== null) {
        frames.push(frame);
      }
    }
    return frames;
  }

  #consumeLine(line: string): SseFrame | null {
    if (line === "") {
      return this.#dispatchFrame();
    }
    if (line.startsWith(":")) {
      // 冒号开头是 SSE 注释，常被服务端用作心跳，不进入业务事件。
      return null;
    }

    const separatorIndex = line.indexOf(":");
    const field = separatorIndex === -1 ? line : line.slice(0, separatorIndex);
    let value = separatorIndex === -1 ? "" : line.slice(separatorIndex + 1);
    if (value.startsWith(" ")) {
      // SSE 规范只移除冒号后的第一个可选空格，其余空格属于字段值。
      value = value.slice(1);
    }

    switch (field) {
      case "event":
        this.#frame.event = value;
        this.#frame.hasRecognizedField = true;
        break;
      case "data":
        this.#appendData(value);
        this.#frame.hasRecognizedField = true;
        break;
      case "id":
        // NUL 不能进入 Last-Event-ID；保留“本 frame 是否真的携带 ID”的语义。
        if (!value.includes("\0")) {
          this.#frame.id = value;
          this.#frame.hasRecognizedField = true;
        }
        break;
      case "retry":
        if (/^\d+$/.test(value)) {
          const retry = Number(value);
          if (Number.isSafeInteger(retry)) {
            this.#frame.retry = retry;
            this.#frame.hasRecognizedField = true;
          }
        }
        break;
      default:
        // 未知字段按 SSE 向前兼容规则忽略。
        break;
    }
    return null;
  }

  #appendData(value: string): void {
    const separatorCharacters = this.#frame.dataLines.length > 0 ? 1 : 0;
    const nextSize =
      this.#frame.dataCharacters + separatorCharacters + value.length;
    if (nextSize > this.#maxEventCharacters) {
      throw new SseParseError(
        "event_too_large",
        `SSE data 超过 ${this.#maxEventCharacters} 个字符`,
      );
    }
    this.#frame.dataLines.push(value);
    this.#frame.dataCharacters = nextSize;
  }

  #dispatchFrame(): SseFrame | null {
    const current = this.#frame;
    this.#frame = createFrameState();

    // 只有 data 字段才产生可交付事件；纯注释和空心跳不会污染业务状态。
    if (current.dataLines.length === 0) {
      return null;
    }

    return {
      event: current.event || "message",
      data: current.dataLines.join("\n"),
      ...(current.id === undefined ? {} : { id: current.id }),
      ...(current.retry === undefined ? {} : { retry: current.retry }),
    };
  }

  #assertLineSize(value: string): void {
    if (value.length > this.#maxLineCharacters) {
      throw new SseParseError(
        "line_too_large",
        `SSE 单行超过 ${this.#maxLineCharacters} 个字符`,
      );
    }
  }

  #assertOpen(): void {
    if (this.#closed) {
      throw new SseParseError("parser_closed", "SSE parser 已经结束");
    }
  }
}

function decodeUtf8(
  decoder: TextDecoder,
  chunk?: Uint8Array,
  stream = false,
): string {
  try {
    return decoder.decode(chunk, { stream });
  } catch {
    throw new SseParseError("invalid_utf8", "SSE 响应包含无效 UTF-8 字节");
  }
}

async function readStreamChunk(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  inactivityTimeoutMilliseconds: number | undefined,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  if (inactivityTimeoutMilliseconds === undefined) {
    return reader.read();
  }

  let timeoutHandle: ReturnType<typeof globalThis.setTimeout> | undefined;
  try {
    return await Promise.race([
      reader.read(),
      new Promise<never>((_resolve, reject) => {
        timeoutHandle = globalThis.setTimeout(() => {
          reject(new SseInactivityTimeoutError(inactivityTimeoutMilliseconds));
        }, inactivityTimeoutMilliseconds);
      }),
    ]);
  } finally {
    if (timeoutHandle !== undefined) {
      globalThis.clearTimeout(timeoutHandle);
    }
  }
}

/**
 * 从浏览器 ReadableStream 逐块产生 SSE frame。TextDecoder 的 stream 模式
 * 保证一个中文字符跨两个网络 chunk 时不会被替换成乱码。
 */
export async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
  options: SseStreamOptions = {},
): AsyncGenerator<SseFrame> {
  const reader = stream.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const parser = new IncrementalSseParser(options);
  const inactivityTimeoutMilliseconds =
    options.inactivityTimeoutMilliseconds === undefined
      ? undefined
      : normalizeLimit(
          "inactivityTimeoutMilliseconds",
          options.inactivityTimeoutMilliseconds,
          options.inactivityTimeoutMilliseconds,
        );
  let reachedEnd = false;

  try {
    while (true) {
      // 每次成功读取任意字节都会开始一个新的超时周期。心跳即使不产生
      // SseFrame，也会在这里续期；因此不能把计时放到上层业务事件循环。
      const { done, value } = await readStreamChunk(
        reader,
        inactivityTimeoutMilliseconds,
      );
      if (done) {
        break;
      }
      const text = decodeUtf8(decoder, value, true);
      for (const frame of parser.push(text)) {
        yield frame;
      }
    }

    const finalText = decodeUtf8(decoder);
    for (const frame of parser.push(finalText)) {
      yield frame;
    }
    for (const frame of parser.finish()) {
      yield frame;
    }
    reachedEnd = true;
  } finally {
    if (!reachedEnd) {
      // 消费方提前退出或解析失败时主动取消底层流，避免 HTTP 连接继续占用资源。
      await reader.cancel().catch(() => undefined);
    }
    reader.releaseLock();
  }
}
