// 扩展 Vitest 的 DOM 断言，使测试可以表达可访问名称和控件状态。
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// 测试未开启 Vitest 全局 API，因此显式清理每个用例挂载的 React DOM。
afterEach(() => {
  cleanup();
});
