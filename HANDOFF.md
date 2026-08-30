# Mini Deer Agent 新窗口交接

> 交接时间：2026-08-30。
>
> 当前状态：功能点 11.5 网页正文抓取与深度阅读闭环已完成源码对照、测试驱动实现、整库自动化检查和用户真实浏览器验证，学习与计划文档已经收尾。

## 新窗口首先执行

按以下顺序读取文档：

1. `HANDOFF.md`：当前窗口停止位置和恢复动作。
2. `PROJECT.md`：稳定的项目目标、架构边界和工程规则。
3. `WORKPLAN.md`：当前进度和后续路线。
4. `LEARNING.md` 末尾：最近已经由用户验证的功能点 10.1 至 10.5、11.1 至 11.5。

不要从聊天记忆推测项目状态；源码和这些文档才是交接事实。

## 用户协作规则

- 每项能力先在当前对话窗口结合 DeerFlow 与 Mini Deer 源码讲解。
- 所有新增源码和测试都要添加准确的中文注释；库名、协议名和标识符保留英文。
- 自动化检查不能替代用户真实运行验证。
- 只有用户明确确认后，才能把该功能点的源码解读、运行结果和关键结论写入 `LEARNING.md`。
- 出现真实运行问题时暂停新功能，先定位、修复并重新验证。
- 架构按生产级可扩展方向建设，不能因为项目当前较小就把职责塞回单文件。
- 功能点 11.5 已验收；下一功能必须使用连续编号 11.6，并在源码对照前确认具体业务目标。

## 项目与运行环境

- Mini Deer 工作目录：`D:\project\agentstudy\mini-deer-agent`
- DeerFlow 对照源码：`D:\project\agentstudy\deer-flow`
- Python 虚拟环境：`D:\project\agentstudy\mini-deer-agent\.venv`
- 后端地址：`http://127.0.0.1:8001`
- 前端地址：`http://127.0.0.1:5173`
- LangGraph 数据库：`data/checkpoints.sqlite`
- 产品历史数据库：`data/application.sqlite`

后端启动命令：

```powershell
.\.venv\Scripts\python.exe -m uvicorn mini_deer_agent.api:app --host 127.0.0.1 --port 8001
```

前端启动命令：

```powershell
cd D:\project\agentstudy\mini-deer-agent\frontend
npm run dev
```

FastAPI 根路径 `/` 返回 404 属于正常现象，页面由 Vite 的 5173 端口提供。

真实 `.env` 包含 DeepSeek 密钥，不要读取、输出或写入文档。实际运行通过 OpenAI-compatible API 调用 DeepSeek V4 Flash，但 LLM 的自然语言自我介绍不是可信运行证据。

## 已完成并验证的最近能力

### 产品历史与页面恢复

- LangGraph Checkpointer 与产品历史数据库保持职责分离。
- `application.sqlite` 保存 Thread、Run、Message、Tool 和统一时间线。
- 页面刷新后可以恢复历史，并在相同 Thread 继续对话。

### 服务端 Run 取消

- `RunExecutionManager` 使用后台 `asyncio.Task`、`abort_event`、有界事件队列和取消锁。
- 正式取消接口：`POST /api/v1/threads/{thread_id}/runs/{run_id}/cancel`。
- 前端使用 `stopping` 等待可信 `run_interrupted`，不在 204 后提前关闭 SSE。
- 模型、LangGraph、天气 HTTP 和 Checkpointer 的 Web 路径已经异步化。
- 中断后 pending 工具卡会显示“已取消”，同一 Thread 可以继续新 Run。

### 中断工具历史恢复

- 真实测试曾发现：取消工具节点后 checkpoint 保留 8 个 `tool_calls`，但没有对应 `ToolMessage`，后续 DeepSeek 请求失败。
- `agents/middleware/tool_history.py` 在模型边界修复 dangling tool calls、重新排列已有结果并丢弃孤儿结果。
- 修复只影响 model-bound messages，不篡改 checkpoint 或产品历史。

以上内容已经写入 `LEARNING.md` 功能点 9.11、9.12。

## 最近完成并验证的功能：Prompt Builder

用户明确决定：System Prompt 不注入后端当前模型名称。Prompt 只定义 Mini Deer Agent 产品身份、行为、工具和保密边界。底层模型选择仍由 `Settings → create_chat_model()` 控制。

新增源码：

- `src/mini_deer_agent/agents/prompts/contracts.py`
  - `AgentPromptContext`
  - `BuiltAgentPrompt`
  - `AgentPromptBuilder` Protocol
- `src/mini_deer_agent/agents/prompts/templates.py`
  - Prompt 版本：`mini-deer-agent/system/v1`
  - 产品身份、行为、工具和保密模板
- `src/mini_deer_agent/agents/prompts/builder.py`
  - `DefaultAgentPromptBuilder`
  - Agent 名称转义和工具名称校验
- `src/mini_deer_agent/agents/middleware/model_messages.py`
  - 生成一个可信 SystemMessage 位于首位的模型视图
  - 移除 checkpoint 中的旧 SystemMessage，但不修改持久化状态
- `src/mini_deer_agent/agents/main/graph.py`
  - 同步 `model_node` 和异步 `async_model_node` 都注入同一个构建结果
  - Prompt 工具清单强制来自真实工具注册表

关键约束：

- 模板不包含 `deepseek`、`claude` 或 `openai` 等具体底层模型名称。
- SystemMessage 每次模型调用只有一个且位于首位。
- SystemMessage 不写入 LangGraph `MessagesState`，避免跨轮重复。
- Prompt Builder 与模型工厂分离，为未来多 Agent 和 Prompt 版本替换保留接口。
- 工具清单不能相信调用方声明，必须从 `get_agent_tools()` 的实际注册表生成。

新增和更新测试：

- `tests/test_prompts.py`
- `tests/test_agent.py`
- `tests/server/test_runs.py`

最后自动化结果：

```text
后端：63 passed
前端：62 passed
TypeScript typecheck：通过
ESLint：通过
Prettier：通过
生产 build：通过
```

## 真实验证结果

用户已经重启后端并在浏览器确认：

1. “你是谁？”会以 Mini Deer Agent 产品身份回答，不再自称 Claude。
2. “你是什么模型？”不会猜测具体模型名称，并以服务端运行信息或产品界面为准。
3. 北京天气请求仍会真实调用天气工具并生成最终回答。

Prompt Builder 已写入 `LEARNING.md` 功能点 9.13，`WORKPLAN.md` 状态已更新为
“已实现”。用户随后明确开始 Thread 列表功能。

## 最近完成并验证的功能：最近 Thread 服务端列表

已实现：

- `GET /api/v1/threads?limit=20`。
- `ConversationRepository` 与 `ConversationHistoryService` 的列表查询契约。
- `application.sqlite` 按 `updated_at DESC, thread_id DESC` 稳定排序。
- SQLite v2 迁移和 `idx_threads_recent` 索引。
- 后端完整测试：`64 passed`。

真实验证已经访问：

```text
http://127.0.0.1:8001/api/v1/threads?limit=20
```

结果为 `limit=20` 返回两个 Thread，最近活动项位于第一位；`limit=1` 只返回该
首项，两项最终状态均为 `idle`。本功能已经写入 `LEARNING.md` 功能点 9.14。

## 最近完成并验证的功能：前端最近会话列表与 Thread 切换

已实现：

- 校验 `GET /api/v1/threads?limit=20` 的不可信 JSON 响应。
- 侧栏加载、失败重试、当前高亮和无服务端记录的新会话占位。
- 选择已有 Thread 后写入 `localStorage` 并加载目标产品历史。
- 活动 Run 与服务端 `busy` Thread 禁止切换。
- Run 终态刷新列表，Thread 切换清理草稿并拒绝迟到历史响应。
- 前端测试 `70 passed`；typecheck、ESLint、Prettier、生产 build 全部通过。

用户已经在真实浏览器确认：列表展示、旧 Thread 切换、刷新续接、活动 Run 禁止
切换、Run 终态刷新和新 Thread 首轮后入列均正常。本功能已经写入 `LEARNING.md`
功能点 9.15，`WORKPLAN.md` 中 Thread 管理已更新为“已实现”。

前一功能已经收尾；新窗口不要重复实现列表与切换，应直接继续下方心跳验收。

## 最近完成并验证的功能：服务端 SSE 心跳

本轮只实现传输层保活：

- `streaming/sse.py` 的 `aiter_run_sse_frames()` 在连续 15 秒没有 `RunEvent`
  时发送标准 SSE 注释 `: heartbeat`。
- 心跳没有 `id`、`event` 和 `data`，不写入产品数据库，也不占用业务
  `sequence`。
- 等待超时时不取消同一个上游 `anext()` Task；业务事件到达后继续正常发送。
- 客户端关闭输出生成器时取消待处理读取，保留既有 `client_disconnected` 清理链。
- 前端 `SseParser` 已能忽略独立注释心跳，不产生未知业务事件。

自动化结果：后端 `66 passed`；前端 11 files / `71 passed`；ESLint、Prettier、
TypeScript typecheck 和生产 build 全部通过。

用户已按当前窗口步骤完成真实终端验证并明确回复“已验证”。本功能已经写入
`LEARNING.md` 功能点 10.1，`WORKPLAN.md` 的 SSE 连接保活已标为“已实现”。

用户随后选择直接编码“前端 SSE 断线检测与连接异常提示”，当前状态见下节。

## 最近完成并验证的功能：前端 SSE 断线检测与连接异常提示

已实现：

- `parseSseStream()` 可为每次底层 `reader.read()` 设置静默超时；聊天客户端使用
  45 秒，其他 SSE 调用方默认不启用。
- 任意网络字节都会重新开始计时，因此业务帧、注释心跳和未闭合半帧都是连接
  活动；计时不依赖 reducer 是否收到业务事件。
- 超时会取消 response body reader，产生可重试的 `stream_inactive`，并复用现有
  `useChatRun → reducer → ChatPage` 错误卡链路。
- 页面进入 failed、显示“长时间未收到 Agent 心跳或事件，连接可能已经中断”和
  “可以稍后重新发送”，同时恢复输入能力。
- 用户主动 Abort、普通网络异常、协议异常继续使用各自原错误码。

自动化结果：前端 11 files / `74 passed`；ESLint、Prettier、TypeScript typecheck
和生产 build 全部通过。

用户已经通过真实浏览器确认错误提示、可重试说明和输入恢复均符合预期。本功能已
写入 `LEARNING.md` 功能点 10.2，`WORKPLAN.md` 的 SSE 断线感知已标为“已实现”。

本轮没有实现自动重连、Last-Event-ID 或事件重放。下一功能建议先建立可单独验证
的 Run 详情查询接口，为断线后查询服务端真实状态提供正式事实来源。

## 最近完成并验证的功能：单个 Run 详情查询

功能点 10.3 已完成实现、自动化检查和真实 API 验证：

- 新增 `GET /api/v1/threads/{thread_id}/runs/{run_id}`，返回既有
  `RunResponse`。
- `ConversationHistoryService` 复用 application SQLite 的 `get_run(run_id)`，
  并校验记录确实属于路径中的 Thread。
- Run 不存在与 Thread/Run 错配统一返回 `run_not_found` 404，避免泄露另一个
  Thread 中的 Run 是否存在。
- 本轮不接前端断线自动查询，不实现 Event Store、Last-Event-ID 或事件重放。

自动化结果：后端 `66 passed`，定向契约与持久化集成测试 `10 passed`，
`git diff --check` 通过。用户已经验证正常详情、缺失 Run 和 Thread/Run 错配，并
明确要求继续原定计划。结论已写入 `LEARNING.md` 功能点 10.3，`WORKPLAN.md`
状态已改为“已实现”。

下一功能点编号为 10.4：前端在 SSE 连接异常后自动查询 Run 持久化状态，并根据
终态修正页面。它不包含 Event Store、Last-Event-ID 或事件重放；若 Run 仍为活动
状态，需要单独定义有限等待和失败收敛策略。

## 最近完成并验证的功能：SSE 断线后自动核对 Run 状态

功能点 10.4 已完成实现、自动化检查和真实浏览器验收：

- `fetchChatRun()` 调用功能点 10.3 的详情接口，并校验所有公开字段及响应身份。
- `reconcileChatRunAfterDisconnect()` 最多查询 5 次、每次间隔 250ms；终态出现
  后立即返回，预算结束仍活动则返回最后快照；5 秒总预算会中止挂起的详情请求。
- `useChatRun()` 只在已经取得 Run ID 的 `stream_inactive`、`network_error`、
  `incomplete_stream` 后自动核对。
- `completed` 收敛为完成，`failed` 使用持久化 `error_code` 收敛为服务端失败，
  `cancelled/interrupted` 收敛为取消。
- 查询失败或 Run 仍活动时保留原 SSE 错误；主动取消、协议错误和响应头前失败不
  查询。
- 这不是事件重放：断线期间没有抵达前端的正文和工具事件不能由 Run 详情补回。

页面级回归已覆盖默认 SSE 客户端缺终止帧后，经默认 Run GET 收敛为完成。
自动化结果：前端 11 files / `85 passed`；ESLint、Prettier、TypeScript typecheck
和生产 build 全部通过。真实浏览器 Network 已观察到 `stream` 请求之后自动发起
以 Run ID 命名的详情请求；用户最终确认本功能按通过验收。结论已写入
`LEARNING.md` 功能点 10.4，`WORKPLAN.md` 状态已改为“已实现”。

随后已经按连续编号进入功能点 10.5：把每个 `RunEvent` 按
`(run_id, sequence)` 持久化并提供只读查询，但不混入 Last-Event-ID、SSE 重放、
前端自动重连或多 Worker StreamBridge。

## 最近完成并验证的功能：RunEvent 持久化与事件查询

功能点 10.5 已完成实现、自动化检查和真实后端验证：

- application SQLite v3 新增 `run_events` 表，原始 `version/event/run_id/thread_id/
  sequence/message_id/payload` envelope 与写入时间被持久化。
- `(run_id, sequence)` 主键防止同一 Run 的事件身份重复；应用写入还要求 sequence
  从 1 连续递增，跳号、倒序和重复都失败关闭。
- 原始事件写入与既有 Run、Message、Tool 投影位于同一个 SQLite 事务，避免只保存
  其中一侧。
- `RunEventHistoryService` 是独立查询边界；SQLite 虽与 Application Database 共用
  物理文件，Router 不直接接触 SQL 或具体适配器。
- 新增 `GET /api/v1/threads/{thread_id}/runs/{run_id}/events`，支持
  `after_sequence` 前向游标和 `limit`，并复用安全的 Thread/Run 归属 404。
- 测试覆盖完整 envelope、分页、重启后读取、sequence 缺口事务回滚、跨 Thread
  安全 404、OpenAPI 和目标索引查询计划。

自动化结果：后端 `68 passed`；`compileall` 和空白差异检查通过。虚拟环境没有安装
Ruff，因此没有 Ruff 结果。

真实验证使用 Thread `80951da3-4ee8-4a39-bf46-b4436f096ea5`、Run
`e6139aa3-fb15-4d34-9c64-c2ad8104b7c7`：正确 URL 返回 200，sequence 1 为
`run_started`，sequence 1890 为 `run_completed`；用户完成游标与重启持久性验证后
明确回复“已验证继续”。最初两次 422 分别来自把 `{thread_id}` 占位符原样放入路径，
以及把查询参数分隔符 `&` 错写为 `%26`，均不是服务端 Event Store 故障。

结论已写入 `LEARNING.md` 功能点 10.5，`WORKPLAN.md` 状态已改为“已实现”。用户
随后明确调整路线：暂不继续 10.6 Last-Event-ID、活动流追赶或多 Worker 可靠性，
优先推进可见业务功能；这些可靠性能力保留在待办，出现真实恢复问题后再实施。

## 最近完成并验证：11.1 会话标题完整闭环

用户选择 B 直接进入源码对照和编码。实现和自动化检查完成后，用户在真实浏览器验证
默认标题、手动改名与刷新持久化，并明确回复“已验证，继续”。结论已经写入
`LEARNING.md` 11.1，`WORKPLAN.md` 状态已经更新为“已实现”。

已实现：

- `domain/conversations.py` 定义统一标题规范化、60 字符上限与首条消息默认标题。
- application SQLite v4 给 `threads` 增加可空 `title`；`create_run()` 只在创建新
  Thread 时写入默认标题，后续 Run 不会覆盖手动标题。
- `ConversationHistoryService.update_thread_title()` 和
  `PATCH /api/v1/threads/{thread_id}` 形成非 Router-SQL 的改名链路。
- 前端最近 Thread 契约增加 `title`；侧栏显示服务端标题，旧空标题退回短 UUID。
- 侧栏支持行内编辑；失败保留输入并允许重试，成功采用 PATCH 返回的完整 Thread。

自动化结果：后端 `77 passed`；前端 11 files / `89 passed`；TypeScript typecheck、
ESLint、Prettier、生产 build、Python `compileall` 和 `git diff --check` 全部通过。

用户明确说明现有 11.2“前端对话窗口工程化渲染”由用户完成，必须保留其内容与编号。

## 最近完成并验证：11.3 会话删除完整闭环

用户选择 B 直接进入源码对照和编码。实现和自动化检查完成后，用户在真实浏览器验证
删除确认与取消、删除非当前会话、刷新后不恢复、删除当前会话后切到空白新 Thread，
以及活动 Run 期间禁止删除，并明确回复“已验证”。结论已经写入 `LEARNING.md` 11.3，
`WORKPLAN.md` 状态已经更新为“已实现”。

已实现：

- `ThreadLifecycleService` 编排 `checkpoints.sqlite` 与 `application.sqlite`，避免 Router
  直接感知双数据库。
- `DELETE /api/v1/threads/{thread_id}` 提供 204、稳定 404 和 `thread_busy` 409 语义。
- 业务仓储事务内再次拒绝 busy Thread，并通过外键级联清理 Thread、Run、Message、
  ToolExecution、时间线和 RunEvent。
- 前端侧栏提供二次确认、删除中状态和原地错误恢复；仅在服务端 204 后移除列表项。
- 删除当前会话成功后复用 `createNewCurrentThreadId()` 进入新会话，失败时保留原历史。

自动化结果：后端 `81 passed`；前端 19 files / `138 passed`；TypeScript typecheck、
ESLint、Prettier、生产 build 和 Python `compileall` 全部通过。

## 最近完成并验证：11.4 网页搜索与引用展示闭环

用户选择 B 直接进入源码对照和编码。实现和自动化检查完成后，用户使用真实
`web_search` 验证搜索来源卡、Assistant 行内引用、参考来源外链和刷新恢复，并明确回复
“已验证”。结论已经写入 `LEARNING.md` 11.4，`WORKPLAN.md` 状态已经更新为“已实现”。

已实现：

- 默认 Prompt 升级为 `mini-deer-agent/system/v2`，规定联网事实引用格式，并禁止模型
  编造或改写搜索结果 URL。
- `web_search` 继续返回 `query/total_results/results` JSON；既有 projector、SSE、
  application SQLite 和历史 API 原样传输、保存与恢复，不新增 citation 表。
- `parseWebSearchResult()` 校验持久化 JSON 和 HTTP(S) URL；`ToolActivity` 将合法结果
  显示为可点击标题、域名和摘要，非法结果安全回退原始文本。
- `extractCitationSources()` 忽略代码和图片，只提取安全 citation，按 URL 去重并统计；
  `MessageContent` 只为 Assistant 渲染行内来源和折叠来源面板。
- 刷新后使用持久化工具 JSON 与 Assistant Markdown 重新生成相同 UI，不依赖临时状态。

自动化结果：后端 `83 passed`；前端 20 files / `146 passed`；TypeScript typecheck、
ESLint、Prettier、生产 build 和 Python `compileall` 全部通过。

## 最近完成并验证：11.5 网页正文抓取与深度阅读闭环

用户选择 B 直接编码。完成 DeerFlow Jina/Browserless、URL safety、Readability、远端
结果中和与前端 `web_fetch` 步骤对照后，Mini Deer 实现了不依赖第三方抓取服务的公开
静态网页读取。用户完成真实浏览器验证并明确回复“已验证”，结论已写入
`LEARNING.md` 11.5，`WORKPLAN.md` 状态已更新为“已实现”。

已实现：

- `web_fetch` 只接受用户直接提供或 `web_search/web_fetch` 已返回的精确 HTTP(S) URL；
  Prompt v3 禁止猜测地址、执行网页指令或引用失败结果。
- 服务端在创建客户端前解析 URL 与 DNS，拒绝凭据、localhost、私网、回环、链路本地、
  元数据和不可公开路由地址；禁用自动跳转，每次重定向前重新校验目标。
- 同步/异步 httpx 客户端限制超时、跳转、下载字节和上下文字符；异步等待可取消，PDF、
  图片和附件等非网页响应明确拒绝。
- 标准库 HTML 解析器优先使用 `main/article`，过滤脚本、导航和页脚；网页伪造的系统标签
  与输入边界会被中和，但普通事实正文保持可读。
- 工具返回 `requested_url/url/title/content/characters/truncated/error` JSON；既有 SSE、
  SQLite 与历史 API 原样保存，前端安全解析并显示标题、域名、字符数、摘要与错误。
- LangGraph 回归已真实走通 `web_search → web_fetch → citation 回答` 两轮工具循环。

自动化结果：后端 `96 passed`；前端 21 files / `151 passed`；TypeScript typecheck、
ESLint、Prettier、生产 build 和 Python `compileall` 全部通过。独立真实公网冒烟成功读取
`https://example.com/`，标题为 `Example Domain`，正文 129 字符。

下一业务功能必须使用连续编号 11.6。具体内容尚未选定；应继续优先提出用户可直接使用
的业务能力，不能覆盖用户的 11.2，也不要自动回到已经暂缓的可靠性工作。

本功能仍不支持 `Last-Event-ID`、SSE join/replay、StreamGap、前端自动重连和
多 Worker 共享流；这些边界不能因事件已经落库而宣称完成。

## 当前已知边界

- Prompt 版本尚未保存到 Run 产品记录，未来可作为 Run 配置快照的一部分。
- 前端尚未从可信 Run 元数据展示实际模型名称。
- 当前活动 Run 注册表是单进程内存结构，不支持多 Worker 远程取消。
- RunEvent 已能持久化查询，但 SSE 尚无 Last-Event-ID、事件重放和自动重连。
- Thread 尚未绑定认证主体，也没有归档和服务端列表分页；旧数据库迁移前已存在的
  Thread 标题保持为 `null`，可由用户手动改名。
- 项目尚无 README 和首个 Git 基线提交；当前 `git status` 中项目文件仍主要是未跟踪状态。

## 安全提醒

- 不读取或输出 `.env` 中的真实 API Key。
- 不删除 `data/*.sqlite`，除非用户明确要求重置真实历史。
- 不把 LLM 自称的模型身份当成 provider 证据。
- 不把 LangGraph checkpoint BLOB 直接作为产品历史 API。
- 不在没有 Sandbox、审批和权限策略时加入任意宿主命令执行工具。
