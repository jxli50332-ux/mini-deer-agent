import { describe, expect, it } from "vitest";

import { extractCitationSources } from "@/entities/citation/model/citations";

describe("Assistant 引用来源提取", () => {
  it("按规范 URL 去重并统计同一来源的多次引用", () => {
    const sources = extractCitationSources(
      "第一处 [citation:示例文档](https://example.com/docs)；" +
        "第二处 [citation:另一个标题](https://example.com/docs)。",
    );

    expect(sources).toEqual([
      {
        id: "https://example.com/docs",
        title: "示例文档",
        url: "https://example.com/docs",
        domain: "example.com",
        count: 2,
      },
    ]);
  });

  it("忽略代码、图片和非 HTTP(S) 链接中的伪引用", () => {
    const sources = extractCitationSources(
      "`[citation:行内代码](https://inline.example)`\n\n" +
        "```md\n[citation:围栏代码](https://fence.example)\n```\n\n" +
        "![citation:图片](https://image.example/a.png)\n\n" +
        "[citation:危险](javascript:alert(1))\n\n" +
        "[citation:真实来源](https://safe.example/article)",
    );

    expect(sources).toHaveLength(1);
    expect(sources[0]).toMatchObject({
      title: "真实来源",
      url: "https://safe.example/article",
      domain: "safe.example",
    });
  });

  it("把空泛来源标题规范化为域名", () => {
    expect(
      extractCitationSources(
        "依据 [citation:来源](https://www.example.com/report)。",
      )[0]?.title,
    ).toBe("example.com");
  });
});
