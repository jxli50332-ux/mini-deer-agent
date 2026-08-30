import { useEffect, useState } from "react";

type CopyStatus = "idle" | "copying" | "copied" | "failed";

interface CopyButtonProps {
  readonly text: string;
  readonly label: string;
  readonly className?: string;
  readonly writeText?: (text: string) => Promise<void>;
}

async function writeClipboardText(text: string): Promise<void> {
  if (
    typeof navigator === "undefined" ||
    navigator.clipboard?.writeText === undefined
  ) {
    throw new Error("Clipboard API unavailable");
  }
  await navigator.clipboard.writeText(text);
}

export function CopyButton({
  text,
  label,
  className,
  writeText = writeClipboardText,
}: CopyButtonProps) {
  const [status, setStatus] = useState<CopyStatus>("idle");

  useEffect(() => {
    if (status !== "copied" && status !== "failed") {
      return;
    }
    const timeoutId = window.setTimeout(() => setStatus("idle"), 2_000);
    return () => window.clearTimeout(timeoutId);
  }, [status]);

  const statusLabel = {
    idle: label,
    copying: "复制中…",
    copied: "已复制",
    failed: "复制失败",
  }[status];

  const handleCopy = async () => {
    if (status === "copying") {
      return;
    }
    setStatus("copying");
    try {
      await writeText(text);
      setStatus("copied");
    } catch {
      // 不把浏览器权限异常暴露到页面；原文仍然保持可选择，用户可以手动复制。
      setStatus("failed");
    }
  };

  return (
    <button
      type="button"
      className={["copy-button", className].filter(Boolean).join(" ")}
      data-copy-status={status}
      disabled={status === "copying"}
      title={status === "failed" ? "复制失败，请手动选择文本" : statusLabel}
      onClick={() => void handleCopy()}
    >
      <span aria-hidden="true">▣</span>
      <span aria-live="polite">{statusLabel}</span>
    </button>
  );
}
