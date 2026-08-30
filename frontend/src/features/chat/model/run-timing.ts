export function elapsedRunSeconds(
  startedAt: string,
  now: number,
): number | null {
  const startedAtMilliseconds = Date.parse(startedAt);
  if (!Number.isFinite(startedAtMilliseconds)) {
    return null;
  }
  return Math.max(0, Math.floor((now - startedAtMilliseconds) / 1_000));
}

export function completedRunSeconds(
  startedAt: string,
  finishedAt: string,
): number | null {
  const startedAtMilliseconds = Date.parse(startedAt);
  const finishedAtMilliseconds = Date.parse(finishedAt);
  if (
    !Number.isFinite(startedAtMilliseconds) ||
    !Number.isFinite(finishedAtMilliseconds)
  ) {
    return null;
  }
  return Math.max(
    0,
    Math.floor((finishedAtMilliseconds - startedAtMilliseconds) / 1_000),
  );
}

export function formatRunDuration(durationSeconds: number): string | null {
  if (
    !Number.isFinite(durationSeconds) ||
    durationSeconds < 0 ||
    !Number.isInteger(durationSeconds)
  ) {
    return null;
  }
  if (durationSeconds === 0) {
    return "少于 1 秒";
  }

  const hours = Math.floor(durationSeconds / 3_600);
  const minutes = Math.floor((durationSeconds % 3_600) / 60);
  const seconds = durationSeconds % 60;
  const parts: string[] = [];
  if (hours > 0) {
    parts.push(`${hours} 小时`);
  }
  if (minutes > 0) {
    parts.push(`${minutes} 分`);
  }
  if (seconds > 0) {
    parts.push(`${seconds} 秒`);
  }
  return parts.join(" ");
}
