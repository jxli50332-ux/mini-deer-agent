export interface CitationSource {
  readonly id: string;
  readonly title: string;
  readonly url: string;
  readonly domain: string;
  readonly count: number;
}

// 排除图片引用，并允许 URL 中出现一层配对括号，避免百科消歧链接被截断。
const CITATION_LINK_PATTERN =
  /(?<!!)\[citation:\s*([^\]]+?)\]\((https?:\/\/(?:[^\s()]|\([^\s()]*\))+)\)/gi;

const GENERIC_TITLES = new Set(["source", "来源"]);

function normalizeUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }
    return parsed.href;
  } catch {
    return null;
  }
}

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./i, "");
  } catch {
    return url;
  }
}

function normalizeTitle(value: string, domain: string): string {
  const title = value.replace(/\s+/g, " ").trim();
  return title.length === 0 || GENERIC_TITLES.has(title.toLowerCase())
    ? domain
    : title;
}

function maskKeepingNewlines(value: string): string {
  return value.replace(/[^\n]/g, " ");
}

function maskCode(markdown: string): string {
  const withoutFences = markdown.replace(
    /(^|\n)(`{3,}|~{3,})[^\n]*(?:\n[\s\S]*?\n\2[^\n]*(?=\n|$)|[\s\S]*$)/g,
    maskKeepingNewlines,
  );
  // 未闭合反引号会渲染为普通文本，因此这里只遮蔽真正闭合的行内代码。
  return withoutFences.replace(/(`+)[\s\S]*?\1/g, maskKeepingNewlines);
}

/** 从不可信 Assistant Markdown 中提取安全、去重的 HTTP(S) 引用来源。 */
export function extractCitationSources(markdown: string): CitationSource[] {
  const sources = new Map<string, CitationSource>();
  for (const match of maskCode(markdown).matchAll(CITATION_LINK_PATTERN)) {
    const url = normalizeUrl(match[2] ?? "");
    if (url === null) {
      continue;
    }
    const current = sources.get(url);
    if (current !== undefined) {
      sources.set(url, { ...current, count: current.count + 1 });
      continue;
    }
    const domain = domainOf(url);
    sources.set(url, {
      id: url,
      title: normalizeTitle(match[1] ?? "", domain),
      url,
      domain,
      count: 1,
    });
  }
  return [...sources.values()];
}
