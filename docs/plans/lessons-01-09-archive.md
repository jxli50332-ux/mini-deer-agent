# Mini Deer Agent 第 1～9 课阶段设计归档

> 文档状态：历史归档。
>
> 本文无损合并原有九份阶段设计，用于追溯项目从最小闭环到 Web Agent 架构的演进过程。它不再代表当前项目总设计；新的生产级项目目标将在根目录 `PROJECT.md` 中维护。

## 归档目录

1. 第 1 课：项目骨架与健康检查
2. 第 2 课：配置系统与环境变量
3. 第 3 课：第一次调用大模型
4. 第 4 课：LangGraph 状态图
5. 第 5 课：工具调用与条件循环
6. 第 6 课：Checkpointer 与线程记忆
7. 第 7 课：LangGraph 流式执行
8. 第 8 课：FastAPI 与 SSE 流式聊天接口
9. 第 9 课：可演进的 Web Agent 基础架构

---

## 第 1 课设计概要：项目骨架与健康检查

### 本课目标

建立一个可以立即启动和验证的最小 Python Web 项目。启动服务后，访问 `/health` 应返回：

```json
{"status":"ok"}
```

本课不连接大模型，也不要求 API Key。

### 核心功能

1. 使用 `pyproject.toml` 声明项目和最小运行依赖。
2. 创建 `mini_deer_agent` Python 包和 FastAPI 应用入口。
3. 提供 `GET /health` 健康检查接口。
4. 使用 pytest 验证接口状态码和响应内容。
5. 在学习文档中补充本课原理、代码解读和运行方法。

### 主要文件

```text
mini-deer-agent/
├── pyproject.toml
├── src/mini_deer_agent/
│   ├── __init__.py
│   └── api.py
├── tests/
│   └── test_health.py
└── LEARNING.md
```

### 技术选型

- Python 3.12+
- FastAPI：提供 HTTP 接口
- Uvicorn：本地启动 ASGI 服务
- pytest + FastAPI TestClient：自动验证健康检查接口
- `src` 目录布局：分离项目源码与仓库根目录文件

### 实现顺序与验证

本课拆成两个可独立验证的原子功能点：

1. **项目骨架与应用入口**：安装项目后能够成功导入 FastAPI 应用。
2. **健康检查接口**：自动测试通过，并可在浏览器访问 `/health` 看到预期 JSON。

每完成一个功能点都暂停，由用户实际验证通过后再继续。

### 本课范围外

- 环境变量与模型配置
- 大模型调用
- LangGraph 状态图
- SQLite、流式响应和聊天页面

---

## 第 2 课设计概要：配置系统与环境变量

### 本课目标

建立一个集中、可测试的配置系统，为下一课调用大模型做准备。配置可以由环境变量或本地 `.env` 文件提供，API Key 不会写入源码或提交到 Git。

本课不调用大模型，也不要求真实 API Key。

### 核心功能

1. 使用 Pydantic Settings 定义配置模型和默认值。
2. 支持通过环境变量和 `.env` 覆盖默认配置。
3. 使用秘密类型保存 API Key，避免意外明文输出。
4. 提供不含真实密钥的 `.env.example` 配置模板。
5. 使用 pytest 验证默认值、环境变量覆盖和密钥隐藏行为。

### 主要文件

```text
mini-deer-agent/
├── pyproject.toml
├── .env.example
├── src/mini_deer_agent/
│   └── config.py
├── tests/
│   └── test_config.py
└── LEARNING.md
```

### 技术选型

- `pydantic-settings`：从环境变量和 `.env` 读取并校验配置。
- `SecretStr`：在日志或调试输出中隐藏 API Key。
- pytest `monkeypatch`：在测试内安全模拟环境变量，不修改用户系统配置。

### 原子功能点

1. **配置模型与默认值**：配置对象可以导入，并得到稳定的非敏感默认值。
2. **环境变量与秘密配置**：环境变量可以覆盖默认值，API Key 默认隐藏，并提供 `.env.example`。

每个功能点都遵循“先写失败测试 → 最小实现 → 对照源码讲解 → 用户验证 → 写入学习文档”的顺序。

### 配置边界

首版配置只覆盖下一课真正需要的字段：

- 模型提供方
- 模型名称
- API Key
- 可选的 API Base URL

不会增加数据库、日志、部署或多环境配置，也不会提供可能泄露密钥的 HTTP 配置接口。

---

## 第 3 课设计概要：第一次调用大模型

### 本课目标

把第 2 课的 `Settings` 转换为可调用的 LangChain 聊天模型，并发送一条消息获得模型回复，形成最小的“配置 → 模型 → 响应”闭环。

自动测试不会访问外网，也不需要真实 API Key。只有最后的人工验证会使用用户自己写入 `.env` 的模型配置。

### 核心功能

1. 使用模型工厂集中创建聊天模型，不在业务代码中散落 SDK 参数。
2. 在模型名称或 API Key 缺失时给出清晰错误，不发送无效请求。
3. 支持官方 OpenAI 与 OpenAI 兼容接口，并正确传递可选 Base URL。
4. 提供一次单轮调用入口，输入一条消息并返回模型响应。
5. 使用替身模型完成无网络测试，再由用户执行一次真实调用。

### 主要文件

```text
mini-deer-agent/
├── pyproject.toml
├── .env.example
├── src/mini_deer_agent/
│   ├── config.py
│   └── models.py
├── tests/
│   └── test_models.py
└── LEARNING.md
```

### 技术选型

- `langchain-openai`：使用 `ChatOpenAI` 创建官方 OpenAI 或 OpenAI 兼容聊天模型。
- LangChain `BaseChatModel` / `AIMessage`：为下一课接入 LangGraph 保留统一模型接口和消息类型。
- pytest `monkeypatch`：替换真实模型类，验证构造参数和调用流程而不访问网络。

官方 OpenAI 提供方使用 Responses API；官方文档建议新的文本生成应用优先使用该 API：[OpenAI 文本生成指南](https://developers.openai.com/api/docs/guides/text)。OpenAI 兼容接口默认不强制启用 Responses API，因为第三方网关的支持情况不同。

### 原子功能点

1. **模型配置校验与工厂**：缺少必要配置时清晰失败；配置完整时能够构造聊天模型，全程不发送请求。
2. **第一次单轮调用**：用替身模型验证消息调用，再由用户使用 `.env` 完成一次真实响应。

每个功能点仍遵循“失败测试 → 最小实现 → 对照源码讲解 → 用户验证 → 写入学习文档”。

### 提供方约定

- `MINI_DEER_MODEL_PROVIDER=openai`：使用官方 OpenAI，并启用 Responses API。
- `MINI_DEER_MODEL_PROVIDER=openai-compatible`：使用兼容接口，需要配置 `MINI_DEER_API_BASE_URL`，不假设其支持 Responses API。
- 模型名称始终由 `MINI_DEER_MODEL_NAME` 显式提供，项目不硬编码可能变化的默认模型。

### 本课实际调用目标

用户已选择通过 DeepSeek 官方 API 调用 `deepseek-v4-flash`。公开配置模板固定以下非敏感参数：

```dotenv
MINI_DEER_MODEL_PROVIDER=openai-compatible
MINI_DEER_MODEL_NAME=deepseek-v4-flash
MINI_DEER_API_BASE_URL=https://api.deepseek.com
```

`MINI_DEER_API_KEY` 必须由用户在被 Git 忽略的真实 `.env` 中填写。DeepSeek 官方文档确认该模型使用 OpenAI 兼容的 Chat Completions 接口：[DeepSeek 首次调用 API](https://api-docs.deepseek.com/zh-cn/)。

### 安全与范围边界

- 测试只使用假密钥，不记录或输出真实 API Key。
- 不读取、展示或提交用户的真实 `.env`。
- 本课不加入 LangGraph、工具调用、线程历史、流式输出或 HTTP 聊天接口。
- 不复制 DeerFlow 的动态模型类、思考模式、追踪、重试和多模型配置系统。

### 本课代码注释要求

本课及后续所有新增代码都必须包含学习型注释：

- 模块、类和函数使用简短说明描述职责。
- 配置校验、提供方分支、密钥处理、真实调用边界和测试替身必须用注释解释原因。
- 注释优先使用简洁中文，并在代码行为变化时同步更新。
- 源码讲解会直接检查注释是否能够帮助理解，而不是只检查代码能否运行。

---

## 第 4 课设计概要：LangGraph 状态图

### 本课目标

把已经可用的单轮模型调用放进 LangGraph，理解 Agent 最基础的四个组成部分：状态、节点、边和编译后的可执行图。

本课只建立一条线性路径，不加入工具循环、线程持久化、流式输出或条件分支。

### 核心功能

1. 使用消息列表作为图的共享状态。
2. 创建一个读取状态并返回状态更新的节点。
3. 使用 `START` 和 `END` 连接最小执行路径。
4. 编译图并通过 `.invoke()` 输入、输出消息状态。
5. 将 DeepSeek 聊天模型注入模型节点，完成一次图内回复。

### 主要文件

```text
mini-deer-agent/
├── pyproject.toml
├── src/mini_deer_agent/
│   ├── models.py
│   └── agent.py
├── tests/
│   └── test_agent.py
└── LEARNING.md
```

### 技术选型

- `langgraph>=1.2.9,<1.3`：构建并执行有状态图。
- `MessagesState`：使用 LangGraph 内置的消息状态及消息合并规则。
- `StateGraph`、`START`、`END`：声明节点和有向执行路径。
- LangChain `HumanMessage`、`AIMessage`：保持消息角色与内容类型明确。
- pytest 替身模型：验证图执行但不重复产生真实 API 费用。

官方 Graph API 说明图必须先定义状态，再添加节点和边，最后通过 `compile()` 生成可以调用的图：[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。

### 原子功能点

1. **最小状态图骨架**：使用固定回复节点走通 `START → respond → END`，验证状态和消息合并，不访问模型。
2. **模型节点**：把 `BaseChatModel` 注入图节点，用替身模型测试后，再由用户通过 DeepSeek 完成真实图调用。

每个功能点继续遵循“失败测试 → 带中文注释的最小实现 → 对照源码讲解 → 用户验证 → 写入学习文档”。

### 与 DeerFlow 的关系

当前 DeerFlow 使用 LangChain `create_agent()`、模型工厂、工具和 middleware 组合完整 Agent。`create_agent()` 内部仍建立可执行图，但隐藏了大量底层细节。

本课直接使用 `StateGraph`，目的是先看清：

```text
输入状态
    → 节点读取状态
    → 节点返回部分状态更新
    → LangGraph 合并更新
    → 沿边进入下一节点或 END
```

理解这个最小机制后，下一课增加工具循环时才能明确知道条件边和循环状态解决了什么问题。

### 代码注释要求

- 新增模块、状态、节点和构图函数必须有中文职责说明。
- 注释必须解释消息为什么需要合并、节点为什么只返回部分状态，以及 `compile()` 与执行的边界。
- 测试替身必须注明它避免真实网络请求和费用。
- 注释随图结构变化同步更新，不能保留失效的节点或边说明。

### 本课范围外

- 工具注册、工具调用和条件循环
- SQLite checkpointer 与 thread ID
- SSE、流式事件和 Web 页面
- DeerFlow middleware、子代理和动态模型配置

---

## 第 5 课设计概要：工具调用与条件循环

### 本课目标

在上一课的线性模型图上加入一个本地工具，让 DeepSeek 可以先请求工具、接收工具结果，再生成最终回答，理解最小 Agent 循环。

### 核心功能

1. 使用 `@tool` 定义可直接验证的真实天气查询工具。
2. 使用 `bind_tools()` 把工具说明和参数结构交给聊天模型，并观察 `AIMessage.tool_calls`。
3. 使用 `ToolNode` 执行模型请求的工具，生成与调用 ID 对应的 `ToolMessage`。
4. 使用 `tools_condition` 构建 `model → tools → model` 条件循环；没有工具调用时进入 `END`。
5. 单元测试使用脚本化假模型，最后由用户通过 DeepSeek-V4-Flash 验证完整循环。

### 原子功能点

1. **工具契约**：实现 Open-Meteo 真实天气工具，验证名称、参数 Schema、地理编码和当前天气请求。
2. **模型绑定**：给模型绑定工具，先验证模型可以返回结构化 `tool_calls`，暂不执行工具。
3. **工具循环**：加入 `ToolNode` 和条件边，用假模型走通两次模型调用及一次工具执行，再验证真实 DeepSeek。

每个功能点都遵循“失败测试 → 带中文注释的最小实现 → 对照源码讲解 → 用户验证 → 写入学习文档”，完成后暂停，不连续堆叠下一功能点。

### 主要文件

```text
mini-deer-agent/
├── pyproject.toml
├── src/mini_deer_agent/
│   ├── agent.py
│   └── tools.py
├── tests/
│   ├── test_agent.py
│   └── test_tools.py
└── LEARNING.md
```

### 关键技术选型

- `langchain_core.tools.tool`：把带类型标注和文档字符串的 Python 函数转换为模型可见工具。
- `httpx`：设置有限超时，调用 Open-Meteo 地理编码和当前天气接口。
- `BaseChatModel.bind_tools()`：把工具 Schema 绑定到模型，但不直接执行工具。
- `AIMessage.tool_calls`、`ToolMessage`：分别表达工具请求和工具执行结果，并通过 `tool_call_id` 对应。
- `langgraph.prebuilt.ToolNode`：执行模型请求的一个或多个工具。
- `langgraph.prebuilt.tools_condition`：根据最后一条 AI 消息是否包含工具调用选择 `tools` 或 `END`。

官方文档说明，工具由名称、说明和输入 Schema 组成，模型只产生调用请求；实际执行及结果回传需要工具循环：[LangChain Tools](https://docs.langchain.com/oss/python/langchain/tools)、[LangChain Models](https://docs.langchain.com/oss/python/langchain/models)。

### 最终图结构

```text
START
  → model
      ├─ 有 tool_calls → tools → model
      └─ 无 tool_calls → END
```

### 与 DeerFlow 的关系

DeerFlow 的工具同样通过 `@tool` 声明，并把工具列表交给 `create_agent()`。高层 `create_agent()` 在内部提供模型调用、工具执行和循环路由。

本课直接组合 `StateGraph`、`ToolNode` 和 `tools_condition`，目的是看清 DeerFlow 高层封装背后的最小机制。

### 代码注释要求

- 所有新增模块、函数、节点、路由和测试替身必须有中文职责说明。
- 注释要解释工具 Schema、工具调用 ID、为什么需要第二次模型调用，以及条件边如何终止循环。
- 外部请求必须设置有限超时，并在返回内容中标注 Open-Meteo 数据来源。
- 单元测试必须模拟 HTTP 响应，不能依赖实时服务状态。
- 测试必须注明假模型避免网络请求和 API 费用。

### 本课范围外

- 需要 API Key 的商业天气服务
- 工具异常重试、超时和权限控制
- 并行工具调用与动态工具选择
- Checkpointer、多轮线程和持久化
- SSE 与流式工具事件

---

## 第 6 课设计概要：Checkpointer 与线程记忆

### 本课目标

给现有工具 Agent 注入 Checkpointer，使用 `thread_id` 保存和恢复 `MessagesState`，先理解同一进程内的线程记忆，再升级为 SQLite 跨进程持久化。

### 核心功能

1. 让 `build_agent_graph()` 接收 `BaseCheckpointSaver`，并在 `compile()` 时注入。
2. 使用 `InMemorySaver` 验证同一 `thread_id` 续接消息、不同线程互相隔离。
3. 使用 `graph.get_state()` 查看指定线程的最新消息状态。
4. 使用 `SqliteSaver` 把 checkpoint 写入本地数据库，关闭并重新打开后仍能恢复线程。
5. 通过 DeepSeek-V4-Flash 验证同一线程的真实多轮对话。

### 原子功能点

1. **内存线程状态**：注入 `InMemorySaver`，验证同线程续接、异线程隔离和 `get_state()`；进程结束后数据消失。
2. **SQLite 持久化**：添加 SQLite checkpointer 依赖和资源管理函数，验证重新创建 saver 与 graph 后仍能恢复同一线程。

每个功能点继续遵循“失败测试 → 带中文注释的最小实现 → 对照源码讲解 → 用户验证 → 写入学习文档”，完成后暂停。

### 主要文件

```text
mini-deer-agent/
├── pyproject.toml
├── .gitignore
├── src/mini_deer_agent/
│   ├── agent.py
│   └── storage.py
├── tests/
│   ├── test_agent.py
│   └── test_storage.py
└── LEARNING.md
```

### 关键技术选型

- `BaseCheckpointSaver`：让构图函数依赖统一的 checkpoint 接口，而不是绑定具体存储实现。
- `InMemorySaver`：无需新服务，适合先验证线程语义，但不能跨进程保存。
- `RunnableConfig.configurable.thread_id`：指定本次运行加载和写入哪个线程。
- `graph.get_state(config)`：读取指定线程的最新 `StateSnapshot`。
- `langgraph-checkpoint-sqlite>=3.1.1,<3.2`：使用 `SqliteSaver` 完成本地跨进程持久化。
- context manager：保证 SQLite 连接在 graph 使用期间保持打开，结束后可靠关闭。

官方文档说明 Checkpointer 在图执行步骤保存状态，`thread_id` 是加载与续接 checkpoint 的主键；`InMemorySaver` 随 LangGraph 提供，SQLite saver 需要单独安装：[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)、[LangGraph Memory](https://docs.langchain.com/oss/python/langgraph/add-memory)。

### 线程调用模型

```python
config = {"configurable": {"thread_id": "weather-thread"}}

graph.invoke(
    {"messages": [HumanMessage(content="查询北京天气")]},
    config,
)
graph.invoke(
    {"messages": [HumanMessage(content="那上海呢？")]},
    config,
)
```

第二次只传入本轮新消息。Checkpointer 先加载该线程已有状态，`MessagesState` 再把新消息追加进去；调用方不能重复提交完整历史，否则可能产生重复消息。

```text
相同 thread_id
    → 加载原 checkpoint
    → 合并本轮输入
    → 执行图
    → 保存新 checkpoint

不同 thread_id
    → 从独立空状态开始
```

### 与 DeerFlow 的关系

DeerFlow 的 Agent 工厂同样接收 `BaseCheckpointSaver`，客户端把 `thread_id` 放进 `RunnableConfig.configurable`。运行时根据配置创建 `InMemorySaver`、`SqliteSaver` 或 PostgreSQL saver，并管理连接生命周期。

本课保留最小的两个后端，先看清：

```text
Checkpointer 决定状态存在哪里
thread_id 决定加载哪一份状态
MessagesState 决定消息怎样合并
```

### 代码注释要求

- 所有新增构图参数、存储工厂、连接生命周期和测试替身必须有中文职责说明。
- 注释要解释 `thread_id` 为什么是状态主键、调用方为什么只提交本轮新消息。
- SQLite 代码必须说明连接必须覆盖 graph 调用生命周期，不能在构图后立即关闭。
- 测试必须使用临时数据库路径，不读写正式运行数据。
- SQLite 数据库及 WAL/SHM 临时文件不得提交到 Git。

### 本课范围外

- 长期用户记忆和跨线程共享 Store
- 消息摘要与上下文窗口裁剪
- 删除线程、时间旅行和 checkpoint 分叉
- checkpoint 加密
- 异步 `AsyncSqliteSaver`
- PostgreSQL、多进程写入和生产级并发

---

## 第 7 课设计概要：LangGraph 流式执行

### 本课目标

让现有工具 Agent 不再等整张图执行结束后才返回结果，而是逐步暴露模型消息、工具调用、工具结果和最终回答，并理解节点级更新与模型 token 增量的区别。

### 核心功能

1. 使用 `graph.stream(..., stream_mode="updates")` 观察每个节点完成后的状态增量。
2. 在天气工具循环中依次识别 `model → tools → model`，并保留原始消息类型。
3. 使用 `stream_mode="messages"` 观察模型生成过程中的消息增量，并按消息 ID 累积文本。
4. 验证流式执行与现有 `thread_id`、SQLite Checkpointer 可以同时工作。
5. 对照 DeerFlow 的多模式流式入口，理解 Mini Deer 省略了哪些事件转换和网络传输层。

### 原子功能点

1. **节点级流式更新**：新增最小同步生成器，透传 `updates` 模式；用假模型验证直接回答和天气工具循环的节点顺序，再由用户运行 DeepSeek 真实天气查询。
2. **模型消息增量**：在第一个功能点验证通过后，再学习 `messages` 模式的 chunk、metadata、消息 ID 与文本累积，不与节点级更新混在第一次实现中。

每个功能点继续遵循“失败测试 → 带中文注释的最小实现 → 对照源码讲解 → 用户真实验证 → 写入学习文档”，完成后暂停。

### 主要文件

```text
mini-deer-agent/
├── src/mini_deer_agent/
│   ├── agent.py          # 复用现有 CompiledStateGraph，不改变图结构。
│   └── streaming.py      # 封装最小同步流式入口和事件读取逻辑。
├── tests/
│   └── test_streaming.py # 验证事件顺序、消息类型和惰性迭代。
├── examples/
│   ├── stream_updates_demo.py  # 验证节点级 model → tools → model 更新。
│   └── stream_messages_demo.py # 验证 token 增量、工具参数分片和消息 ID 累积。
├── docs/plans/
│   └── 2026-08-25-lesson-07-langgraph-streaming.md
└── LEARNING.md           # 用户验证后再记录学习结论。
```

### 关键技术选型

- `CompiledStateGraph.stream()`：同步迭代 LangGraph 执行事件，适合当前 PowerShell 学习命令。
- `stream_mode="updates"`：每个节点结束后只返回该节点写入的状态增量，最容易看清 Agent 循环。
- `stream_mode="messages"`：返回模型消息 chunk 和调用 metadata，用于观察 token 级输出。
- Python generator：调用方每次迭代才继续驱动图执行，避免先收集完整结果再伪装成流式输出。
- 原始 LangChain 消息类型：直接识别 `AIMessage`、`AIMessageChunk` 和 `ToolMessage`，不把工具请求压成普通字符串。
- Python 示例文件：让 PowerShell 只传递文件路径，不再通过 `-c` 传递带引号的多行源码。

### 两种流式粒度

```text
updates 模式
    model 节点完成 → 返回带 tool_calls 的 AIMessage
    tools 节点完成 → 返回 ToolMessage
    model 节点完成 → 返回最终 AIMessage

messages 模式
    模型生成 token/chunk → 立即返回 AIMessageChunk
    调用方按消息 ID 累积 content → 得到完整回答
```

第一个功能点只实现并验证 `updates`，因为它可以独立展示完整工具循环。确认无误后再加入 `messages`，避免同时处理节点事件、token 拼接和重复消息去重。

### 预期调用模型

```python
## graph 仍由现有构图函数创建，流式能力来自编译后的 LangGraph 图。
graph = build_agent_graph()

## 生成器逐步返回节点更新；不能先转换成 list 再向终端逐条打印。
for update in stream_agent_updates(
    graph,
    [HumanMessage(content="请查询北京当前天气")],
):
    print(update)
```

天气工具请求的预期节点顺序是：

```text
model
    → AIMessage.tool_calls 包含 get_weather
tools
    → ToolMessage 包含 Open-Meteo 查询结果
model
    → AIMessage 包含最终自然语言回答
```

不需要工具时，预期只有一个节点更新：

```text
model
    → AIMessage 包含直接回答
```

### 与 Checkpointer 的关系

流式执行只改变调用方何时看到事件，不改变图状态和 checkpoint 语义：

```text
相同 thread_id
    → 加载已有 checkpoint
    → 流式执行各节点
    → 每个图步骤继续保存 checkpoint
    → 下次调用仍可恢复完整消息历史
```

因此，`config={"configurable": {"thread_id": "..."}}` 仍要原样传给 `graph.stream()`。SQLite saver 也必须在 `with open_sqlite_checkpointer(...)` 生命周期内完成整个迭代。

### 与 DeerFlow 源码的对应关系

DeerFlow 的同步客户端在 `backend/packages/harness/deerflow/client.py` 中直接调用：

```python
## DeerFlow 同时订阅完整状态、消息增量和自定义事件。
for item in self._agent.stream(
    state,
    config=config,
    context=context,
    stream_mode=["values", "messages", "custom"],
):
    ...
```

它随后把 LangGraph 原始事件转换为 `values`、`messages-tuple`、`custom` 和 `end` 等客户端事件，并处理消息去重、token 用量和工具结果。Gateway 则使用异步 `agent.astream()`，再通过队列和 SSE 发给远程客户端。

Mini Deer 本课只保留最小学习链路：

```text
CompiledStateGraph.stream()
    → Python iterator
    → 终端直接观察原始节点或消息事件
```

这样可以先看清 LangGraph 的原始流式语义，再学习 DeerFlow 为什么需要额外的事件协议层。

### 代码注释要求

- 所有新增生成器、事件解析分支和测试替身必须有中文职责说明。
- 注释要解释生成器为什么必须边迭代边执行，不能预先收集全部结果。
- `updates` 与 `messages` 的返回形状必须分别说明，不能把两者混为一种事件。
- 工具调用、工具结果和最终回答的类型判断必须说明消息之间的关联关系。
- Checkpointer 示例必须说明流迭代不能离开 SQLite saver 的上下文生命周期。

### 本课范围外

- FastAPI、SSE 和 WebSocket 网络传输
- 异步 `astream()` 与异步 SQLite saver
- DeerFlow 的 `StreamBridge`、心跳、断线重放和多订阅者广播
- 自定义 `custom` 事件
- `debug`、`tasks`、`checkpoints` 等高级 stream mode
- 前端逐字渲染和 Markdown 增量解析

---

## 第 8 课设计概要：FastAPI 与 SSE 流式聊天接口

### 本课目标

把第 7 课的 Python 消息生成器接入 FastAPI，通过标准 SSE 帧向 HTTP 客户端逐步发送模型正文、工具调用、工具结果和结束事件，并在最后接回 SQLite 线程状态。

### 核心功能

1. 定义最小 SSE 事件协议，把 Agent 消息转换成 UTF-8 JSON 帧。
2. 增加 `POST /chat/stream`，使用 `StreamingResponse` 边迭代边发送事件。
3. 使用请求模型校验 `message` 和 `thread_id`，避免把无效输入带入流式执行。
4. 返回 `text/event-stream` 及禁止缓存、禁止代理缓冲的响应头。
5. 最后接入 SQLite Checkpointer，验证相同 `thread_id` 能通过两次 HTTP 请求续接历史。

### 原子功能点

1. **SSE 帧编码器**：实现纯函数和消息事件转换器，不启动 FastAPI、不访问 DeepSeek；测试并直接观察 `ai_delta`、`tool_call_chunk`、`tool_result`、`end` 的文本格式。
2. **HTTP 流式端点**：把编码器接入 `StreamingResponse`；测试使用假消息流，用户再通过 Uvicorn 和 `curl.exe -N` 验证真实 DeepSeek 事件逐步抵达。
3. **HTTP 线程持久化**：让请求携带 `thread_id`，在整个响应迭代期间保持 SQLite saver 打开；通过两次独立 HTTP 请求验证历史恢复。

每个功能点继续遵循“失败测试 → 带中文注释的最小实现 → 对照源码讲解 → 用户真实验证 → 写入学习文档”，完成后暂停。

### 主要文件

```text
mini-deer-agent/
├── src/mini_deer_agent/
│   ├── api.py       # 请求模型、依赖组装和 StreamingResponse 路由。
│   ├── sse.py       # Agent 消息到 SSE 文本帧的纯转换逻辑。
│   ├── streaming.py # 复用现有 stream_agent_messages()。
│   └── storage.py   # 第三个功能点复用 SQLite saver 生命周期。
├── tests/
│   ├── test_sse.py         # 验证协议帧和消息类型映射。
│   └── test_chat_stream.py # 验证 HTTP 状态、响应头和事件顺序。
├── examples/
│   ├── sse_frames_demo.py     # 不访问外部服务，直接展示原始 SSE 文本帧。
│   ├── chat_stream_request.json # 让 curl 从文件读取天气请求 JSON。
│   ├── chat_memory_round_1.json # HTTP 线程记忆第一轮请求。
│   └── chat_memory_round_2.json # 使用相同 thread_id 的第二轮请求。
└── LEARNING.md             # 用户验证后记录学习结论。
```

### 关键技术选型

- `fastapi.responses.StreamingResponse`：直接消费同步生成器，不预先构造完整响应体。
- SSE：基于普通 HTTP 的单向文本事件流，当前浏览器聊天输出不需要 WebSocket 双向连接。
- `json.dumps(..., ensure_ascii=False)`：保留中文内容，并保证每个 `data:` 字段是合法单行 JSON。
- `media_type="text/event-stream"`：告诉客户端按 SSE 协议解释响应。
- `Cache-Control: no-cache`：避免中间缓存延迟事件交付。
- `X-Accel-Buffering: no`：提示 Nginx 等代理不要积攒完整响应后再发送。
- 同步 generator：与当前 `graph.stream()`、`SqliteSaver` 和 FastAPI 线程池边界保持一致；异步链路以后单独学习。

### 最小 SSE 帧协议

每个事件由 `event:`、`data:` 和一个空行组成：

```text
event: ai_delta
data: {"id":"message-1","content":"北京","node":"model"}

```

末尾的空行不能省略，它表示一帧结束。当前协议包含：

| 事件名 | 数据 | 作用 |
| --- | --- | --- |
| `ai_delta` | 消息 ID、正文增量、节点名 | 前端追加模型正文 |
| `tool_call_chunk` | 消息 ID、工具调用参数增量 | 展示模型正在组织工具请求 |
| `tool_result` | 工具名、调用 ID、结果正文 | 展示完整工具执行结果 |
| `error` | 稳定错误说明 | HTTP 响应开始后通过事件报告运行错误 |
| `end` | 空对象 | 明确通知客户端本次流结束 |

编码器只接收 Python 数据并返回字符串，不创建 graph、不读取环境变量，也不访问网络，因此可以独立测试。

### 消息到 SSE 的映射

```text
AIMessageChunk.text 非空
    → event: ai_delta

AIMessageChunk.tool_call_chunks 非空
    → event: tool_call_chunk

ToolMessage
    → event: tool_result

生成器正常结束
    → event: end
```

同一个 `AIMessageChunk` 可能同时携带正文和工具调用字段，转换器应分别发送对应事件，不能使用互斥分支丢失数据。

### 预期 HTTP 接口

请求：

```http
POST /chat/stream
Content-Type: application/json

{
  "message": "请查询北京当前天气",
  "thread_id": "weather-http-demo"
}
```

响应头：

```text
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no
```

响应体逐步抵达：

```text
event: tool_call_chunk
data: {...}

event: tool_result
data: {...}

event: ai_delta
data: {...}

event: end
data: {}

```

### 错误边界

请求体校验发生在开始响应之前，因此空消息等错误可以正常返回 HTTP `422`。

模型或工具错误可能发生在 SSE 响应头已经发送之后，此时不能再把 HTTP 状态改成 `500`。最小接口应发送：

```text
event: error
data: {"message":"Agent execution failed"}

event: end
data: {}

```

错误事件不能直接暴露 API Key、完整异常栈或内部请求参数；详细异常只应进入服务端日志。

### 与 SQLite 生命周期的关系

第三个功能点中，SQLite 上下文必须覆盖整个 SSE 迭代：

```python
def generate_frames(...):
    """在数据库连接有效期间持续产生 SSE 帧。"""
    # saver 不能在返回 StreamingResponse 前关闭，因为生成器尚未开始执行。
    with open_sqlite_checkpointer(database_path) as checkpointer:
        graph = build_agent_graph(checkpointer=checkpointer)
        for event in stream_agent_messages(graph, messages, config):
            # 每消费一个 Agent 消息就立即编码并向 HTTP 客户端发送。
            yield encode_event(event)
```

错误写法是先在 `with` 中创建生成器，退出后再交给 `StreamingResponse`；真正迭代发生时连接已经关闭。

### 与 DeerFlow 源码的对应关系

DeerFlow 路由层同样只负责建立 HTTP 流式响应：

```python
## 路由把异步事件消费者交给 StreamingResponse。
return StreamingResponse(
    sse_consumer(...),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    },
)
```

`sse_consumer()` 在服务层消费 `StreamBridge`，处理事件 ID、心跳、`Last-Event-ID` 重放、断线取消、结束哨兵和多订阅者。Mini Deer 暂时不复制这些生产能力，只保留相同的核心分层：

```text
Agent 消息生成器
    → SSE 编码器
    → StreamingResponse
    → HTTP 客户端
```

### 验证方式

离线测试使用假事件流，不能访问 DeepSeek 或 Open-Meteo。真实验证时启动：

```powershell
## Uvicorn 持续运行，并由 FastAPI 提供 /chat/stream。
.\.venv\Scripts\python.exe -m uvicorn mini_deer_agent.api:app --reload
```

另开 PowerShell 使用 `curl.exe -N`。`-N` 会关闭 curl 自身的输出缓冲，否则即使服务端逐步发送，终端也可能延迟显示：

```powershell
## 使用 ASCII JSON 验证可以避开 Windows PowerShell 的中文参数编码差异。
curl.exe -N -X POST http://127.0.0.1:8000/chat/stream `
  -H "Content-Type: application/json" `
  -d '{"message":"Use get_weather for Beijing, then answer in Chinese.","thread_id":"weather-http-demo"}'
```

### 代码注释要求

- 所有新增请求模型、SSE 编码函数、生成器和路由必须有中文职责说明。
- 注释必须说明 SSE 空行、JSON 单行编码和 `flush`/缓冲相关边界。
- 异常分支必须说明为什么响应开始后只能发送 `error` 事件，不能修改 HTTP 状态。
- SQLite 生成器必须说明 saver 生命周期为什么要覆盖完整 HTTP 响应迭代。
- 测试替身必须说明为什么不能在离线测试中访问 DeepSeek 和真实天气服务。

### 本课范围外

- WebSocket 双向协议
- 异步 `astream()` 与 `AsyncSqliteSaver`
- `StreamBridge`、心跳和多订阅者广播
- `Last-Event-ID` 断线重放
- 多 Worker 任务所有权与后台运行队列
- 身份认证、限流、CORS 和生产部署
- 浏览器聊天页面与 Markdown 增量渲染

---

## 第 9 课设计概要：可演进的 Web Agent 基础架构

### 架构目标

本课交付的功能仍然是“在浏览器与 Agent 流式对话”，但代码按未来生产级 Agent 的长期边界组织。后续增加会话列表、文件、工具审批、子任务、记忆、认证、可观测性和多 Agent 时，应把实现放入已经确定的模块，而不是继续扩大单个 `api.py`、HTML 或 JavaScript 文件。

本课遵循以下原则：

1. **先固定边界，再逐步填充能力**：建立正式的后端 HTTP 层、应用服务层、Agent 运行层、基础设施层和前端功能层。
2. **协议先于页面实现**：浏览器只依赖版本化 HTTP/SSE 契约，不直接了解 LangGraph 消息对象或 SQLite 细节。
3. **资源生命周期归应用管理**：数据库 checkpointer 等长生命周期资源由 FastAPI lifespan 创建和关闭，不在每个请求中重复初始化。
4. **保持可替换性**：DeepSeek、SQLite、SSE、React 页面都通过明确接口接入，未来可以替换模型、数据库或部署形态。
5. **不创建空壳功能**：目录和接口按长期架构建立，但认证、重连、文件等能力在对应课程到来时再实现真实逻辑。

### 本课核心功能

1. 把 FastAPI 入口、路由、请求模型和聊天流应用服务分开，保留稳定的 ASGI 入口。
2. 建立独立的 React + TypeScript 前端工程，并配置开发代理、类型检查、测试和生产构建。
3. 实现类型化的 POST SSE 客户端，正确处理网络 chunk、UTF-8 字符和 SSE frame 三种不同边界。
4. 用显式运行状态机管理一次 Agent run，并按消息 ID 合并模型增量、工具调用和工具结果。
5. 建立线程 ID 的设备本地管理，支持继续当前线程和创建新线程，但不把它误当成用户身份或权限。

### 原子功能点

1. **后端模块化迁移与 HTTP 分层基线**：把现有平铺模块迁入 `agents`、`application`、`llms`、`tools`、`persistence`、`streaming` 和 `server` 包，同时增加应用工厂、版本化路由与 schema；稳定 ASGI 入口和现有端点行为不变。运行后端测试，用户重新调用健康检查和 SSE 接口验证。
2. **前端工程与可识别页面**：建立 React/TypeScript 前端及模块目录，完成可识别的聊天页面外壳，但不发送真实消息。用户验证桌面和窄窗口布局。
3. **类型化流式客户端**：实现独立 SSE parser、API client、事件类型和 run 状态机，连接真实 DeepSeek 与天气工具。用户验证模型文字逐步出现和工具状态更新。
4. **线程连续性**：实现线程仓储、新会话和上下文连续性，验证同一线程可以追问、新线程互相隔离。

每个功能点都执行“先讲清源码对应关系 → 编写带中文注释的代码 → 自动化检查 → 用户实际运行验证 → 验证成功后写入 `LEARNING.md`”，完成一个功能点后暂停。

### 目标目录结构

```text
mini-deer-agent/
├── frontend/                         # 独立、可构建的 Web 应用。
│   ├── package.json                  # 开发、测试、类型检查和构建脚本。
│   ├── vite.config.ts                # 开发期 /api 代理和生产构建配置。
│   ├── tsconfig.json                 # TypeScript 严格模式。
│   ├── index.html                    # SPA 宿主页，不承载业务逻辑。
│   ├── src/
│   │   ├── app/
│   │   │   ├── App.tsx               # 应用组合入口。
│   │   │   └── styles.css            # 全局设计变量和页面基础样式。
│   │   ├── features/chat/
│   │   │   ├── api/chat-stream.ts    # 聊天 run 的 HTTP/SSE 客户端。
│   │   │   ├── model/events.ts       # SSE 判别联合类型和校验。
│   │   │   ├── model/reducer.ts      # run 与消息合并状态机。
│   │   │   ├── model/use-chat-run.ts # 连接 API、状态机和取消信号。
│   │   │   └── ui/                   # ChatPage、MessageList、Composer、ToolActivity。
│   │   ├── entities/
│   │   │   ├── message/              # 与展示无关的消息领域类型。
│   │   │   └── thread/               # thread_id 与本地线程仓储。
│   │   └── shared/
│   │       ├── api/sse-parser.ts      # 与聊天业务无关的增量 SSE 解析器。
│   │       ├── config/runtime.ts      # API 基础路径等公开运行配置。
│   │       └── ui/                    # 可复用但不含业务语义的 UI 原件。
│   └── tests/                         # parser、reducer、组件和后续 E2E 测试。
├── src/mini_deer_agent/
│   ├── api.py                         # 稳定 ASGI 入口，只导出 app/create_app。
│   ├── application/
│   │   └── run_stream.py              # 编排一次 Agent run，不依赖 FastAPI。
│   ├── agents/
│   │   └── main/
│   │       └── graph.py               # 主 Agent 的 LangGraph 状态图与路由。
│   ├── core/
│   │   └── config.py                  # 后端私密配置与环境校验。
│   ├── llms/
│   │   └── factory.py                 # DeepSeek 等聊天模型的构造入口。
│   ├── persistence/
│   │   └── checkpoints.py             # checkpointer 创建、迁移与关闭。
│   ├── server/
│   │   ├── app.py                     # FastAPI 工厂、lifespan、中间件和路由注册。
│   │   ├── dependencies.py            # 从 app.state 获取应用服务的依赖函数。
│   │   ├── routers/
│   │   │   ├── health.py              # 健康与就绪探针。
│   │   │   └── runs.py                # HTTP 参数、响应头和 SSE StreamingResponse。
│   │   ├── schemas/
│   │   │   └── runs.py                # API 请求、错误和事件数据契约。
│   │   └── __init__.py
│   ├── streaming/
│   │   ├── events.py                  # 与传输框架无关的 run 事件契约。
│   │   ├── langgraph.py               # LangGraph 消息到 run 事件的转换。
│   │   └── sse.py                     # run 事件到 SSE wire format 的编码。
│   └── tools/
│       ├── registry.py                 # 主 Agent 可用工具的集中注册入口。
│       └── weather.py                  # Open-Meteo 天气工具及外部 API 适配。
├── tests/
│   ├── server/                         # 路由、schema、依赖和应用生命周期测试。
│   └── ...                             # 现有 Agent、流式、存储测试。
└── LEARNING.md                         # 用户验证成功后记录课程结论。
```

这是一套“先建立稳定扩展槽位、按功能填充”的结构。第一个功能点就完成现有平铺模块的迁移，避免未来工具、Agent 或持久化实现增加后再做全局搬迁。不会提前创建没有代码的 `auth`、`uploads`、`memory` 等目录；当课程实现该能力时，再把真实模块放入已经稳定的层级。

### 为什么前端改为 React + TypeScript

原生 `index.html + app.js` 能演示一次 SSE 请求，却不能稳定承载生产 Agent 后续必需的复杂状态：

```text
thread
  └── run
      ├── user message
      ├── reasoning delta
      ├── assistant delta
      ├── tool calls (0..n)
      ├── tool results (0..n)
      ├── artifacts / citations
      └── completed / failed / cancelled
```

React 负责可组合 UI，TypeScript 让协议变更在编译期暴露，reducer 让流式事件按确定规则更新状态。Vite 只负责 SPA 的开发与构建，不引入 SSR；Agent 工作台是高交互应用，当前没有 SEO 或服务端页面渲染需求。若以后增加公开官网，可以作为独立前端入口处理，不污染 Agent 工作台。

不为了“看起来像生产”一次安装大量组件库和状态库。当前用 React 自身的 reducer 与 hook 表达 run 状态；当跨页面服务端缓存出现后再接入查询库，避免无真实用途的依赖。

### 后端分层职责

```text
HTTP router
    → 只处理路径、请求校验、状态码、响应头和断连信号
application.run_stream
    → 创建 run 上下文并编排 Agent 流
Agent graph / streaming adapter
    → 执行 LangGraph 并输出与框架无关的领域事件
SSE encoder
    → 把领域事件序列化为标准 wire format
Checkpointer / model / tools
    → 基础设施与外部系统
```

关键限制：

- router 不直接构建模型、LangGraph 图或 SQLite 连接。
- application 层不依赖 FastAPI 或 `StreamingResponse`，以后 CLI、定时任务和消息渠道也能复用同一 run 用例。
- 前端不接收 Python 类名、LangChain message 对象或数据库 checkpoint。
- `api.py` 保持稳定，使 `uvicorn mini_deer_agent.api:app` 不因内部重构改变。
- `create_app()` 接受可替换依赖，测试不需要真实 DeepSeek 或真实 SQLite。

### 应用生命周期

当前实现为每次聊天请求打开 SQLite checkpointer。修订后由 FastAPI lifespan 管理长生命周期资源：

```text
应用启动
    → 校验 Settings
    → 创建 checkpointer / model factory / run service
    → 放入 app.state

请求到达
    → Depends 从 app.state 取得同一个 run application service
    → 创建仅属于本次请求的 run 上下文

应用关闭
    → 等待或终止在途 run
    → 关闭 checkpointer 与其他连接
```

这为以后加入连接池、PostgreSQL、任务队列和指标采集保留正确位置，也避免在路由函数里散落资源创建代码。

### 版本化 API

新的正式接口使用资源化、可版本演进的路径：

```http
GET  /api/v1/health
GET  /api/v1/ready
POST /api/v1/threads/{thread_id}/runs/stream
```

聊天请求第一版：

```json
{
  "message": "请查询北京当前天气"
}
```

`thread_id` 属于线程资源，所以放在路径中；服务端生成 `run_id`，一轮执行不能只靠 `thread_id` 标识。现有 `/health` 和 `/chat/stream` 在迁移期作为兼容别名保留并标记 deprecated，示例和前端统一改用 `/api/v1`，后续在明确的破坏性版本中删除。

### 稳定的 SSE 事件契约

每个 SSE frame 包含标准 `id`、`event` 和统一 JSON envelope：

```text
id: <run_id>:<sequence>
event: ai_delta
data: {"version":"1","run_id":"...","thread_id":"...","sequence":4,"message_id":"...","payload":{"text":"北京"}}
```

第一版事件类型：

| `event` | `payload` 核心字段 | 用途 |
| --- | --- | --- |
| `run_started` | `created_at` | 建立 run 身份和初始状态 |
| `ai_delta` | `text` | 按 `message_id` 合并模型文本 |
| `tool_call_delta` | `tool_call_id`、`name`、`arguments_delta` | 增量展示工具请求 |
| `tool_result` | `tool_call_id`、`name`、`content` | 关联对应工具结果 |
| `run_error` | `code`、`message`、`retryable` | 稳定错误，不暴露内部异常和密钥 |
| `run_completed` | `finish_reason` | 明确结束并恢复输入状态 |

统一字段现在就保留 `version`、`run_id`、`thread_id`、`sequence`、`message_id`，以后实现取消、重连、事件重放、追踪和运行历史时不需要推翻协议。未实现事件重放前，不能声称 `Last-Event-ID` 已受支持。

### 浏览器流式解析

浏览器原生 `EventSource` 只能发 GET，当前接口需要 POST JSON，因此 API client 使用 `fetch()`、`ReadableStream` 和 `TextDecoder`。

```text
reader.read()
    → decoder.decode(value, { stream: true })
    → 追加文本 buffer
    → 兼容 \n\n 与 \r\n\r\n，提取所有完整 SSE frame
    → 保留不完整尾部
    → 解析 id / event / data，多行 data 用换行连接
    → JSON 校验为 ChatStreamEvent
    → reducer 消费事件
```

必须区分三种边界：

- 网络 chunk 不等于 SSE frame。
- SSE frame 不等于模型 token。
- 一个 UTF-8 中文字符也可能跨网络 chunk。

parser 是 `shared/api` 中无 UI 依赖的异步生成器，可以用构造出的碎片流做单元测试。聊天 API client 只负责 URL、请求、状态码、`AbortSignal` 和事件类型校验。

### 前端运行状态机

```text
idle
  └── submit → connecting
                  ├── run_started → streaming
                  │                   ├── run_completed → completed → idle
                  │                   ├── run_error → failed → idle
                  │                   └── abort → cancelled → idle
                  └── HTTP/network error → failed → idle
```

状态中至少保留：

- 当前 `threadId`、`runId` 和递增 `sequence`。
- 按 ID 索引并按顺序展示的消息。
- `tool_call_id` 到工具活动卡片的关联。
- 当前阶段、错误对象和 `AbortController`。

同一线程第一版只允许一个在途 run。reducer 检查 sequence，避免重复或乱序事件把 UI 状态覆盖。未来实现并行任务时，在 run 维度扩展，不把布尔变量散落到组件里。

### 前端组件边界

```text
ChatPage
├── ThreadHeader          # 当前线程、新会话、连接状态
├── MessageList role=log # 只负责有序渲染消息
│   ├── UserMessage
│   ├── AssistantMessage
│   └── ToolActivity      # 通过 tool_call_id 关联调用与结果
└── Composer              # 输入、发送、停止和键盘行为
```

组件只接收明确 props，不直接发请求或读 `localStorage`。`useChatRun` 编排流，reducer 处理事件，thread repository 管理设备本地线程键。这样以后加入历史侧栏、文件上传或工具审批时，可以在对应 feature/entity 中扩展。

### 线程、身份与持久化边界

第一版允许浏览器生成 UUID 并把当前 `thread_id` 保存到 `localStorage`。这里只代表“这台设备上次打开的线程”，不代表用户身份：

```text
localStorage
    → 可以保存设备本地 thread_id 和无敏感偏好
    → 不保存 API Key、访问令牌或完整聊天记录

后端 checkpointer
    → 保存 LangGraph 状态以续接上下文
    → 当前还不提供历史列表与消息回放 API
```

生产认证加入后，后端必须从认证上下文获得 `principal_id`，并验证线程所有权；绝不能因为客户端知道 `thread_id` 就允许读取或运行该线程。路由依赖层现在预留请求上下文入口，但本课不伪造登录系统。

### 安全基线

- DeepSeek API Key 只存在于后端环境，永不进入前端构建变量或响应。
- 模型、工具和错误文本按不可信内容处理；纯文本使用 React 默认转义，禁止直接使用 `dangerouslySetInnerHTML`。
- API 限制 message 与 thread ID 长度，拒绝空消息和非法 UUID。
- 正式错误使用稳定 code；服务端日志可以记录异常，客户端不得收到堆栈、数据库路径或密钥。
- 请求携带 request/run/thread 关联字段，日志不能记录密钥，用户正文的记录策略后续单独配置。
- 开发期由 Vite 代理 `/api`；生产期保持同源，避免为了本地联调开放宽泛 CORS。
- 前端请求使用 `AbortController`，组件卸载或用户停止时中断网络读取；后端后续课程再实现真正的 run 取消语义。

### 开发与生产部署边界

```text
开发：浏览器 → Vite dev server → /api 代理 → FastAPI

生产：浏览器 → 同源反向代理/CDN
                  ├── /assets 与 SPA → frontend/dist
                  └── /api/*          → FastAPI
```

为方便本地单进程演示，FastAPI 可以选择挂载已经构建好的 `frontend/dist`，但它只消费构建产物，不负责前端源码。生产环境可以改由反向代理或 CDN 提供静态文件，无需修改 React 业务代码或 API 契约。

项目目前没有 `.openai/hosting.json`，课程围绕本地 FastAPI 与用户掌握的运行环境，因此本课不初始化 Sites 或发布公网地址。

### 自动化质量门槛

后端：

- router 使用注入的假 service 做契约测试，不调用真实 DeepSeek。
- lifespan 测试验证资源只初始化一次并正确关闭。
- 现有 Agent、SQLite、SSE 测试全部保持通过。

前端：

- `typecheck`：严格 TypeScript 检查。
- `lint`：组件、hook 和潜在不安全代码检查。
- `test`：SSE 分片、跨块中文、多帧合并、reducer 顺序和错误状态。
- `build`：验证生产构建成功。
- 后续关键用户流程使用 Playwright 连接可控假后端；真实 DeepSeek 调用仍由用户单独验证，避免测试不稳定和产生费用。

自动化检查不能代替真实运行。本课每个原子功能点仍由用户在自己的 PowerShell、Uvicorn 和浏览器中验证后再继续。

### 与 DeerFlow 源码的对应关系

DeerFlow 后端使用 `app/gateway/app.py` 的应用工厂集中管理 lifespan 与 router 注册，业务端点放在 `app/gateway/routers/`；Mini Deer 的 `server/app.py + routers` 使用同构的职责边界，通用 run 编排则独立放入 `application` 层，供未来 HTTP 之外的入口复用。

DeerFlow 前端使用：

```text
src/app/                     # 应用入口和路由
src/core/threads/            # thread API、类型、hook 与状态逻辑
src/components/workspace/    # 工作台聊天组件
```

其 `useStream<AgentThreadState>()` 负责 SDK SSE 解码、thread/run 状态、消息合并、重连和 UI 节流。Mini Deer 对应为：

```text
frontend/src/app/
frontend/src/features/chat/
frontend/src/entities/thread/
frontend/src/shared/api/sse-parser.ts
```

我们先手工实现类型化 SSE parser 和 reducer，以便真正理解 SDK 隐藏的链路；当协议复杂度达到 LangGraph SDK 能覆盖的范围时，再做基于契约和测试的替换，而不是让组件绑定某个临时实现。

### 代码注释要求

- 所有新增代码必须有中文注释，重点说明职责、边界和“为什么”，不能只把语句翻译成中文。
- `server` 层注释必须说明 router、service、lifespan 和依赖注入的分工。
- TypeScript 注释必须解释网络 chunk、SSE frame、模型增量三种边界。
- reducer 注释必须说明消息 ID、工具调用 ID、sequence 与状态迁移规则。
- 安全相关代码必须说明为什么不能暴露密钥、使用不安全 HTML 或信任 thread ID。
- 测试注释必须说明它保护的协议或架构约束，而不只是描述输入输出。

### 本课范围外但已有明确扩展位置

| 后续能力 | 预定位置 |
| --- | --- |
| 历史列表与回放 | 后端 threads router/service；前端 entities/thread |
| 停止生成与重试 | runs router/service；chat run 状态机 |
| Markdown、代码与引用 | entities/message renderer；独立安全策略 |
| 文件上传与 artifacts | 独立 uploads/artifacts feature 与 router |
| 认证和线程授权 | server dependencies/middleware；frontend auth feature |
| 多 Agent 与子任务 | Agent runtime；前端 agents/tasks feature |
| MCP 与工具审批 | tools/runtime；前端 tool approval feature |
| 可观测性 | server middleware、run service 和基础设施 adapter |
| PostgreSQL/Redis/队列 | persistence/infrastructure adapter，不改变 HTTP/UI 契约 |
| SSE 重连与事件重放 | run event store、`Last-Event-ID` 与现有 sequence 契约 |

