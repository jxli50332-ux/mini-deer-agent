import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

import {
  formatAttachmentSize,
  prepareSelectedTextAttachments,
  type PreparedTextAttachment,
} from "@/entities/attachment/model/text-attachments";
import type { TodoList } from "@/entities/todo/model/todo-list";
import { TodoPanel } from "@/features/chat/ui/TodoPanel";

interface ComposerProps {
  readonly isActive: boolean;
  readonly isStopping?: boolean;
  readonly disabled?: boolean;
  readonly editorHeight?: number;
  readonly minEditorHeight?: number;
  readonly maxEditorHeight?: number;
  readonly onEditorHeightChange?: (height: number) => void;
  readonly onResetEditorHeight?: () => void;
  readonly todoList?: TodoList | null;
  readonly todoSourceStepId?: string;
  readonly draftInsertion?: {
    readonly id: number;
    readonly text: string;
  } | null;
  readonly onDraftInsertionApplied?: (id: number) => void;
  readonly modelOptions?: readonly {
    readonly name: string;
    readonly displayName: string;
    readonly available: boolean;
  }[];
  readonly selectedModel?: string | null;
  readonly isModelLoading?: boolean;
  readonly isModelSwitching?: boolean;
  readonly modelError?: string | null;
  readonly onModelChange?: (name: string) => void | Promise<void>;
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
  editorHeight = 88,
  minEditorHeight = 64,
  maxEditorHeight = 420,
  onEditorHeightChange = () => undefined,
  onResetEditorHeight = () => undefined,
  todoList = null,
  todoSourceStepId,
  draftInsertion = null,
  onDraftInsertionApplied = () => undefined,
  modelOptions = [],
  selectedModel = null,
  isModelLoading = false,
  isModelSwitching = false,
  modelError = null,
  onModelChange = () => undefined,
  onSubmit,
  onCancel,
}: ComposerProps) {
  const [draft, setDraft] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);
  const lastAppliedInsertionId = useRef<number | null>(null);
  const resizeStart = useRef<{ y: number; height: number } | null>(null);
  const [isResizing, setIsResizing] = useState(false);
  const [attachments, setAttachments] = useState<
    readonly PreparedTextAttachment[]
  >([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [isPreparingAttachments, setIsPreparingAttachments] = useState(false);
  const normalizedDraft = draft.trim();
  const canSubmit =
    !disabled &&
    !isActive &&
    !isModelSwitching &&
    !isPreparingAttachments &&
    normalizedDraft.length > 0;

  useEffect(() => {
    if (
      draftInsertion === null ||
      draftInsertion.id === lastAppliedInsertionId.current
    ) {
      return;
    }
    lastAppliedInsertionId.current = draftInsertion.id;
    setDraft((current) => {
      const separator = current.length === 0 ? "" : "\n\n";
      return `${current}${separator}${draftInsertion.text}`.slice(0, 32_768);
    });
    textarea.current?.focus();
    onDraftInsertionApplied(draftInsertion.id);
  }, [draftInsertion, onDraftInsertionApplied]);

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

  const startResize = (event: PointerEvent<HTMLDivElement>) => {
    resizeStart.current = { y: event.clientY, height: editorHeight };
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsResizing(true);
  };

  const resize = (event: PointerEvent<HTMLDivElement>) => {
    if (resizeStart.current === null) return;
    onEditorHeightChange(
      resizeStart.current.height - (event.clientY - resizeStart.current.y),
    );
  };

  const finishResize = (event: PointerEvent<HTMLDivElement>) => {
    resizeStart.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setIsResizing(false);
  };

  const resizeWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 32 : 8;
    if (event.key === "ArrowUp") onEditorHeightChange(editorHeight + step);
    else if (event.key === "ArrowDown")
      onEditorHeightChange(editorHeight - step);
    else if (event.key === "Home") onEditorHeightChange(minEditorHeight);
    else if (event.key === "End") onEditorHeightChange(maxEditorHeight);
    else return;
    event.preventDefault();
  };

  return (
    <footer className="composer-region">
      {todoList !== null && todoList.items.length > 0 && (
        <TodoPanel
          todoList={todoList}
          {...(todoSourceStepId === undefined
            ? {}
            : { sourceStepId: todoSourceStepId })}
        />
      )}
      <form
        className="composer"
        data-resizing={isResizing}
        aria-label="发送消息"
        aria-busy={isActive}
        onSubmit={handleSubmit}
      >
        <label htmlFor="chat-message">向 Agent 提问</label>
        <div className="composer__toolbar">
          <label className="composer__model-picker">
            <span>模型</span>
            <select
              aria-label="当前模型"
              value={selectedModel ?? ""}
              disabled={
                disabled ||
                isActive ||
                isModelLoading ||
                isModelSwitching ||
                modelOptions.length === 0
              }
              onChange={(event) => void onModelChange(event.target.value)}
            >
              {selectedModel === null && (
                <option value="">
                  {isModelLoading ? "读取中…" : "模型不可用"}
                </option>
              )}
              {modelOptions.map((item) => (
                <option
                  key={item.name}
                  value={item.name}
                  disabled={!item.available}
                >
                  {item.displayName}
                  {item.available ? "" : "（不可用）"}
                </option>
              ))}
            </select>
          </label>
          <div className="composer__attachments">
            <input
              id="chat-attachments"
              className="visually-hidden"
              type="file"
              multiple
              accept=".txt,.md,.json,.csv,.py,.js,.jsx,.ts,.tsx,.html,.htm,.css,.scss,.yaml,.yml,.xml,.toml,.sh,.sql,.go,.java,.c,.h,.cpp,.hpp,.rs"
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
            <span>支持代码、配置等文本文件；最多 3 个</span>
          </div>
        </div>
        {modelError !== null && (
          <p className="composer__model-error">{modelError}</p>
        )}
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
        <div
          className="composer__resize-handle"
          role="separator"
          aria-label="调整输入框高度"
          aria-orientation="horizontal"
          aria-valuemin={minEditorHeight}
          aria-valuemax={maxEditorHeight}
          aria-valuenow={editorHeight}
          tabIndex={0}
          onDoubleClick={onResetEditorHeight}
          onKeyDown={resizeWithKeyboard}
          onPointerDown={startResize}
          onPointerMove={resize}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
        />
        <div className="composer__input-row">
          <textarea
            ref={textarea}
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
