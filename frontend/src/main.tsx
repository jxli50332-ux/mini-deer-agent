import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/app/App";

const rootElement = document.getElementById("root");

// 根节点缺失属于部署产物损坏，应立即失败，而不是渲染一个不可诊断的空白页面。
if (rootElement === null) {
  throw new Error("Mini Deer Agent root element was not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
