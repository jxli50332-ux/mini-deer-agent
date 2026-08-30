# Thread 标题

## 已实现边界

Thread 标题是 Application Database 中的产品元数据，不依赖 LangGraph checkpoint，
也不由浏览器根据消息历史临时猜测。

默认标题写入链路：

```text
POST runs/stream
    → RunExecutionManager
    → SqliteConversationRepository.create_run()
        → 规范化首条用户消息
        → 新建 threads 行并写入 title
        → 同一事务创建 Run 和首条用户消息
```

标题最多 60 个字符。连续空白和换行压成一个空格；超长默认标题截断并使用 `...`
结尾。`INSERT ... ON CONFLICT` 的更新分支不修改 title，因此后续 Run 不会覆盖首轮
标题或用户手动标题。

手动改名使用：

```http
PATCH /api/v1/threads/{thread_id}
Content-Type: application/json

{"title":"新的会话标题"}
```

Router 只处理 UUID、schema、404 和响应映射；标题业务校验位于 Application Service，
SQLite 仓储负责原子更新 `title` 与 `updated_at`。改名不写 checkpoint，所以不需要占用
Agent Run 的 checkpoint 写锁。

前端严格校验列表和 PATCH 响应中的 `title`。侧栏只在服务端 PATCH 成功后替换完整
Thread 记录；失败时保留编辑框、用户输入和错误信息。

## 兼容边界

SQLite v4 使用可空列兼容已有数据库。迁移前已经存在的 Thread 不从后来消息反推标题，
避免错误地把非首轮消息当成首轮；这类 Thread 在侧栏显示短 UUID 回退文案，直到用户
手动改名。

## 尚未实现

- LLM 摘要式标题和独立标题模型配置。
- 标题搜索、归档与列表分页。
- Principal 所有权验证和多租户过滤。
