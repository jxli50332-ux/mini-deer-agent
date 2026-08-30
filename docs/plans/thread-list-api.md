# 最近 Thread 列表 API 设计概要

> 状态：服务端原子功能已实现，并通过自动化检查和用户真实运行验证。

## 可观察目标

访问 `GET /api/v1/threads?limit=20`，可以看到产品数据库中最近活动的 Thread，按
`updated_at` 从新到旧稳定排序。

## 核心功能

1. 从 `application.sqlite` 查询 Thread 产品元数据，不读取 LangGraph checkpoint。
2. 使用 `updated_at DESC, thread_id DESC` 保证相同时间下仍有确定顺序。
3. 复用现有 `ThreadResponse`，支持有上限的 `limit` 查询参数。
4. 保持 Router → Application Service → Repository 的依赖方向。

本原子功能不包含会话标题、搜索、分页游标、前端列表和旧 Thread 切换；这些在服务端
接口通过真实验证后分别实现。

## 主要文件

- `src/mini_deer_agent/application/conversations.py`：增加列表查询用例与仓储契约。
- `src/mini_deer_agent/persistence/conversations.py`：实现稳定排序查询和对应索引迁移。
- `src/mini_deer_agent/server/routers/threads.py`：公开版本化列表接口。
- `tests/test_conversation_persistence.py`：验证仓储排序与数量限制。
- `tests/server/test_app.py`：验证公开 API 契约。

## 技术选型

- FastAPI `GET /api/v1/threads`
- 现有 `ConversationHistoryService` 和 `ConversationRepository`
- SQLite 产品数据库及版本化索引迁移
- 响应继续使用现有 `ThreadResponse[]`

## DeerFlow 对照

DeerFlow 的 `/api/threads/search` 通过独立 Thread metadata store 查询 Thread，并把
checkpoint 与产品列表职责分开。Mini Deer 当前先实现其最小子集：只按最近活动时间
列出产品数据库中的 Thread，为后续前端“最近会话”和 Thread 切换提供可信数据源。

## 实现后验证

1. 先创建或继续两个不同会话，使它们写入产品数据库。
2. 请求 `http://127.0.0.1:8001/api/v1/threads?limit=20`。
3. 预期返回两个 Thread，最近活动的位于第一项，且不会出现仅存在于 checkpoint 的
   内部状态。
