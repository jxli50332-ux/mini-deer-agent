import { ChatPage } from "@/features/chat/ui/ChatPage";

import "@/app/styles.css";

export function App() {
  // 应用入口只负责组合页面；聊天状态和 API 逻辑属于 chat feature。
  return <ChatPage />;
}
