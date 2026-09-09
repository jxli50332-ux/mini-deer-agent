import { useCallback, useEffect, useState } from "react";

interface ResizablePreferenceOptions {
  readonly storageKey: string;
  readonly defaultValue: number;
  readonly minValue: number;
  readonly maxStoredValue?: number;
  readonly getMaxValue: () => number;
}

export function clampResizableValue(
  value: number,
  minValue: number,
  maxValue: number,
  fallback: number,
): number {
  const normalized = Number.isFinite(value) ? value : fallback;
  return Math.round(Math.min(Math.max(normalized, minValue), maxValue));
}

function readStoredValue(options: ResizablePreferenceOptions): number {
  const maxValue = options.maxStoredValue ?? options.getMaxValue();
  try {
    const stored = globalThis.localStorage?.getItem(options.storageKey);
    if (stored !== null && stored !== undefined) {
      return clampResizableValue(
        Number(stored),
        options.minValue,
        maxValue,
        options.defaultValue,
      );
    }
  } catch {
    // 浏览器禁用存储时仍保留可拖拽能力，只是不跨刷新持久化。
  }
  return clampResizableValue(
    options.defaultValue,
    options.minValue,
    maxValue,
    options.defaultValue,
  );
}

export function useResizablePreference(options: ResizablePreferenceOptions) {
  const [preferredValue, setPreferredValue] = useState(() =>
    readStoredValue(options),
  );
  const [, setViewportRevision] = useState(0);
  const value = clampResizableValue(
    preferredValue,
    options.minValue,
    options.getMaxValue(),
    options.defaultValue,
  );

  const setValue = useCallback(
    (nextValue: number) => {
      setPreferredValue(
        clampResizableValue(
          nextValue,
          options.minValue,
          options.getMaxValue(),
          options.defaultValue,
        ),
      );
    },
    [options],
  );

  const reset = useCallback(
    () => setValue(options.defaultValue),
    [options.defaultValue, setValue],
  );

  useEffect(() => {
    try {
      globalThis.localStorage?.setItem(
        options.storageKey,
        String(preferredValue),
      );
    } catch {
      // 与读取一致：存储不可用不应中断布局调整。
    }
  }, [options.storageKey, preferredValue]);

  useEffect(() => {
    const updateViewport = () => setViewportRevision((current) => current + 1);
    globalThis.addEventListener?.("resize", updateViewport);
    return () => globalThis.removeEventListener?.("resize", updateViewport);
  }, []);

  return { value, setValue, reset } as const;
}
