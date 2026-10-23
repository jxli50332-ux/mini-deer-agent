import { useState } from "react";
import { MessageContent } from "@/features/chat/ui/MessageContent";

/** Markdown 复用对话中现有的安全渲染；源码始终作为文本节点显示。 */
export function TextDocumentContent({
  content,
  markdown,
}: {
  readonly content: string;
  readonly markdown: boolean;
}) {
  const [source, setSource] = useState(false);
  return (
    <>
      {markdown && (
        <div
          className="text-preview__tabs"
          role="group"
          aria-label="Markdown 显示方式"
        >
          <button
            type="button"
            aria-pressed={!source}
            onClick={() => setSource(false)}
          >
            预览
          </button>
          <button
            type="button"
            aria-pressed={source}
            onClick={() => setSource(true)}
          >
            源码
          </button>
        </div>
      )}
      {content.length === 0 ? (
        <p>这是一个空文件。</p>
      ) : markdown && !source ? (
        <div className="text-preview__markdown">
          <MessageContent role="assistant" content={content} />
        </div>
      ) : (
        <div
          className="text-preview__source"
          tabIndex={0}
          aria-label="文本源码"
        >
          {content
            .replace(/\r\n?/g, "\n")
            .split("\n")
            .map((line, index) => (
              <div className="text-preview__line" key={index}>
                <span aria-hidden="true">{index + 1}</span>
                <code>{line || " "}</code>
              </div>
            ))}
        </div>
      )}
    </>
  );
}
