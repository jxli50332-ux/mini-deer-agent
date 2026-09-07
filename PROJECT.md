# Mini Deer Agent 项目总设计

> 文档状态：当前有效。
>
> 本文只维护稳定的项目目标、架构边界和工程规则。工作计划与当前进度保存在 `WORKPLAN.md`，跨窗口恢复信息保存在 `HANDOFF.md`，历史课程设计保存在 `docs/plans/lessons-01-09-archive.md`，学习结论保存在 `LEARNING.md`。当源码与本文不一致时，必须先确认这是实现缺口还是设计已经变更，再同步修改文档。

## 1. 项目定位

Mini Deer Agent 是一个通过对照 DeerFlow 源码逐步构建的生产级 Agent 学习项目。

最终交付物不是只能演示对话和工具调用的 Demo，而是一套可部署、可扩展、可恢复、可观测的 Agent Runtime 与 Web 工作台。项目借鉴 DeerFlow 的核心思想和职责边界，但不机械复制 DeerFlow，也不把 DeerFlow 作为运行依赖。

当前采用渐进式建设：每次只交付一个可以立即运行验证的真实能力，同时把代码放入能够承载长期演进的正式层级。项目规模暂时较小，不构成把所有逻辑塞进单文件或绕过领域边界的理由。

## 2. 双重目标

### 2.1 学习目标

1. 每项能力先定位 DeerFlow 对应源码，理解其调用链和设计原因。
2. Mini Deer 完成实现后，必须在当前对话窗口中结合 DeerFlow 源码和新写的 Mini Deer 源码，讲解职责对应关系、关键代码和完整调用流程。
3. 从模型调用、状态图、工具、持久化和流式协议开始，逐步理解完整 Agent Runtime。
4. 用户完成实际运行、问题讨论并明确确认后，才能把源码解读、运行结果和关键结论写入 `LEARNING.md`。
5. 保留必要的故障排查过程，使学习记录能够解释系统为何这样设计。

### 2.2 工程目标

1. 建立稳定的 Thread、Run、Message、Tool、Artifact 和 Memory 领域边界。
2. 支持可靠的 Agent 运行生命周期，包括流式输出、取消、恢复、重试和事件重放。
3. 建立受权限约束、可审批、可审计的工具运行时和隔离执行环境。
4. 支持 Skills、MCP、上下文工程、长期记忆、Goal 和 Sub-Agent。
5. 具备认证授权、可观测性、评测、数据迁移和生产部署能力。

## 3. 核心质量属性

生产级不是功能数量，而是系统在异常和长期演进中仍然保持正确。所有后续设计必须同时考虑以下属性：

### 3.1 正确性

- 同一 Thread 的消息顺序必须确定。
- 每个 Run、Message 和 Tool Call 使用独立身份，不能通过名称或文本猜测关联关系。
- 事件重复、缺失、乱序或跨 Run 到达时不能破坏前端状态。
- 模型生成内容属于不可信数据，不能作为运行配置、身份或权限依据。

### 3.2 可恢复性

- 服务重启后可以恢复持久化 Thread。
- 网络中断后能够判断 Run 的真实状态。
- 未来通过 Event Store 和 Last-Event-ID 支持有界事件重放。
- 取消、重试和重复提交需要明确的幂等语义。

### 3.3 可扩展性

- HTTP、CLI、定时任务和消息渠道可以复用同一 Application Service。
- 模型提供方、数据库、工具来源和 Sandbox 通过明确适配器替换。
- 新能力进入对应模块，不能持续扩大 `api.py`、单个 graph 或页面组件。

### 3.4 安全性

- 模型密钥只存在于后端。
- Thread ID 不是用户身份，也不是授权凭证。
- 工具参数、模型文本、上传文件和外部 HTTP 响应都按不可信输入处理。
- 任意命令执行必须位于资源受限的 Sandbox 中，并经过权限策略。

### 3.5 可观测性

- Request、Thread、Run、Message 和 Tool Call ID 可以形成完整关联链。
- 日志、指标和 Trace 不记录密钥，并对用户正文采用明确的数据策略。
- 可以观察延迟、Token、费用、工具错误、取消和恢复情况。

## 4. 总体架构

```text
Web / CLI / Scheduled Task / Message Channel
                       │
                       ▼
       API Gateway / Authentication / Authorization
                       │
                       ▼
               Application Services
        ┌──────────────┼──────────────┐
        │              │              │
   Thread Service   Run Service   Artifact Service
        │              │              │
        └──────────────┼──────────────┘
                       ▼
                   Agent Runtime
        ┌──────────────┼──────────────┐
        │              │              │
 Prompt / Context  LangGraph Loop  Tool Runtime
        │              │              │
        └──────────────┼──────────────┘
                       ▼
                  Infrastructure
    LLM Provider / Checkpointer / App DB / Event Store
       Sandbox / Object Storage / Queue / Telemetry
```

依赖方向必须从入口层指向领域与基础设施抽象。基础设施实现不能反向控制 HTTP 或页面组件。

## 5. 后端职责边界

### 5.1 `server`

负责 HTTP 路径、schema、认证上下文、状态码、响应头、中间件和 StreamingResponse。

限制：

- Router 不直接创建模型、LangGraph、数据库连接或外部工具客户端。
- Router 不读取 Checkpointer 内部表结构。
- 错误响应只返回稳定 code 和安全文本，不返回堆栈、数据库路径或密钥。

### 5.2 `application`

负责编排一个完整用例，例如启动 Run、取消 Run、创建 Thread、查询历史或保存 Artifact。

Application Service 不依赖 FastAPI，因此以后可以被 CLI、任务队列和消息渠道复用。

### 5.3 `agents`

负责 Agent 状态、节点、边和运行策略。主 Agent、专用 Agent 和未来 Sub-Agent 必须拥有明确目录，不把所有图塞入同一个模块。

LangGraph 负责执行状态，不负责用户认证、HTTP 序列化或产品线程列表。

### 5.4 `llms`

负责模型提供方适配、模型能力声明、超时、重试和构造参数。

模型工厂不能决定产品提示词。Prompt Builder 根据 Agent 配置、运行上下文和安全策略构建 SystemMessage，然后由 Agent Runtime 调用模型。

### 5.5 `tools`

工具实现、注册信息、运行策略和外部服务适配必须分离：

```text
Tool Definition
    → 名称、描述和参数契约
Tool Runtime
    → 权限、审批、超时、重试、审计和结果限制
Tool Adapter
    → Open-Meteo、搜索服务、MCP 或 Sandbox 的具体请求
```

### 5.6 `persistence`

负责 Checkpointer、业务数据库、Event Store 和迁移适配器。上层只依赖仓储或服务协议，不能把 SQLite SQL 散落到 Router 和 Agent 节点。

### 5.7 `streaming`

负责 Agent 内部消息到 RunEvent、RunEvent 到传输格式的投影。领域事件不能携带 LangChain Python 对象进入浏览器协议。

## 6. 核心领域模型

### 6.1 Principal

表示经过认证的调用主体。即使采用本地单用户部署，公开 Thread 和 Run 操作的接口设计也不能排除未来绑定 Principal。

### 6.2 Thread

表示连续对话和 Agent 上下文的逻辑容器。Thread ID 只负责寻址；所有权、标题、创建时间、更新时间和归档状态属于业务数据。

### 6.3 Message

表示用户、模型、工具或系统产生的对话记录。展示历史和模型上下文可能来自同一事实，但不能假设 Checkpointer 的内部 BLOB 就是稳定的产品消息 API。

### 6.4 Run

表示 Thread 上的一次独立执行，至少包含：

- `run_id`
- `thread_id`
- 生命周期状态
- 开始与结束时间
- 模型和 Agent 配置快照
- 错误或停止原因
- Token、费用和 Trace 关联信息

### 6.5 RunEvent

表示 Run 过程中可排序、可投影的事实。事件必须具有 version、run ID、thread ID 和单调 sequence。

### 6.6 ToolExecution

表示一次具体工具调用，使用 Tool Call ID 与请求和结果关联，并记录审批、耗时、状态和审计信息。

### 6.7 Artifact

表示 Agent 生成或修改的文件、报告、图片、代码和其他交付物。Artifact 需要稳定 ID、媒体类型、存储位置、来源 Run 和访问权限。

## 7. Prompt 与模型身份

System Prompt 必须由正式 Prompt Builder 构建，不能在节点函数中随意拼接字符串。

基础 Prompt 至少包含：

- Agent 产品身份和能力边界。
- 不注入或猜测底层模型提供方；可信模型信息由后端运行元数据承担。
- 工具使用、安全和引用规则。
- 无法确认信息时的行为约束。
- 不得把模型自我介绍当成运行时配置。

页面展示的模型名称必须来自后端运行元数据，而不是询问 LLM。模型回复“我是 Claude”或“我是 ChatGPT”只属于生成文本，不改变实际 provider。

Prompt 必须支持版本号、模板测试和变更追踪，使线上 Run 能追溯到实际使用的 Prompt 版本。

## 8. Run 生命周期

服务端 Run 状态机：

```text
pending
  ├── running
  │     ├── completed
  │     ├── failed
  │     └── interrupted
  └── interrupted
```

前端在取消命令尚未得到服务端终态时使用瞬时 `stopping` 状态；它不是数据库
Run 状态。用户取消、连接断开和服务关闭最终都物化为 `interrupted`，并通过
`finish_reason` 区分原因。

约束：

- 同一 Thread 默认只允许一个会修改对话状态的在途 Run。
- 取消接口必须幂等；重复取消已经结束的 Run 不能破坏状态。
- 浏览器断开连接不能被静默当作成功；当前策略是通过同一取消状态机记录
  `client_disconnected` 原因。
- Run 结束事件必须与持久化最终状态一致。
- 中断可能留下没有对应 ToolMessage 的工具请求，调用模型前必须修复协议视图。
- 重试需要区分重连同一 Run、重放事件和创建新 Run。

## 9. 流式事件协议

正式接口契约：

```http
GET  /api/v1/health
GET  /api/v1/ready
POST /api/v1/threads/{thread_id}/runs/stream
POST /api/v1/threads/{thread_id}/runs/{run_id}/cancel
```

核心事件契约：

- `run_started`
- `ai_delta`
- `tool_call_delta`
- `tool_result`
- `run_error`
- `run_interrupted`
- `run_completed`

演进原则：

- 新增字段优先保持向后兼容。
- 破坏性变更提升协议 version。
- SSE `id` 与 envelope identity 必须一致。
- Event Store 完成前不声明支持 Last-Event-ID。
- 心跳事件不参与业务 sequence，或必须明确独立规则。

未来可能增加 reasoning、citation、approval、artifact 和 usage 事件，但必须先定义领域含义，再接入 UI。

## 10. 持久化策略

持久化分为三类，不能混为一体：

### 10.1 Checkpointer

保存 LangGraph 执行状态，用于恢复上下文和图执行。当前使用 SQLite，适合本地单实例学习和开发。

### 10.2 Application Database

保存 Principal、Thread 元数据、Run、消息索引、权限和 Artifact 元数据。它是产品查询 API 的主要事实来源。

### 10.3 Event Store

保存 RunEvent，用于流式重连、审计和运行恢复。是否与 Application Database 共用物理数据库属于基础设施选择，不改变逻辑边界。

公开部署阶段计划使用 PostgreSQL 和正式迁移体系；Redis 只用于缓存、协调、队列或短期状态，不能成为唯一持久事实来源。

## 11. 前端架构

```text
app
├── 应用入口、全局 Provider 和路由
features
├── chat
├── threads
├── run-control
├── tool-approval
├── uploads
└── artifacts
entities
├── thread
├── run
├── message
└── artifact
shared
├── api
├── config
└── ui
```

原则：

- UI 组件只接收明确 props，不直接解析 SSE 或读取数据库概念。
- API Client 负责 HTTP、AbortSignal 和协议校验。
- Reducer 负责确定性事件归并，不能把流式状态分散成多个布尔变量。
- Thread Repository 管理设备本地线程选择，但不承担服务器授权。
- 模型和工具输出默认以纯文本渲染；Markdown 和引用渲染必须有单独安全策略。
- API Key、服务端密钥和内部错误永远不能进入 Vite 客户端环境。

## 12. 工具与 Sandbox

当前个人本地学习模式不使用工作区密码或连接/锁定流程；页面自动加载本地项目，后端保留回环来源检查与允许目录配置。普通与项目对话后续共用文件能力时沿用该模式，不重新引入手动凭据步骤。公开部署的身份授权要求仍按第 13 节另行建设。

文件工具是 Agent 的通用能力，普通对话与项目对话复用同一套目录浏览、读取、搜索、创建、编辑、移动、重命名和删除工具。Project 提供持久目录身份、默认路径与项目上下文，不是文件工具的使用前提；普通 Thread 始终可使用服务端配置的允许根，并以 `workspace-N` 虚拟路径访问，也不自动改变 Thread 的项目归属。Project Thread 默认以项目根为范围，本轮明确写出的根外绝对路径可成为附加范围。

工具实现与文件访问上下文分离：运行时确定目标文件/目录，模型参数不能自行扩大范围。当前个人学习阶段按用户决定直接修改授信根，安全与可靠性专项后置。已实现文件创建、精确与完整文本更新、目录创建、文件重命名、同一文件范围内移动及单文件删除；目录删除和命令仍按后续原子功能逐项落地。

以下安全与可靠性能力保留为未来公开部署或用户重新启用专项时的建设清单，不阻塞当前本地文件 Coding：

1. 工具权限分类。
2. 参数 schema 和输入限制。
3. 超时、并发和结果大小限制。
4. 用户审批与拒绝流程。
5. Tool Call 审计记录。
6. 独立工作区和 Sandbox 资源限制。
7. 网络访问与秘密注入策略。

禁止把宿主机任意命令执行包装成普通工具后直接交给模型。

## 13. 身份、授权与多租户

本地开发阶段可以运行在单用户模式，但接口和仓储不能把单用户假设写死。

公开部署前必须满足：

- 每个请求具有可信 Principal。
- Thread、Run、Artifact 和 Memory 都有所有权或共享策略。
- 所有查询和修改在服务端验证权限。
- Thread ID 和 Run ID 即使泄露，也不能绕过授权。
- 管理接口和普通用户接口使用不同权限。
- 日志、缓存、文件和数据库查询保持租户隔离。

## 14. 可观测性与评测

### 14.1 日志

- 使用结构化日志。
- 记录 request ID、thread ID、run ID 和 tool call ID。
- 默认不记录密钥、认证令牌和完整用户正文。
- 内部异常进入服务端日志，客户端只接收稳定错误。

### 14.2 指标

至少观测：

- Run 成功率、失败率和取消率。
- 首 Token 延迟和总耗时。
- 模型 Token 与费用。
- 工具耗时、错误和审批情况。
- SSE 断开与重放次数。
- 活跃 Run 和队列深度。

### 14.3 Trace

模型、Agent 节点、工具和外部 HTTP 调用需要处于同一 Trace 链路，并遵守数据脱敏策略。

### 14.4 Evals

单元测试验证代码契约，Agent Evals 验证模型行为。需要建立可重复样本、工具调用正确率、安全拒绝、引用可靠性和回归阈值。

## 15. 测试与质量门槛

### 15.1 后端

- 配置、Prompt、Graph、Tool 和事件投影使用离线单元测试。
- Router 使用注入的假 Application Service 做契约测试。
- SQLite/PostgreSQL 适配器使用集成测试。
- 真实 DeepSeek 和第三方 API 由受控手动验证或独立 Live Test 执行，避免普通测试产生费用。

### 15.2 前端

- 严格 TypeScript。
- ESLint 和 Prettier。
- Parser、事件校验和 Reducer 单元测试。
- Hook 和组件交互测试。
- 关键路径使用可控假后端进行 E2E 测试。
- 真实 Agent 流仍由用户在浏览器验证。

### 15.3 合并门槛

- 自动化测试通过。
- 类型检查、Lint、格式和生产构建通过。
- 关键外部能力由用户实际运行验证。
- 源码注释、设计文档和学习记录与行为一致。

## 16. 部署边界

开发环境：

```text
Browser → Vite Dev Server → /api Proxy → FastAPI → DeepSeek / Tools
```

生产环境：

```text
Browser → TLS Reverse Proxy
             ├── Static Assets
             └── /api → Agent API
                         ├── PostgreSQL
                         ├── Redis / Queue
                         ├── Sandbox Workers
                         └── External Providers
```

生产部署必须具备配置校验、数据库迁移、健康与就绪探针、优雅关闭、在途 Run 处理、备份和回滚方案。

## 17. 明确不采用的做法

- 不把 DeerFlow 整仓复制到本项目。
- 不为了目录看起来完整而创建没有真实实现的空模块。
- 不因为当前用户少就把身份和 Thread ID 混为一体。
- 不通过读取 LangGraph SQLite 内部表直接实现产品 API。
- 不相信 LLM 对自身模型、权限或执行结果的自然语言声明。
- 不在没有 Sandbox 和审批时提供任意宿主命令工具。
- 不在没有真实需求和契约前一次性引入大量框架、组件库和基础设施。
- 不以“测试通过”代替真实浏览器、真实模型和真实外部工具验证。

## 18. 学习与交付流程

学习功能点统一使用 `<课号>.<本课内连续序号>` 编号，例如第 9 课依次使用
`9.1`、`9.2`、`9.3`。新增功能只递增数字，不使用 `A/B/C` 或 `B-1/B-2`
后缀；调整编号时必须同步 `LEARNING.md`、`WORKPLAN.md` 和 `HANDOFF.md` 的引用。
当实施主题跨入新的正式阶段时先建立新课程，再从 `.1` 开始编号；不能为了省事
把不同主题长期追加到旧课程末尾。

每个原子功能点统一采用以下顺序：

1. 明确本次可观察目标和验证方式。
2. 定位并讲解 DeerFlow 对应源码及其设计边界。
3. 说明 Mini Deer 当前调用链、与 DeerFlow 的对应关系和本次需要改变的位置。
4. 编写测试和带中文注释的实现。
5. 执行自动化检查。
6. 在当前对话窗口中结合 DeerFlow 源码和新写的 Mini Deer 源码，讲解实现细节与完整调用流程。
7. 用户在自己的终端或浏览器实际验证，并继续提出不清楚的问题。
8. 修复验证问题或补充源码讲解，直到用户明确确认本功能点没有问题。
9. 只有得到用户确认后，才把本次源码解读、验证结果和关键结论写入 `LEARNING.md`。
10. 再进入下一个原子功能点。

用户运行结果是最终环境事实。自动化检查通过不能跳过当前对话中的源码讲解和用户验证；出现问题时暂停新功能，先定位、修复并重新验证。

## 19. 代码注释约定

该约定适用于后续所有源码和测试：

1. 新增模块、公开类和函数必须有简洁中文说明。
2. 关键流程必须解释职责边界和“为什么这样做”，不能只翻译代码语句。
3. 配置、安全、资源生命周期、并发、错误和异常分支必须添加准确注释。
4. Agent 状态、消息 ID、Run ID、Tool Call ID 和 sequence 的关联规则必须注明。
5. 测试注释必须说明它保护的行为或架构契约。
6. 库名称、协议名称、类型名和代码标识符保留原文。
7. 修改行为时同步更新注释，禁止保留与源码不一致的过期说明。

## 20. 文档治理

- `PROJECT.md`：稳定的项目目标、架构边界和工程规则。
- `WORKPLAN.md`：当前实施计划、进度、验证状态和优先级。
- `HANDOFF.md`：跨窗口继续所需的当前状态、命令、边界和恢复动作。
- `README.md`：安装、配置、启动和日常使用说明。
- `docs/architecture/`：已经落地的架构细节。
- `docs/decisions/`：重要架构决策记录。
- `docs/plans/lessons-01-09-archive.md`：历史阶段设计归档。
- `LEARNING.md`：用户已经验证过的课程和源码学习记录。

稳定设计改变时更新 `PROJECT.md`；计划或进度改变时更新 `WORKPLAN.md`；切换窗口时更新 `HANDOFF.md`；实现完成后更新对应架构文档；用户验证成功后更新学习文档。历史文档只用于追溯，不能覆盖当前设计。
