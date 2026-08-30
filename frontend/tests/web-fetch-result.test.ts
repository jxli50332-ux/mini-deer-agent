import { describe, expect, it } from "vitest";

import { parseWebFetchResult } from "@/entities/web-page/model/web-fetch-result";

describe("网页读取结果解析", () => {
  it("把可信字段投影为有界网页预览", () => {
    expect(
      parseWebFetchResult(
        JSON.stringify({
          requested_url: "https://example.com/start",
          url: "https://www.example.com/article",
          title: "示例文章",
          content: "a".repeat(700),
          characters: 700,
          truncated: true,
        }),
      ),
    ).toEqual({
      url: "https://www.example.com/article",
      title: "示例文章",
      domain: "example.com",
      excerpt: `${"a".repeat(500)}…`,
      characters: 700,
      truncated: true,
      error: null,
    });
  });

  it("拒绝危险 URL 和伪造字段，并允许稳定错误结果", () => {
    expect(
      parseWebFetchResult(
        JSON.stringify({
          url: "javascript:alert(1)",
          title: "危险",
          content: "正文",
          characters: 2,
          truncated: false,
        }),
      ),
    ).toBeNull();

    expect(
      parseWebFetchResult(
        JSON.stringify({
          requested_url: "http://127.0.0.1/private",
          url: "http://127.0.0.1/private",
          title: "",
          content: "",
          characters: 0,
          truncated: false,
          error: "该地址被网页读取安全策略拒绝。",
        }),
      )?.error,
    ).toBe("该地址被网页读取安全策略拒绝。");
  });
});
