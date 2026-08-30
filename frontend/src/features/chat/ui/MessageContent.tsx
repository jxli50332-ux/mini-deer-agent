import { isValidElement, useMemo, type ReactNode } from "react";
import Markdown, { defaultUrlTransform, type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { extractCitationSources } from "@/entities/citation/model/citations";
import type { MessageRole } from "@/entities/message/model/types";
import { CopyButton } from "@/shared/ui/CopyButton";

import { CitationSources } from "./CitationSources";

interface MessageContentProps {
  readonly role: MessageRole;
  readonly content: string;
  readonly allowCopy?: boolean;
}

function extractText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(extractText).join("");
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return extractText(node.props.children);
  }
  return "";
}

function createMarkdownComponents(allowCopy: boolean): Components {
  return {
    a({ node, href, children, ...props }) {
      // react-markdown 的 AST node 只用于渲染决策，不能透传为 DOM 属性。
      void node;
      const isExternal = href !== undefined && /^https?:\/\//i.test(href);
      const citationMatch = /^citation:\s*(.+)$/i.exec(
        extractText(children).trim(),
      );

      if (isExternal && citationMatch !== null) {
        const domain = new URL(href).hostname.replace(/^www\./i, "");
        const rawTitle = citationMatch[1]?.trim() ?? "";
        const title =
          rawTitle.length === 0 || /^(?:source|来源)$/i.test(rawTitle)
            ? domain
            : rawTitle;
        return (
          <a
            {...props}
            className="citation-link"
            href={href}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span>{title}</span>
            <span aria-hidden="true">↗</span>
          </a>
        );
      }

      return (
        <a
          {...props}
          href={href}
          target={isExternal ? "_blank" : undefined}
          rel={isExternal ? "noopener noreferrer" : undefined}
        >
          {children}
        </a>
      );
    },
    pre({ node, children, ...props }) {
      void node;
      const childClassName = isValidElement<{ className?: string }>(children)
        ? children.props.className
        : undefined;
      const language =
        /(?:^|\s)language-([^\s]+)/.exec(childClassName ?? "")?.[1] ?? "code";
      const code = extractText(children).replace(/\n$/, "");

      return (
        <figure className="markdown-code-block">
          <figcaption className="markdown-code-block__header">
            <span className="markdown-code-block__language">{language}</span>
            {allowCopy && code.length > 0 && (
              <CopyButton
                text={code}
                label="复制代码"
                className="copy-button--code"
              />
            )}
          </figcaption>
          <pre {...props}>{children}</pre>
        </figure>
      );
    },
    img({ node, alt }) {
      void node;
      // 不自动请求模型生成的远程图片，避免对话渲染泄露客户端网络信息。
      return (
        <span className="markdown-image-placeholder">
          [图片：{alt?.trim() || "未命名"}]
        </span>
      );
    },
  };
}

export function MessageContent({
  role,
  content,
  allowCopy = false,
}: MessageContentProps) {
  const markdownComponents = useMemo(
    () => createMarkdownComponents(allowCopy),
    [allowCopy],
  );
  const citationSources = useMemo(
    () => (role === "assistant" ? extractCitationSources(content) : []),
    [content, role],
  );

  if (role === "user") {
    // 用户输入是对话事实，不把 Markdown 或 HTML 重新解释成富文本。
    return (
      <p className="message__content message__content--plain">{content}</p>
    );
  }

  return (
    <div className="message__content message__content--assistant markdown-content">
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={defaultUrlTransform}
        components={markdownComponents}
      >
        {content}
      </Markdown>
      <CitationSources sources={citationSources} />
    </div>
  );
}
