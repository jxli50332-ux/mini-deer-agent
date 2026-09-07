# Mini Deer Agent 工作计划与进度

> 文档状态：当前有效。
>
> 最后更新：2026-09-05。
>
> 本文只记录会频繁变化的实施计划、完成进度、验证状态和近期任务。稳定的项目目标与架构约束见 `PROJECT.md`，已经由用户验证的学习结论见 `LEARNING.md`。
>
> 当前优先级：完整 Coding 闭环与检查结果审阅区均已验收；第 13 阶段进入文档与源码一致性收口。
>
> 最新设计确认：安全与可靠性专项暂不推进。Project Thread 默认以项目根为文件范围；用户在本轮消息明确写出根外绝对文件或目录时，该目标可加入本轮只读范围；未明确时不探索根外路径。

## 状态定义

- **已实现**：源码存在，自动化检查通过，并已完成用户真实运行验证。
- **待验证**：实现和自动化检查已经完成，正在等待用户在真实环境验证。
- **建设中**：已经开始设计或实现，尚未达到可交付验证状态。
- **规划中**：属于正式路线，但尚未进入本轮实施。
- **暂停**：按用户要求保留当前状态，不主动进入下一项工作。

任何规划能力都不能在接口、页面或文档中伪装成已实现能力。

## 当前进度

| 领域             | 状态   | 当前结果                                                                            |
| ---------------- | ------ | ----------------------------------------------------------------------------------- |
| 项目工作区 | 建设中 | Coding 闭环与检查结果已验收；正在完成第 13 阶段文档、状态和源码一致性收口 |
| 配置             | 已实现 | Pydantic Settings、`.env`、SecretStr 和模型配置边界                                 |
| 模型             | 已实现 | 通过 OpenAI-compatible 接口调用 DeepSeek V4 Flash                                   |
| Agent 图         | 已实现 | 主工具循环 + clarification/skill activation/policy block 专用分支 + 并发 delegation 子图 |
| Prompt 工程      | 已实现 | v38 新功能、配套测试与验证交付已完成真实页面验收 |
| Plan mode        | 已实现 | write_todos 规划工具 + 任务清单展示，Prompt 升级 v6（12.2）                              |
| Clarification    | 已实现 | 后端闭环（12.3）+ v1 专用交互（12.4）+ v2 完整七种字段（12.5—12.6）                    |
| Sub-agent        | 已实现 | 12.7—12.8：独立子图、受控工具、每批并发 3 个、每 Run 累计 6 个及取消传播              |
| Skills           | 已实现 | 12.9—12.11：内置发现、显式/自动激活、专用工具与 allowed-tools 双层权限             |
| 动态上下文       | 已实现 | 12.12：主/子 Agent 每次调用注入宿主日期、时间、星期与 UTC 偏移，不落盘             |
| 上下文摘要       | 已实现 | 12.13：主/子 Agent 自动压缩 checkpoint，产品历史保持完整，已完成真实线程验证       |
| Durable Context  | 已实现 | 12.14：委派、技能引用和 Todo 在摘要后确定性续接，且不跨 Run 继承技能权限           |
| 长期 Memory      | 已实现 | 12.15：本地单用户显式 CRUD，跨 Thread/重启持久化，禁止静默自动写入                 |
| MCP              | 已实现 | 12.16：静态可信配置、stdio/HTTP、多服务器隔离发现、状态接口与主图工具注入           |
| 工具             | 已实现 | 主图被动注册内置工具与启动时 MCP 快照；天气 Skill 专用 get_weather                  |
| 网页搜索与引用   | 已实现 | 搜索来源卡、行内引用、来源面板和刷新恢复均已通过真实浏览器验证                      |
| 网页正文读取     | 已实现 | 安全抓取、正文提取、读取卡、引用复用和刷新恢复均已通过真实浏览器验证                |
| 文本附件         | 已实现 | 内联 UTF-8 文本附件及代码/配置类型扩展（11.6）均已通过真实浏览器验证                |
| 历史附件正文     | 已实现 | 历史消息附件可展开查看正文，已通过真实浏览器验证（11.7）                              |
| 中断工具历史     | 已实现 | 模型边界修复 dangling tool calls 和孤儿 ToolMessage                                 |
| Checkpointer     | 已实现 | SQLite 跨进程恢复同一 Thread 的 LangGraph 状态                                      |
| Run 协议         | 已实现 | version、sequence、run ID、thread ID 和稳定消息身份                                 |
| 产品历史         | 已实现 | 独立应用 SQLite 保存 Thread、Run、Message、Tool 和统一时间线                        |
| Web              | 已实现 | React、TypeScript、增量 SSE、事件校验、聊天和刷新恢复                               |
| 对话窗口渲染     | 已实现 | 安全 Markdown、轮次投影、可折叠工具、粘底滚动和复制均已通过真实浏览器验证           |
| 执行过程折叠     | 已实现 | 工具调用与中间回复折叠进「执行过程」，澄清卡与最终回答直接展示（12.17）            |
| 思考过程展示     | 已实现 | 捕获 DeepSeek reasoning_content 并折叠展示，刷新后可恢复（12.18）                 |
| 服务端取消       | 待验证 | 后台异步 Task、幂等取消 API、中断恢复及不响应取消时的 5 秒强制收敛                  |
| Thread 管理      | 已实现 | 刷新续接、新建隔离、历史分页、选择持久化、旧 Thread 切换及多 Thread 并发均已验证    |
| 会话标题         | 已实现 | 首条消息默认标题、PATCH 改名、刷新持久化和失败重试均已通过真实浏览器验证            |
| 会话删除         | 已实现 | 双 SQLite 清理、侧栏确认、失败恢复和当前会话安全切换均已通过真实浏览器验证          |
| SSE 连接保活     | 已实现 | 15 秒注释心跳、业务序号隔离和断开资源清理均已验证                                   |
| SSE 断线感知     | 已实现 | 45 秒字节静默超时、reader 清理和可重试错误提示均已验证                              |
| Run 详情查询     | 已实现 | 复合身份查询、统一安全 404 和真实 API 验证均已完成                                  |
| SSE 断线状态核对 | 已实现 | 自动查询、有限等待和终态收敛已通过检查与真实浏览器验收                              |
| Event Store      | 已实现 | RunEvent 原始 envelope、连续 sequence、SQLite v3 迁移和只读游标 API 已通过真实验证  |
| SSE 事件重放     | 规划中 | Last-Event-ID、活动流追赶和多 Worker 共享流暂缓，遇到真实恢复需求再推进             |
| 认证与多租户     | 规划中 | 当前仍是本地单用户开发边界                                                          |

当前系统已经形成生产架构骨架，但不具备公开部署所需的完整安全性、可靠性和运维能力。

## 最近完成功能点：12.18 展示 CoT（已验证）

- 12.17 前端折叠：`ConversationTurn` 把工具调用与中间回复折叠进「执行过程」，澄清卡与最终回答
  始终直接展示；折叠的是过程噪音，不是交互与交付物。
- 12.18 思考过程捕获：新增 `PatchedChatOpenAI` 捕获 DeepSeek `reasoning_content`（流式/非流式/
  多轮回传），投影为 `reasoning_delta` 事件，经 v8 迁移持久化到 `messages.reasoning`，前端折叠
  展示「思考过程」并支持刷新恢复。
- 顺带修复：子 Agent 递归上限 8 → 20（此前「调研 Rust/Go」子 Agent 触发 `GraphRecursionError`）；
  补充 Agent 执行流日志（Run 生命周期、工具调用、子 Agent）与 logging 配置，便于卡住时定位。
- 自动化结果：后端 `239 passed`；前端 vitest 通过；typecheck / lint / build / `git diff --check`
  通过。
- 用户已在真实浏览器验证思考过程折叠展示与历史恢复，并确认子 Agent 委派正常，回复「已验证」。
- 当前暂停，等待用户指定下一项；下一连续编号是 12.19。工具循环检测和工具输出预算均继续后置。

## 当前实施点

前端对话窗口工程化渲染已经完成：

- Assistant 使用禁用原始 HTML 的安全 Markdown，用户消息保持纯文本。
- 扁平时间线先投影为稳定轮次，再交给专用消息和工具组件渲染。
- 工具调用按状态折叠，JSON 仅格式化展示副本。
- 用户贴近底部时自动跟随；主动上滚后不抢位置，并提供“回到最新”。
- 只有 final 轮次最后一条 Assistant 回答及其代码块开放复制。
- 最终前端检查为 `16 files / 111 passed`，格式、Lint、类型和生产构建全部通过。
- 用户已经在真实浏览器逐项确认功能点 0—5，结论写入 `LEARNING.md`。

用户提出的“显示执行时间”已并入前端对话窗口工程化渲染：运行中从服务端
`run_started.created_at` 实时计时；完成、失败或停止后使用持久化 Run 的
`started_at / finished_at` 定格；刷新和加载更早消息时按 `user_message_id` 恢复到对应轮次。
代码、自动化检查和用户真实浏览器验证均已完成。

服务端 SSE 心跳与前端 SSE 断线感知已完成源码讲解、自动化检查和用户真实验证，
结论分别写入 `LEARNING.md` 功能点 10.1、10.2。

- 可观察目标：响应已经建立后，连续 45 秒没有收到任何 SSE 字节时结束本地流，
  页面显示可重试的连接静默错误，并恢复输入能力。
- 活动定义：业务事件、注释心跳和未闭合的网络 chunk 都会重新开始 45 秒计时；
  不能只在 reducer 收到业务事件时计时。
- 清理边界：超时后取消 `ReadableStream` reader，避免浏览器继续占用连接，并让
  服务端沿现有断开链终止 Run。
- 错误边界：使用稳定 `stream_inactive` 客户端错误；主动 Abort 仍是
  `aborted`，正常 TCP 异常仍是 `network_error`，协议损坏仍是
  `stream_protocol_error`。
- 验证方式：自动化使用短超时模拟静默和心跳恢复；源码讲解后由用户在真实浏览器
  验证错误提示与输入恢复。

功能点 10.3“单条 Run 详情查询接口”已经完成：

- 正式路径：`GET /api/v1/threads/{thread_id}/runs/{run_id}`。
- 成功返回既有 `RunResponse`，事实来自 application SQLite，不读取进程内活动表。
- Application Service 必须校验 Run 属于路径 Thread。
- Run 缺失、Thread/Run 错配统一返回安全 `run_not_found` 404。
- 本功能只提供可查询事实，不接入前端断线后的自动查询。
- 用户已经通过真实 API 验证正常详情、缺失 Run 和 Thread/Run 错配，结论已写入
  `LEARNING.md` 功能点 10.3。

功能点 10.4“前端 SSE 断线后自动核对 Run 状态”已经完成：

- `fetchChatRun()` 对单 Run API 的不可信 JSON、UUID、时间和路径身份进行运行时
  校验。
- `reconcileChatRunAfterDisconnect()` 最多查询 5 次、间隔 250ms，为服务端断开
  清理和终态持久化保留有限竞争窗口；整个核对过程最多 5 秒，超时会中止挂起的
  GET。
- `useChatRun()` 只对 `stream_inactive`、`network_error` 和
  `incomplete_stream` 自动核对，而且必须已经取得响应头中的 Run ID。
- 持久化 `completed/failed/cancelled/interrupted` 通过 reducer 收敛现有页面；
  查询失败或预算结束仍为 `pending/running` 时保留原连接错误。
- 协议错误、主动取消和响应头前失败不会误走状态恢复分支；本功能不伪造 SSE
  事件，也不声称恢复断线期间缺失的正文或工具事件。
- 页面级回归已覆盖默认 SSE 客户端缺终止帧后，经真实默认 Run GET 收敛为完成。
- 前端完整测试：11 files / `85 passed`；ESLint、Prettier、TypeScript typecheck
  和生产 build：通过。
- 真实浏览器 Network 已观察到 SSE `stream` 之后自动发起以 Run ID 命名的详情
  请求；用户确认按本功能通过验收，结论已写入 `LEARNING.md` 功能点 10.4。

## 当前任务顺序

功能点 10.5“RunEvent 持久化与事件查询”已经完成实现、自动化检查和真实验证：

- SQLite v3 新增 `run_events`，以 `(run_id, sequence)` 为主键，并使用
  `(thread_id, run_id, sequence)` 索引服务复合身份游标查询。
- `apply_run_event()` 在同一事务中写入原始 envelope 并更新 Run/Message/Tool
  当前投影；任一侧失败都会整体回滚。
- 单 Run sequence 必须从 1 连续递增；重复、倒序或跳号通过
  `RunEventSequenceError` 失败关闭。
- `RunEventHistoryService` 隔离 Event Store 查询与 HTTP，先执行 Thread/Run
  归属校验，再使用 `after_sequence` 和 `limit` 正序查询。
- 正式 API：`GET /api/v1/threads/{thread_id}/runs/{run_id}/events`。
- 自动化结果：后端 `68 passed`，`compileall` 和空白差异检查通过；当前环境没有
  安装 Ruff，因此未执行 Ruff。
- 真实验证使用 Run `e6139aa3-fb15-4d34-9c64-c2ad8104b7c7`：Event Store 中
  sequence 1 为 `run_started`，sequence 1890 为 `run_completed`，前向游标查询与
  重启后读取均由用户确认通过。

当前任务顺序：

1. 已完成 DeerFlow Event Store、RunJournal、查询 API、StreamBridge 重放边界与
   Mini Deer 当前事件链的源码对照。
2. 已用失败测试驱动迁移、原子写入、sequence 防护、游标查询和重启恢复。
3. 用户已完成事件 API、游标和后端重启后的持久性验证；结论已写入
   `LEARNING.md` 功能点 10.5。
4. 用户调整优先级：功能点 10.6“Last-Event-ID SSE 重放”保留在可靠性待办，
   当前不实施；下一阶段转向能在真实页面直接使用的业务能力。
5. 功能点 11.1“会话标题完整闭环”已通过用户真实浏览器验证，结论已写入
   `LEARNING.md`；用户完成的 11.2“前端对话窗口工程化渲染”保留原编号。
6. 功能点 11.3“会话删除完整闭环”已通过用户真实浏览器验证：服务端共同清理
   checkpoint 与完整业务事实，侧栏提供确认/错误恢复，删除当前会话后安全切到新 Thread。
7. 功能点 11.4“网页搜索与引用展示闭环”已通过用户真实浏览器验证：搜索工具结果显示
   为来源卡，Assistant 回答显示行内引用与去重来源面板，刷新后从持久历史完整恢复。
8. 功能点 11.5“网页正文抓取与深度阅读闭环”已通过用户真实浏览器验证：Agent 能执行
   `web_search → web_fetch → 最终引用回答`，网页读取卡与引用可在刷新后恢复。
9. 功能点 11.6“扩展文本附件支持类型”已通过用户真实浏览器验证：内联文本附件从 4 类
   扩展到代码/配置等 27 个扩展名，历史恢复复用同一媒体类型白名单。
10. 下一业务功能使用连续编号 11.7；继续优先选择用户可直接使用的业务能力，进入实现前
    仍按 A（极简设计）或 B（直接编码）开始。

功能点 11.1 最终结果：

- SQLite v4 为 `threads` 增加可空 `title`；旧 Thread 保持可读，新 Thread 在
  `create_run()` 的同一事务中从首条用户消息生成最多 60 字符的默认标题。
- `PATCH /api/v1/threads/{thread_id}` 通过 Application Service 更新业务标题和
  `updated_at`；空标题、超长标题和额外字段返回 422，不存在的 Thread 返回安全 404。
- 前端 Thread parser 把 `title` 当作不可信服务端字段校验；侧栏优先显示真实标题，
  旧空标题才退回短 UUID。
- 侧栏支持行内改名；只有服务端成功后才替换列表记录，失败时保留输入和编辑状态。
- 自动化结果：后端 `77 passed`；前端 11 files / `89 passed`；TypeScript、ESLint、
  Prettier、生产 build、Python `compileall` 和 `git diff --check` 均通过。
- 用户已验证默认标题、手动改名和刷新持久化，状态由“待验证”更新为“已实现”。

功能点 11.3 最终结果：

- `ThreadLifecycleService` 通过最小端口编排 LangGraph checkpoint 与 application SQLite，
  Router 不直接访问数据库。
- `DELETE /api/v1/threads/{thread_id}` 成功返回 204；缺失返回 404；活动 Run 返回稳定
  `thread_busy` 409，并在触碰任一存储前拒绝删除。
- application SQLite 只删除 Thread 主记录，由既有外键级联清除 Run、Message、Tool、
  时间线与 RunEvent。
- 前端提供二次确认、删除中状态和原地错误恢复；只有 204 后才移除列表记录。
- 删除当前会话成功后复用 `createNewCurrentThreadId()` 切到空白新会话；删除失败保留原
  Thread 与历史。
- 自动化结果：后端 `81 passed`；前端 19 files / `138 passed`；TypeScript、ESLint、
  Prettier、生产 build 和 Python `compileall` 均通过。
- 用户已完成真实浏览器验证，状态由“待验证”更新为“已实现”，结论已写入
  `LEARNING.md` 功能点 11.3。

功能点 11.4 最终结果：

- Prompt 升级为 `mini-deer-agent/system/v2`，要求联网关键事实使用
  `[citation:来源标题](https://来源URL)`，且 URL 必须来自真实 `web_search` 结果。
- 复用既有 `ToolMessage → tool_result → application SQLite` 链路保存原始搜索 JSON，
  复用 Assistant Message 保存引用 Markdown，没有新增数据库表或 SSE 事件。
- 前端只为 `web_search` 解析结构化结果，展示搜索词、可点击标题、域名、摘要与工具错误；
  非法 JSON 或其他工具保持原始文本回退。
- Assistant citation 只接受 HTTP(S)，忽略代码和图片，按 URL 去重并统计使用次数；用户
  消息继续按纯文本展示。
- 刷新后历史 API 返回同一工具 JSON 与 Assistant Markdown，前端重新投影出来源卡、
  行内引用和参考来源面板。
- 自动化结果：后端 `83 passed`；前端 20 files / `146 passed`；TypeScript、ESLint、
  Prettier、生产 build 和 Python `compileall` 均通过。
- 用户已使用真实搜索完成工具卡、回答引用、外链与刷新恢复验证，状态由“待验证”更新为
  “已实现”，结论已写入 `LEARNING.md` 功能点 11.4。

功能点 11.5 最终结果：

- 新增 `web_fetch`，读取用户直接提供或搜索结果返回的精确公开 HTTP(S) URL；注册表按
  `web_search → web_fetch` 顺序同时交给模型与 ToolNode。
- URL 校验拒绝凭据、localhost、`.local`、私网、回环、链路本地、云元数据和不可公开
  路由地址；域名 DNS 解析与每次重定向目标都重新校验。
- HTTP 客户端限制 10 秒超时、5 次重定向、1 MB 下载、12000 字符正文、300 字符标题，
  并拒绝 PDF 与其他二进制响应；异步网络等待可以响应 Run 取消。
- 标准库 HTML 解析器优先提取 `main/article`，过滤脚本、导航和页脚；远端伪系统标签与
  用户输入边界会被中和。Prompt 升级为 `system/v3`，失败结果不得成为引用。
- `web_fetch` 返回稳定 JSON；既有 ToolMessage、SSE、application SQLite 和历史 API
  负责持久化。前端校验后展示网页标题、域名、正文长度、有界摘要和错误。
- 自动化结果：后端 `96 passed`；前端 21 files / `151 passed`；TypeScript、ESLint、
  Prettier、生产 build 和 Python `compileall` 均通过。
- 真实公网冒烟成功读取 `https://example.com/`；用户已完成浏览器中的直接读取、搜索后
  深读、引用与刷新恢复验证，状态由“待验证”更新为“已实现”。

功能点 11.6 最终结果：

- 内联文本附件类型白名单从 `.txt/.md/.json/.csv` 扩展到 `.py/.js/.jsx/.ts/.tsx/.go/
  .java/.c/.h/.cpp/.hpp/.rs/.sql/.sh/.html/.htm/.css/.scss/.yaml/.yml/.xml/.toml`。
- 后端 `_MEDIA_TYPES_BY_EXTENSION` 与前端 `MEDIA_TYPES_BY_EXTENSION` 保持逐项一致，
  服务端继续按扩展名推导 media_type，不信任客户端声明。
- 新增 `isSupportedTextAttachmentMediaType` 类型守卫，历史恢复 `parseTextAttachments`
  复用同一映射，消除第二处硬编码白名单；前端 Composer 的 `accept` 与提示文案同步扩展。
- 自动化结果：后端 `108 passed`；前端 22 files / `156 passed`；TypeScript、ESLint、
  Prettier、生产 build 和 `git diff --check` 均通过。
- 用户已完成真实浏览器验证，状态由“待验证”更新为“已实现”，结论已写入
  `LEARNING.md` 功能点 11.6。

## 实施路线

### 阶段 0：项目基线治理

- 整理 README、启动命令和环境说明。
- 完善 `.gitignore`，排除 IDE、密钥、构建物和运行数据。
- 建立首个 Git 基线提交。
- 维护总设计、工作计划、学习记录和窗口交接文档。

完成条件：全新环境可以按 README 启动，源码和文档进入版本控制。

### 阶段 1：可靠对话内核

- Prompt Builder、SystemMessage 和 Agent 身份。
- Thread 本地选择、新建和切换。
- 正式 Thread、Message 和 Run 查询接口。
- 页面重开后的历史恢复。
- 服务端 Run 取消。
- 失败重试和重新生成。

完成条件：服务重启、页面重开、取消和普通错误不会造成状态不一致。

### 阶段 2：Run 可靠性

- Run Repository 和 Event Store。
- SSE 心跳、断线检测和事件重放。
- 幂等请求和并发控制。
- 超时、重试和错误分类。
- 运行历史与状态查询。

完成条件：短暂网络中断后可以恢复同一 Run，重复请求不会重复修改 Thread。

### 阶段 3：受控工具平台

- Tool Runtime 和权限策略。
- 工具审批、审计、超时和结果限制。
- 搜索、抓取和引用。
- MCP 接入。
- Tool Evals。

完成条件：高权限工具只有在策略允许或用户批准后执行，每次调用可追踪。

### 阶段 4：文件、Artifact 与 Sandbox

- 上传和文件校验。
- Workspace、输出和 Artifact 管理。
- 隔离文件工具和命令执行。
- 资源、网络和秘密策略。

完成条件：Agent 能在隔离环境中产生可下载交付物，不能越权访问宿主资源。

### 阶段 5：上下文与智能能力

- Token 预算和上下文压缩。
- 长期 Memory。
- Skills 渐进加载。
- Session Goal。
- 规划、Sub-Agent 和循环检测。

完成条件：复杂长任务不会因为上下文无限增长失控，委派过程可追踪且有明确终止条件。

### 阶段 6：安全与生产运营

- 认证、授权和多租户隔离。
- PostgreSQL、Redis、队列和迁移。
- 限流、配额和成本控制。
- 日志、Metrics、Trace 和告警。
- Agent Evals、CI、容器化、备份和恢复。

完成条件：通过安全检查、故障演练和部署验收后，才可以称为可公开部署的生产级系统。

## 计划维护规则

1. 每个功能点开始前记录可观察目标、源码对照范围和验证方式。
2. 实现完成但用户尚未验证时只能标记为“待验证”。
3. 用户验证失败时暂停后续计划，优先修复当前功能。
4. 用户验证成功后同步 `LEARNING.md`，再把状态改成“已实现”。
5. 计划优先级或进度改变只更新本文；稳定架构改变才更新 `PROJECT.md`。
6. 窗口切换时同步 `HANDOFF.md`，不要依赖聊天上下文保存工程事实。
