import {
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";

import {
  formatAttachmentSize,
  prepareSelectedTextAttachments,
  type PreparedTextAttachment,
} from "@/entities/attachment/model/text-attachments";

interface ComposerProps {
  readonly isActive: boolean;
  readonly isStopping?: boolean;
  readonly disabled?: boolean;
  readonly onSubmit: (
    message: string,
    attachments: readonly PreparedTextAttachment[],
  ) => Promise<boolean>;
  readonly onCancel: () => Promise<boolean>;
}

export function Composer({
  isActive,
  isStopping = false,
  disabled = false,
  onSubmit,
  onCancel,
}: ComposerProps) {
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<
    readonly PreparedTextAttachment[]
  >([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [isPreparingAttachments, setIsPreparingAttachments] = useState(false);
  const normalizedDraft = draft.trim();
  const canSubmit =
    !disabled &&
    !isActive &&
    !isPreparingAttachments &&
    normalizedDraft.length > 0;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }

    // hook 在调用当下同步建立 in-flight guard，因此可以立即清空本地草稿。
    setDraft("");
    setAttachments([]);
    setAttachmentError(null);
    void onSubmit(normalizedDraft, attachments);
  };

  const handleAttachmentSelection = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    // FileList 与 input 是实时绑定的；必须先复制，否则清空 value 会让 files 同步变空。
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    if (files.length === 0) {
      return;
    }

    setAttachmentError(null);
    setIsPreparingAttachments(true);
    try {
      setAttachments(await prepareSelectedTextAttachments(attachments, files));
    } catch (error) {
      setAttachmentError(
        error instanceof Error ? error.message : "无法读取附件",
      );
    } finally {
      setIsPreparingAttachments(false);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  return (
    <footer className="composer-region">
      <form
        className="composer"
        aria-label="发送消息"
        aria-busy={isActive}
        onSubmit={handleSubmit}
      >
        <label htmlFor="chat-message">向 Agent 提问</label>
        <div className="composer__attachments">
          <input
            id="chat-attachments"
            className="visually-hidden"
            type="file"
            multiple
            accept=".txt,.md,.json,.csv,text/plain,text/markdown,application/json,text/csv"
            aria-label="添加文本附件"
            disabled={disabled || isActive || isPreparingAttachments}
            onChange={(event) => void handleAttachmentSelection(event)}
          />
          <label
            className="composer__attachment-button"
            htmlFor="chat-attachments"
            aria-disabled={disabled || isActive || isPreparingAttachments}
          >
            {isPreparingAttachments ? "正在读取…" : "+ 文本附件"}
          </label>
          <span>支持 TXT、Markdown、JSON、CSV；最多 3 个</span>
        </div>
        {attachments.length > 0 && (
          <ul className="composer__attachment-list" aria-label="待发送附件">
            {attachments.map((attachment, index) => (
              <li key={`${attachment.filename}:${index}`}>
                <span>
                  <strong>{attachment.filename}</strong>
                  {formatAttachmentSize(attachment.sizeBytes)}
                </span>
                <button
                  type="button"
                  aria-label={`移除附件 ${attachment.filename}`}
                  disabled={disabled || isActive}
                  onClick={() =>
                    setAttachments((current) =>
                      current.filter((_, itemIndex) => itemIndex !== index),
                    )
                  }
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        {attachmentError !== null && (
          <p className="composer__attachment-error" role="alert">
            {attachmentError}
          </p>
        )}
        <div className="composer__input-row">
          <textarea
            id="chat-message"
            name="message"
            rows={2}
            value={draft}
            maxLength={32_768}
            placeholder="输入消息，Enter 发送，Shift + Enter 换行……"
            aria-describedby="composer-hint"
            disabled={disabled || isActive}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
          />
          {isActive ? (
            <button
              type="button"
              data-action="cancel"
              disabled={disabled || isStopping}
              onClick={() => void onCancel()}
            >
              {isStopping ? "正在停止…" : "停止"}
            </button>
          ) : (
            <button type="submit" data-action="submit" disabled={!canSubmit}>
              发送
            </button>
          )}
        </div>
        <p id="composer-hint">
          {isActive
            ? isStopping
              ? "正在请求服务端终止当前 Run，请稍候。"
              : "Agent 正在生成；停止会终止服务端当前 Run。"
            : "消息通过本地 FastAPI 发送，模型密钥不会进入浏览器。"}
        </p>
      </form>
    </footer>
  );
}
