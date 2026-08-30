import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CURRENT_THREAD_STORAGE_KEY,
  createCurrentThreadRepository,
  type ThreadIdStorage,
} from "@/entities/thread/model/current-thread-repository";

const STORED_THREAD_ID = "11111111-1111-4111-8111-111111111111";
const CREATED_THREAD_ID = "22222222-2222-4222-8222-222222222222";

function createMemoryStorage(initialValue: string | null): ThreadIdStorage {
  let value = initialValue;
  return {
    getItem: vi.fn((key: string) => {
      expect(key).toBe(CURRENT_THREAD_STORAGE_KEY);
      return value;
    }),
    setItem: vi.fn((key: string, nextValue: string) => {
      expect(key).toBe(CURRENT_THREAD_STORAGE_KEY);
      value = nextValue;
    }),
  };
}

describe("CurrentThreadRepository", () => {
  beforeEach(() => {
    // 每个用例从干净的设备状态开始，避免 localStorage 跨测试泄漏线程身份。
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("默认浏览器仓储在两个实例之间复用同一线程", () => {
    const firstRepository = createCurrentThreadRepository({
      createThreadId: () => CREATED_THREAD_ID,
    });
    expect(firstRepository.getOrCreateCurrentThreadId()).toBe(
      CREATED_THREAD_ID,
    );

    const secondFactory = vi.fn(() => STORED_THREAD_ID);
    const secondRepository = createCurrentThreadRepository({
      createThreadId: secondFactory,
    });
    expect(secondRepository.getOrCreateCurrentThreadId()).toBe(
      CREATED_THREAD_ID,
    );
    expect(secondFactory).not.toHaveBeenCalled();
  });

  it("复用并规范化浏览器中已有的线程 ID", () => {
    const storage = createMemoryStorage(
      `  ${STORED_THREAD_ID.toUpperCase()}  `,
    );
    const createThreadId = vi.fn(() => CREATED_THREAD_ID);
    const repository = createCurrentThreadRepository({
      storage,
      createThreadId,
    });

    expect(repository.getOrCreateCurrentThreadId()).toBe(STORED_THREAD_ID);
    expect(repository.getOrCreateCurrentThreadId()).toBe(STORED_THREAD_ID);
    expect(createThreadId).not.toHaveBeenCalled();
    expect(storage.setItem).toHaveBeenCalledWith(
      CURRENT_THREAD_STORAGE_KEY,
      STORED_THREAD_ID,
    );
  });

  it("替换不可信的已存值并保存新 UUID", () => {
    const storage = createMemoryStorage("../../not-a-thread");
    const repository = createCurrentThreadRepository({
      storage,
      createThreadId: () => CREATED_THREAD_ID,
    });

    expect(repository.getOrCreateCurrentThreadId()).toBe(CREATED_THREAD_ID);
    expect(storage.setItem).toHaveBeenCalledWith(
      CURRENT_THREAD_STORAGE_KEY,
      CREATED_THREAD_ID,
    );
  });

  it("存储被浏览器禁用时在内存中稳定降级", () => {
    const storage: ThreadIdStorage = {
      getItem: vi.fn(() => {
        throw new DOMException("blocked");
      }),
      setItem: vi.fn(() => {
        throw new DOMException("blocked");
      }),
    };
    const createThreadId = vi.fn(() => CREATED_THREAD_ID);
    const repository = createCurrentThreadRepository({
      storage,
      createThreadId,
    });

    expect(repository.getOrCreateCurrentThreadId()).toBe(CREATED_THREAD_ID);
    expect(repository.getOrCreateCurrentThreadId()).toBe(CREATED_THREAD_ID);
    expect(createThreadId).toHaveBeenCalledOnce();
  });

  it("创建新线程并立即替换设备当前线程", () => {
    const storage = createMemoryStorage(STORED_THREAD_ID);
    const repository = createCurrentThreadRepository({
      storage,
      createThreadId: () => CREATED_THREAD_ID,
    });

    expect(repository.getOrCreateCurrentThreadId()).toBe(STORED_THREAD_ID);
    expect(repository.createNewCurrentThreadId()).toBe(CREATED_THREAD_ID);
    expect(repository.getOrCreateCurrentThreadId()).toBe(CREATED_THREAD_ID);
    expect(storage.setItem).toHaveBeenLastCalledWith(
      CURRENT_THREAD_STORAGE_KEY,
      CREATED_THREAD_ID,
    );
  });

  it("选择已有线程时规范化 ID 并立即持久化", () => {
    const storage = createMemoryStorage(STORED_THREAD_ID);
    const repository = createCurrentThreadRepository({ storage });

    expect(
      repository.selectCurrentThreadId(
        `  ${CREATED_THREAD_ID.toUpperCase()}  `,
      ),
    ).toBe(CREATED_THREAD_ID);
    expect(repository.getOrCreateCurrentThreadId()).toBe(CREATED_THREAD_ID);
    expect(storage.setItem).toHaveBeenLastCalledWith(
      CURRENT_THREAD_STORAGE_KEY,
      CREATED_THREAD_ID,
    );
  });

  it("拒绝选择无效 Thread，避免污染历史 API 路径", () => {
    const repository = createCurrentThreadRepository({
      storage: createMemoryStorage(STORED_THREAD_ID),
    });

    expect(() => repository.selectCurrentThreadId("not-a-thread")).toThrow(
      "选择的线程 ID 必须是 UUID",
    );
    expect(repository.getOrCreateCurrentThreadId()).toBe(STORED_THREAD_ID);
  });

  it("拒绝把当前 ID 伪装成新线程", () => {
    const repository = createCurrentThreadRepository({
      storage: createMemoryStorage(STORED_THREAD_ID),
      createThreadId: () => STORED_THREAD_ID,
    });

    expect(() => repository.createNewCurrentThreadId()).toThrow(
      "新线程 ID 必须与当前线程不同",
    );
  });

  it("拒绝无效的 UUID 工厂，避免错误 ID 进入 API 路径", () => {
    const repository = createCurrentThreadRepository({
      storage: null,
      createThreadId: () => "invalid-id",
    });

    expect(() => repository.getOrCreateCurrentThreadId()).toThrow(
      "线程 ID 工厂必须返回 UUID",
    );
  });
});
