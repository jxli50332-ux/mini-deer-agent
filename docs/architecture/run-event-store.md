# RunEvent Store

## 已实现边界

Mini Deer 把每条公开 `RunEvent` 的原始 envelope 保存到 application SQLite 的
`run_events` 表。Event Store 与产品历史当前共用一个物理数据库，但通过独立的
`RunEventHistoryService` 应用端口查询，HTTP Router 不依赖 SQLite。

写入链路：

```text
RunExecutionManager
    → SqliteConversationRepository.apply_run_event()
        → 同一事务写入 run_events 原始事实
        → 同一事务更新 Run / Message / Tool 当前投影
    → 事务成功后发布到进程内 SSE 队列
```

`sequence` 在单个 Run 内从 1 连续递增。`(run_id, sequence)` 是事件身份主键，
`(thread_id, run_id, sequence)` 索引服务复合身份查询。

公开查询：

```http
GET /api/v1/threads/{thread_id}/runs/{run_id}/events
    ?after_sequence=0
    &limit=200
```

查询先验证 Run 属于路径 Thread；Run 缺失和归属不匹配返回相同的安全 404。返回结果
严格按 sequence 升序，`after_sequence` 使用排他游标。

## 尚未实现

- `Last-Event-ID` 请求解析。
- 从 Event Store 重新加入或重放 SSE。
- 事件保留期限、裁剪和 `StreamGap`。
- 多 Worker 发布订阅与共享活动 Run。
- Principal 所有权过滤与多租户隔离。

因此 Event Store 查询成功只证明事件事实可持久恢复，不代表网络断线已经可以自动补流。
