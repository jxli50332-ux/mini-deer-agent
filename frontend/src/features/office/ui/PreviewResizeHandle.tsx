import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

/** 捕获分隔条上的指针，让移出边界、取消拖动和键盘操作使用相同的宽度约束。 */
export function PreviewResizeHandle({
  panelId,
  width,
  minWidth,
  maxWidth,
  onWidthChange,
  onReset,
}: {
  readonly panelId: string;
  readonly width: number;
  readonly minWidth: number;
  readonly maxWidth: number;
  readonly onWidthChange: (width: number) => void;
  readonly onReset: () => void;
}) {
  const start = useRef<{ id: number; x: number; width: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  const finish = (event: PointerEvent<HTMLDivElement>) => {
    if (start.current?.id !== event.pointerId) return;
    start.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const resizeWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 40 : 10;
    // 右侧面板向左扩宽，方向与左侧导航栏相反。
    if (event.key === "ArrowLeft") onWidthChange(width + step);
    else if (event.key === "ArrowRight") onWidthChange(width - step);
    else if (event.key === "Home") onWidthChange(minWidth);
    else if (event.key === "End") onWidthChange(maxWidth);
    else return;
    event.preventDefault();
  };

  return (
    <div
      className="office-panel__resize-handle"
      role="separator"
      aria-label="调整预览宽度"
      aria-orientation="vertical"
      aria-controls={panelId}
      aria-valuemin={minWidth}
      aria-valuemax={maxWidth}
      aria-valuenow={width}
      aria-valuetext={`${width} 像素`}
      title="拖动调整宽度；双击恢复默认；左右方向键微调"
      tabIndex={0}
      data-resizing={dragging}
      onDoubleClick={onReset}
      onKeyDown={resizeWithKeyboard}
      onPointerDown={(event) => {
        if (event.button !== 0 || start.current !== null) return;
        event.preventDefault();
        event.currentTarget.focus();
        event.currentTarget.setPointerCapture(event.pointerId);
        start.current = { id: event.pointerId, x: event.clientX, width };
        setDragging(true);
      }}
      onPointerMove={(event) => {
        if (start.current?.id !== event.pointerId) return;
        onWidthChange(start.current.width + start.current.x - event.clientX);
      }}
      onPointerUp={finish}
      onPointerCancel={finish}
      onLostPointerCapture={() => {
        start.current = null;
        setDragging(false);
      }}
    />
  );
}
