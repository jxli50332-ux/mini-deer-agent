export interface WebFetchResult {
  readonly url: string;
  readonly title: string;
  readonly domain: string;
  readonly excerpt: string;
  readonly characters: number;
  readonly truncated: boolean;
  readonly error: string | null;
}

type UnknownRecord = Record<string, unknown>;

const MAX_EXCERPT_CHARACTERS = 500;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return url.href;
  } catch {
    return null;
  }
}

function createExcerpt(content: string): string {
  const normalized = content.replace(/\s+/g, " ").trim();
  return normalized.length > MAX_EXCERPT_CHARACTERS
    ? `${normalized.slice(0, MAX_EXCERPT_CHARACTERS)}…`
    : normalized;
}

/** 校验持久化 web_fetch JSON，只把安全链接和有界正文预览交给组件。 */
export function parseWebFetchResult(value: string): WebFetchResult | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value) as unknown;
  } catch {
    return null;
  }
  if (
    !isRecord(parsed) ||
    typeof parsed.title !== "string" ||
    typeof parsed.content !== "string" ||
    typeof parsed.characters !== "number" ||
    !Number.isSafeInteger(parsed.characters) ||
    parsed.characters < 0 ||
    typeof parsed.truncated !== "boolean" ||
    (parsed.error !== undefined && typeof parsed.error !== "string")
  ) {
    return null;
  }

  const url = normalizeHttpUrl(parsed.url);
  if (url === null) {
    return null;
  }
  const domain = new URL(url).hostname.replace(/^www\./i, "");
  const title = parsed.title.trim() || domain;

  return {
    url,
    title,
    domain,
    excerpt: createExcerpt(parsed.content),
    characters: parsed.characters,
    truncated: parsed.truncated,
    error: typeof parsed.error === "string" ? parsed.error : null,
  };
}
