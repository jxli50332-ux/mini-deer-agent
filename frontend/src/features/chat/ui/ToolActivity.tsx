import type { ToolTimelineItem } from "@/entities/message/model/types";
import { parseWebSearchResult } from "@/entities/search/model/web-search-result";
import { parseWebFetchResult } from "@/entities/web-page/model/web-fetch-result";

interface ToolActivityProps {
  readonly item: ToolTimelineItem;
}

function formatToolContent(content: string): string {
  const trimmed = content.trim();
  if (!(
    (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
    (trimmed.startsWith("[") && trimmed.endsWith("]"))
  )) {
    return content;
  }

  try {
    // 只格式化展示副本，不修改 reducer 中保存的原始工具内容。
    return JSON.stringify(JSON.parse(trimmed) as unknown, null, 2);
  } catch {
    return content;
  }
}

export function ToolActivity({ item }: ToolActivityProps) {
  const toolName = item.name ?? "工具名称生成中";
  const statusLabel = {
    pending: "调用中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  }[item.status];
  const shouldStartOpen = item.status !== "completed";
  const formattedInput = formatToolContent(item.input);
  const formattedResult =
    item.result === null ? null : formatToolContent(item.result);
  const webSearchResult =
    item.name === "web_search" && item.result !== null
      ? parseWebSearchResult(item.result)
      : null;
  const webFetchResult =
    item.name === "web_fetch" && item.result !== null
      ? parseWebFetchResult(item.result)
      : null;

  return (
    <article
      className="tool-activity"
      role="status"
      aria-label={`工具 ${toolName} ${statusLabel}`}
      data-status={item.status}
    >
      <details className="tool-activity__disclosure" open={shouldStartOpen}>
        <summary className="tool-activity__header">
          <span className="tool-activity__icon" aria-hidden="true">
            T
          </span>
          <span className="tool-activity__title">
            <strong>{toolName}</strong>
            <small>工具活动</small>
          </span>
          <span className="tool-activity__state">{statusLabel}</span>
          <span className="tool-activity__toggle" aria-hidden="true">
            ▾
          </span>
        </summary>
        <div className="tool-activity__body">
          <dl className="tool-activity__details">
            <div>
              <dt>参数</dt>
              <dd>
                {item.input.trim().length > 0 ? (
                  <pre className="tool-activity__content">{formattedInput}</pre>
                ) : (
                  <span className="tool-activity__placeholder">
                    等待模型生成参数……
                  </span>
                )}
              </dd>
            </div>
            <div>
              <dt>结果</dt>
              <dd>
                {formattedResult === null ? (
                  <span className="tool-activity__placeholder">
                    等待工具返回结果……
                  </span>
                ) : webSearchResult !== null ? (
                  <div className="web-search-result">
                    <p className="web-search-result__summary">
                      搜索“{webSearchResult.query}”得到{" "}
                      {webSearchResult.sources.length} 个来源
                    </p>
                    {webSearchResult.error !== null && (
                      <p className="web-search-result__error" role="alert">
                        {webSearchResult.error}
                      </p>
                    )}
                    {webSearchResult.sources.length > 0 && (
                      <ol
                        className="web-search-result__list"
                        aria-label="网页搜索来源"
                      >
                        {webSearchResult.sources.map((source) => (
                          <li key={source.url}>
                            <a
                              href={source.url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              <strong>{source.title}</strong>
                            </a>
                            <span className="web-search-result__domain">
                              {source.domain}
                            </span>
                            {source.content.length > 0 && (
                              <p>{source.content}</p>
                            )}
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                ) : webFetchResult !== null ? (
                  <div className="web-fetch-result">
                    {webFetchResult.error !== null ? (
                      <p className="web-fetch-result__error" role="alert">
                        {webFetchResult.error}
                      </p>
                    ) : (
                      <>
                        <p className="web-fetch-result__summary">
                          已读取 {webFetchResult.domain} ·{" "}
                          {webFetchResult.characters} 个字符
                          {webFetchResult.truncated ? "（已截断）" : ""}
                        </p>
                        <a
                          className="web-fetch-result__link"
                          href={webFetchResult.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {webFetchResult.title}
                        </a>
                        {webFetchResult.excerpt.length > 0 && (
                          <p className="web-fetch-result__excerpt">
                            {webFetchResult.excerpt}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                ) : formattedResult.length > 0 ? (
                  <pre className="tool-activity__content">
                    {formattedResult}
                  </pre>
                ) : (
                  <span className="tool-activity__placeholder">
                    工具返回了空内容
                  </span>
                )}
              </dd>
            </div>
          </dl>
          {/* tool_call_id 是调用与结果的关联键，不把它当作用户可读标题。 */}
          <p className="tool-activity__id">{item.toolCallId}</p>
        </div>
      </details>
    </article>
  );
}
