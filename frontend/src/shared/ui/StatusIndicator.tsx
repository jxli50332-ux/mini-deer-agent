interface StatusIndicatorProps {
  readonly label: string;
}

export function StatusIndicator({ label }: StatusIndicatorProps) {
  return (
    <span className="status-indicator" role="status" aria-label={label}>
      {/* 圆点只提供辅助视觉，状态名称由 aria-label 明确提供。 */}
      <span className="status-indicator__dot" aria-hidden="true" />
      {label}
    </span>
  );
}
