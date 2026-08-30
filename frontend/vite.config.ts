import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  // 读取未暴露给浏览器的开发代理配置；API Key 永远不能放进 Vite 环境变量。
  const environment = loadEnv(mode, process.cwd(), "");
  const backendOrigin =
    environment.MINI_DEER_BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      // 浏览器始终请求同源 /api，开发服务器只在本地把请求转发到 FastAPI。
      proxy: {
        "/api": {
          target: backendOrigin,
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: "127.0.0.1",
      port: 4173,
      strictPort: true,
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
      css: true,
    },
  };
});
