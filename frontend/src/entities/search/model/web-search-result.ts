export interface WebSearchSource {
  readonly title: string;
  readonly url: string;
  readonly domain: string;
  readonly content: string;
}

export interface WebSearchResult {
  readonly query: string;
  readonly sources: readonly WebSearchSource[];
  readonly error: string | null;
}

type UnknownRecord = Record<string, unknown>;

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

/** 校验持久化工具 JSON；非法结构返回 null，让工具卡安全退回原始文本。 */
export function parseWebSearchResult(value: string): WebSearchResult | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value) as unknown;
  } catch {
    return null;
  }
  if (
    !isRecord(parsed) ||
    typeof parsed.query !== "string" ||
    !Array.isArray(parsed.results) ||
    (parsed.error !== undefined && typeof parsed.error !== "string")
  ) {
    return null;
  }

  const sources: WebSearchSource[] = [];
  for (const candidate of parsed.results.slice(0, 10)) {
    if (!isRecord(candidate)) {
      continue;
    }
    const url = normalizeHttpUrl(candidate.url);
    if (url === null) {
      continue;
    }
    const domain = new URL(url).hostname.replace(/^www\./i, "");
    const title =
      typeof candidate.title === "string" && candidate.title.trim().length > 0
        ? candidate.title.trim()
        : domain;
    sources.push({
      title,
      url,
      domain,
      content:
        typeof candidate.content === "string" ? candidate.content.trim() : "",
    });
  }

  return {
    query: parsed.query.trim(),
    sources,
    error: typeof parsed.error === "string" ? parsed.error : null,
  };
}
