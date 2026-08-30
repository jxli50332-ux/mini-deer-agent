// 使用版本化 key，未来迁移存储结构时不会误读旧格式。
export const CURRENT_THREAD_STORAGE_KEY =
  "mini-deer-agent.current-thread-id.v1";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export interface ThreadIdStorage {
  readonly getItem: (key: string) => string | null;
  readonly setItem: (key: string, value: string) => void;
}

export interface CurrentThreadRepository {
  /** 读取设备当前线程；不存在或无效时创建并保存一个新线程 ID。 */
  readonly getOrCreateCurrentThreadId: () => string;
  /** 创建并保存一个不同于当前线程的新线程 ID。 */
  readonly createNewCurrentThreadId: () => string;
  /** 选择并保存服务端已经存在的 Thread ID。 */
  readonly selectCurrentThreadId: (threadId: string) => string;
}

interface CurrentThreadRepositoryOptions {
  readonly storage?: ThreadIdStorage | null;
  readonly createThreadId?: () => string;
}

function normalizeThreadId(value: string): string | null {
  const normalized = value.trim().toLowerCase();
  return UUID_PATTERN.test(normalized) ? normalized : null;
}

function getBrowserStorage(): ThreadIdStorage | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    // 隐私模式或浏览器策略可能禁止访问 localStorage，仓储必须允许页面降级运行。
    return window.localStorage;
  } catch {
    return null;
  }
}

function createBrowserThreadId(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * 创建当前线程仓储。
 * localStorage 只保存设备选择的 thread ID，不保存消息、密钥或授权信息。
 */
export function createCurrentThreadRepository(
  options: CurrentThreadRepositoryOptions = {},
): CurrentThreadRepository {
  const storage =
    options.storage === undefined ? getBrowserStorage() : options.storage;
  const createThreadId = options.createThreadId ?? createBrowserThreadId;
  // 存储不可用时仍在当前 Repository 生命周期内复用同一 ID，避免一次渲染产生多个线程。
  let volatileThreadId: string | null = null;

  function persistThreadId(threadId: string): void {
    if (storage === null) {
      return;
    }

    try {
      storage.setItem(CURRENT_THREAD_STORAGE_KEY, threadId);
    } catch {
      // 写入失败只会失去跨刷新续接能力，当前页面仍可安全使用内存线程。
    }
  }

  function createAndRememberThreadId(previousThreadId: string | null): string {
    const created = normalizeThreadId(createThreadId());
    if (created === null) {
      throw new Error("线程 ID 工厂必须返回 UUID");
    }
    if (created === previousThreadId) {
      throw new Error("新线程 ID 必须与当前线程不同");
    }

    volatileThreadId = created;
    persistThreadId(created);
    return created;
  }

  function getOrCreateCurrentThreadId(): string {
    if (volatileThreadId !== null) {
      return volatileThreadId;
    }

    if (storage !== null) {
      try {
        const stored = storage.getItem(CURRENT_THREAD_STORAGE_KEY);
        const normalizedStored =
          stored === null ? null : normalizeThreadId(stored);
        if (normalizedStored !== null) {
          volatileThreadId = normalizedStored;
          // 统一大小写和首尾空格，使 URL、日志和 Checkpoint 使用同一规范值。
          if (stored !== normalizedStored) {
            persistThreadId(normalizedStored);
          }
          return normalizedStored;
        }
      } catch {
        // 读取失败时继续使用内存线程，不能让浏览器存储策略阻断整个聊天页面。
      }
    }

    return createAndRememberThreadId(null);
  }

  return {
    getOrCreateCurrentThreadId,
    selectCurrentThreadId(threadId: string): string {
      const normalized = normalizeThreadId(threadId);
      if (normalized === null) {
        throw new Error("选择的线程 ID 必须是 UUID");
      }
      volatileThreadId = normalized;
      persistThreadId(normalized);
      return normalized;
    },
    createNewCurrentThreadId(): string {
      // 先确保“当前线程”存在，再拒绝工厂意外返回相同 ID，避免 UI 看似重置却仍串用旧上下文。
      const previousThreadId = getOrCreateCurrentThreadId();
      return createAndRememberThreadId(previousThreadId);
    },
  };
}
