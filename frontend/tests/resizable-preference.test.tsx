import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/features/chat/ui/Composer";
import { clampResizableValue } from "@/shared/model/use-resizable-preference";

describe("可拖拽布局偏好", () => {
  it("对非法值和越界值执行稳定取整与边界约束", () => {
    expect(clampResizableValue(Number.NaN, 240, 480, 280)).toBe(280);
    expect(clampResizableValue(120, 240, 480, 280)).toBe(240);
    expect(clampResizableValue(999, 240, 480, 280)).toBe(480);
    expect(clampResizableValue(301.6, 240, 480, 280)).toBe(302);
  });

  it("输入框分隔条支持键盘调节与双击复位", () => {
    const onEditorHeightChange = vi.fn();
    const onResetEditorHeight = vi.fn();
    render(
      <Composer
        isActive={false}
        editorHeight={88}
        minEditorHeight={64}
        maxEditorHeight={420}
        onEditorHeightChange={onEditorHeightChange}
        onResetEditorHeight={onResetEditorHeight}
        onSubmit={() => Promise.resolve(true)}
        onCancel={() => Promise.resolve(true)}
      />,
    );
    const separator = screen.getByRole("separator", {
      name: "调整输入框高度",
    });
    fireEvent.keyDown(separator, { key: "ArrowUp" });
    expect(onEditorHeightChange).toHaveBeenCalledWith(96);
    fireEvent.doubleClick(separator);
    expect(onResetEditorHeight).toHaveBeenCalledOnce();
  });
});
