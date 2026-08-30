import type { CitationSource } from "@/entities/citation/model/citations";

interface CitationSourcesProps {
  readonly sources: readonly CitationSource[];
}

/** 在回答下方展示去重后的来源清单，正文行内引用仍保留原位置。 */
export function CitationSources({ sources }: CitationSourcesProps) {
  if (sources.length === 0) {
    return null;
  }

  return (
    <details className="citation-sources">
      <summary className="citation-sources__summary">
        参考来源（{sources.length}）
      </summary>
      <ol className="citation-sources__list" aria-label="参考来源">
        {sources.map((source) => (
          <li className="citation-sources__item" key={source.id}>
            <a href={source.url} target="_blank" rel="noopener noreferrer">
              <strong>{source.title}</strong>
              <span>{source.domain}</span>
              <span aria-hidden="true">↗</span>
            </a>
            <small>引用 {source.count} 次</small>
          </li>
        ))}
      </ol>
    </details>
  );
}
