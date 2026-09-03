# Mini Deer Agent — Agent 能力学习路线

> 文档状态：当前有效（重心调整版）。
>
> 最后更新：2026-09-03。
>
> 当前优先级补充：用户已结束前端优化，指定下一大阶段为项目工作区与 Agent Coding。实施入口见 [第 13 阶段计划](project-workspace-coding-stage.md)，状态为规划待确认；阶段内的文件管理、审批、隔离执行和 Diff 不再受本文旧「留白」限制。其余留白继续保留。本文第 12 阶段顺序作为已完成主线的历史参考，不覆盖新计划。
>
> 本文是项目重心的重新声明：**优先学习并逐步实现 Agent 工作流的核心能力**，次要的工程功能（认证、部署、多渠道等）降级为「留白」，只在调试确有体验需求时再补。本文负责 Agent 能力的战略顺序；`WORKPLAN.md` 只维护当前功能点、进度和验证状态，不再独立改变本路线的优先级。

## 1. 为什么重心要调整

用户用相同问题和名义上相同的模型分别测试 Mini Deer 与 DeerFlow，观察到任务分解、工具使用和回答完整度存在明显差距。一次对比不能排除模型参数、运行时上下文和工具配置等变量，但足以说明：**编排层是当前最值得优先学习和改进的部分**。

- 重心调整前的 Mini Deer：一个手写的 LangGraph `model → tools → model` 循环，System Prompt 较短，只有少量网页工具。
- Mini Deer 当前：已完成 12.1—12.13，Prompt 为 `mini-deer-agent/system/v14`，已有
  `write_todos` 规划、Clarification v2、受控并发 `task` 委派，以及显式和受控自动内置
  Skills 激活、专用天气工具与 allowed-tools 双层权限、主/子 Agent 动态日期时间投影和
  checkpoint 累计摘要压缩；
  后续差距应从这个新基线继续衡量。
- DeerFlow：用 `langchain.agents.create_agent` 原语，叠加多层中间件与动态拼装 Prompt，让同一基础模型获得更完整的任务执行能力。

因此，接下来的学习重心是：**把 DeerFlow 里那些「让 Agent 变聪明」的编排能力，逐个读懂、逐个在 Mini Deer 里以最小形态落地**。

## 2. 差距诊断：DeerFlow 的 Agent 能力全景

以下能力按「对任务成功率和可观察执行质量的直接贡献」排序。这个价值排序不等于实施顺序；实施顺序还要考虑复杂度和依赖关系。

DeerFlow 对照仓库为 `D:\project\agentstudy\deer-flow`，本路线审阅时的基线提交为 `a5acc25d`，harness 包根目录为 `backend/packages/harness/deerflow/`。

| # | 能力 | 作用 | DeerFlow 对照源码 | 对任务能力的贡献 |
|---|---|---|---|---|
| 1 | System Prompt 工程 | 动态拼装详尽行为指令：工具清单、skills 元数据、子代理规则、引用规则、保密边界 | `agents/lead_agent/prompt.py`（`apply_prompt_template`） | 最高，最直接 |
| 2 | Plan mode / Todo | `write_todos` 工具让模型对复杂任务先分解步骤、实时更新 | `agents/lead_agent/agent.py`（`_create_todo_list_middleware`）、`agents/middlewares/todo_middleware.py` | 高，显式任务分解与进度跟踪 |
| 3 | Sub-agent 委派 | `task` 工具把子任务委派给独立子代理，各自深入推理 | `agents/middlewares/subagent_limit_middleware.py`、`tools/builtins/task_tool.py` | 高，复杂任务分而治之 |
| 4 | Skills 渐进加载 | `/skill-name` 激活 `SKILL.md`，注入领域专家指令与专用工具 | `skills/`、`agents/middlewares/skill_activation_middleware.py`、`skill_context.py`、`describe_skill` / `tool_search` | 高，领域能力注入 |
| 5 | Clarification 澄清 | `ask_clarification` 让模型主动向用户澄清模糊需求 | `agents/middlewares/clarification_middleware.py` | 中高，避免猜错方向 |
| 6 | 动态上下文 | 注入当前日期、时间等 `<system-reminder>`，保持静态 prompt 可缓存 | `agents/middlewares/dynamic_context_middleware.py` | 中 |
| 7 | 上下文压缩/摘要 | 接近 token 上限时压缩历史，保留关键信息 | `agents/middlewares/summarization_middleware.py`、`runtime/context_compaction.py` | 中，支撑长任务 |
| 8 | 长期 Memory | 跨会话记住用户偏好、目标、决策、身份 | `agents/memory/`（deermem / mem0 / honcho）、`memory_middleware.py`、`agents/memory/tools.py` | 中，个性化与延续性 |
| 9 | Durable Context | 委派台账 + 已加载技能在压缩后仍可见 | `agents/middlewares/durable_context_middleware.py` | 中 |
| 10 | 循环检测 | 阻止模型重复调用同一工具原地打转 | `agents/middlewares/loop_detection_middleware.py` | 中，健壮性 |
| 11 | 工具输出预算/摘要 | 限制工具返回体积，生成结构化预览；DeerFlow 可进一步外置到文件 | `agents/middlewares/tool_output_budget_middleware.py`、`tool_output_synopsis.py` | 低中，健壮性 |

> 说明：DeerFlow 还有大量「工程/安全」类中间件（认证、授权、沙箱审计、上传、MCP 高级路由、Token 计费等），它们**不属于本次学习重心**，统一列入第 5 节「留白」。12.16 只提前实现了 MCP 的最小工具接入主链。

## 3. 学习原则

沿用 `PROJECT.md` 第 18 节的流程，并补充以下针对 Agent 能力的规则：

1. **先读懂 DeerFlow，再落地**：每个能力先定位并讲解 DeerFlow 对应源码，说明「它为什么让模型变聪明」，再决定 Mini Deer 的最小实现。
2. **最小可验证闭环**：不追求功能对齐，优先观察任务是否完成、工具是否选对、约束是否保留、引用是否可信、是否减少无依据猜测。
3. **只评价可观察行为**：不把隐藏思维链、回答长度或格式复杂度当作能力指标；重点观察任务分解、工具轨迹、最终结果和失败恢复。
4. **逐项真实验证**：每个能力用同一组问题做前后对比，确认行为变化，而不是只看测试通过。
5. **保留轻量回归样本**：完整 Trace / Evals 平台可以留白，但每个阶段必须补充少量固定问题和明确通过条件，防止后续能力让已验证行为回退。

最低验证维度：

- 简单问题不滥用复杂工具。
- 模糊问题不擅自猜测关键条件。
- 复杂任务能分解并完成关键步骤。
- 工具调用结果能被正确使用，失败后能够收敛。
- 新能力带来的额外模型调用、耗时和输出长度仍可接受。

## 4. 分阶段学习路线

每阶段按 `源码对照 → 讲解 → 测试驱动 → 真实验证 → 写入 LEARNING.md` 推进。阶段是能力主题，不等于一个原子功能点；涉及多个可观察行为时，必须继续拆分并逐个让用户验证。

阶段之间存在明确依赖：Clarification 依赖现有 Run / 事件 / 历史链；Sub-agent 与 Skills 的关键信息必须在摘要发生后由 Durable Context 保留；长期 Memory 必须先定义本地单用户身份边界。后续实施按下面顺序推进。

### 阶段 1：System Prompt 工程升级（已完成，功能点 12.1）

- **目标**：把 Mini Deer 的 System Prompt 从「简短身份声明」升级为「动态拼装的详尽行为指令」，对齐 DeerFlow 的 `apply_prompt_template` 结构。
- **要点**：Prompt 版本化升级到 `system/v5`；新增 `<thinking_style>` / `<response_style>` / `<critical_reminders>`，强化「先分析、分解任务、主动澄清、引用可信来源」等行为约束。
- **验证**：同样的问题，任务分解更清楚、关键约束保留得更完整、模糊条件会先指出；用户已确认整体表现比以前更强。

### 阶段 2：Plan mode（Todo 规划工具）（已完成，功能点 12.2）

- **目标**：引入 `write_todos` 工具，让模型对 3+ 步任务先列计划、执行中实时更新。
- **要点**：对照 `todo_middleware.py` 的 `write_todos` 契约；前端展示带状态色的任务清单。
- **验证**：复杂任务先列计划再逐步执行；简单任务不触发。用户已确认。

### 阶段 3：Clarification（澄清，12.3—12.6 已完成）

- **目标**：引入 `ask_clarification` 工具，让模型在需求模糊时主动追问，而不是猜。
- **最小语义**：第一版不实现同一 Run 的长期挂起与恢复。澄清请求结束当前 Run；用户回答后在同一 Thread 创建新 Run，通过稳定的 `request_id` 关联并继续任务。
- **建议拆分**：先完成工具契约、Prompt 使用规则和 Run 结束语义，再完成结构化追问卡片与回答关联；两个功能点分别验证。
- **要点**：对照 `clarification_middleware.py` 与 DeerFlow 前端的 `human_input_response`；普通聊天输入仍可作为兼容回退。
- **验证**：模糊问题时 Agent 先追问；回答后能正确关联原问题继续，不重复追问已回答的信息。
- **已验证进度**：12.3 完成工具与 Run 结束语义；12.4 完成 v1 专用卡片、精确回答关联和刷新恢复；12.5 完成 text、textarea、select 的 v2 基础表单；12.6 补齐 number、date、multi_select、checkbox、类型化 JSON 和必填语义。全部功能继续采用“下一 Run 继续”的最小语义。

### 阶段 4：Sub-agent 委派（task 工具，12.7—12.8 已完成）

- **目标**：引入 `task` 工具，让主代理把子任务委派给独立子代理。
- **已验证实现**：12.7 完成独立 prompt、受控工具集、稳定结果与失败和递归委派禁止；
  12.8 扩展为每批最多 3 个、每 Run 累计最多 6 个的受控并发，并补齐原序收敛、失败
  隔离、混合/超额调用结算和父 Run 取消传播。
- **要点**：对照 `subagent_limit_middleware.py` 与 `task_tool.py`；第一版禁止子代理再次调用 `task`，避免递归委派。
- **验证**：真实页面已出现两个独立 task 工具卡并分别返回结果，主 Agent 在收敛后正确
  综合；简单问题不委派，父 Run 取消时全部子任务停止。
- **明确留白**：后台任务、可配置限额、自定义子 Agent、专用进度 UI、跨恢复 Run 的
  durable delegation ledger、子图 checkpoint、Skills/Memory 和文件写入仍不在当前实现中。

### 阶段 5：Skills 渐进加载（12.9—12.11 已完成最小权限闭环）

- **目标**：支持 `SKILL.md` 技能文件，显式 `/skill-name` 激活或由受控规则按需加载，注入领域指令与专用工具。
- **实施拆分**：12.9 内置发现与显式激活，12.10 受控自动激活，12.11 专用工具策略。
- **要点**：对照 `skills/`、`skill_activation_middleware.py` 与 `skill_context.py`；必须区分可信技能指令与用户/工具数据。
- **已验证实现**：12.9 完成只读内置 `SKILL.md` 发现、Prompt 元数据目录、严格 slash、
  当前 Run 模型投影、下一 Run 失效、稳定错误和 wheel package-data；首个
  `/structured-explainer` 已通过真实页面验证，未激活时不污染普通对话。
- **已验证实现**：12.10 新增可见 `activate_skill` 工具、严格 tool call/result 留痕、独占
  路由、每 Run 一个、同名幂等、切换拒绝、slash 优先和新 Run 失效；没有采用静默关键词
  路由，也没有把正文放进工具结果或基础 Prompt。
- **已验证实现**：12.11 为 `BuiltInSkill` 增加三态 allowed-tools，分离被动/专用 registry，
  用同一决策同时过滤模型 Schema 和阻断真实执行；首个 `/weather-briefing` 只在活动时开放
  `get_weather`，越权混合批次失败关闭，下一 Run 恢复普通权限。
- **明确留白**：自定义技能、启用状态、支持资源、多个活动技能、动态 registry、
  Durable Context 和子 Agent Skills 仍须继续拆分验证。

### 阶段 6：Context 工程（动态上下文 + 摘要 + Durable Context）

- **目标**：注入动态上下文，并在接近 token 上限时压缩历史，同时保留不能被摘要丢失的结构化状态。
- **已验证进度**：12.12 已完成可信日期/时间/星期/时区的主、子 Agent 模型专用动态投影；
  每次调用刷新，保持唯一 SystemMessage，且不写入 checkpoint 或产品历史。
- **已验证进度**：12.13 已完成主、子 Agent 的 OR 阈值摘要、累计 `summary_text`、完整用户
  回合保留、失败开放、SQLite 恢复及产品历史隔离；真实长线程已观察到摘要与原文分界。
- **已验证进度**：12.14 已完成独立委派台账、技能引用和 Todo 快照通道；在原始来源被摘要
  删除后以隐藏低信任数据确定性续接。历史技能不会跨 Run 自动激活或扩大工具权限，旧委派
  也不占用新 Run 预算。
- **要点**：对照 `dynamic_context_middleware.py`、`summarization_middleware.py`、`runtime/context_compaction.py` 与 `durable_context_middleware.py`。
- **验证**：日期问题使用当前上下文；长对话压缩后仍能延续主题，并保留关键约束、委派结果和已激活技能。

### 阶段 7：长期 Memory（本地单用户，12.15 已完成）

- **目标**：跨 Thread 记住用户明确允许保存的偏好、目标和决策。
- **身份边界**：第一版只支持本地单用户默认命名空间，不承诺多用户隔离；正式用户身份和权限留到认证阶段。
- **已验证实现**：12.15 已完成 `memory_search/add/update/delete`、业务 SQLite v7、跨 Thread/
  重启持久化、修改与删除立即生效、重复内容唯一约束和条件化 Prompt v16。普通陈述不会静默
  写入，相关历史由模型按需搜索，不自动注入全部事实。
- **继续后置**：模型自动提取、敏感信息识别、多用户命名空间、向量检索、远程后端和专用管理
  页面不属于 12.15；没有新的明确需求或评估前不主动加入。
- **要点**：对照 `agents/memory/`、`memory_middleware.py` 与 `agents/memory/tools.py`，不追求 deermem / mem0 等多后端。
- **验证**：新 Thread 中能正确引用已保存事实；删除或修改后不会继续使用旧值；未授权信息不被自动记忆。

### 阶段 8：MCP 外部工具扩展（12.16 已完成）

- **目标**：无需修改 Agent 图即可从可信静态配置接入外部 MCP 工具。
- **已验证实现**：12.16 支持 stdio/HTTP、多服务器并行发现与故障隔离、初始化超时、名称前缀/
  冲突检查、环境变量引用、启动快照和只读状态接口；工具进入主图的模型 schema、Skills 权限链与
  ToolNode，真实 stdio Server 已完成发现和调用验证。
- **边界**：配置变更需重启；每次工具调用独立 session；子 Agent 不继承 MCP。配置管理 UI/API、
  热更新、OAuth、持久 session、Resources/Prompts/Roots、长任务与工具审批继续后置。
- **要点**：对照 DeerFlow `mcp/client.py`、`mcp/tools.py`、`mcp/cache.py`、`mcp/session_pool.py`
  和 `config/extensions_config.py`，只抽取当前架构需要的发现与注册链。

### 阶段 8 补充：前端体验（12.17—12.18 已完成，非路线阶段）

Agent 能力路线完成后，为了让思考过程与执行过程可被观察、便于学习，补了两个前端体验功能：

- 12.17 执行过程折叠：工具调用与中间回复折叠进「执行过程」，澄清卡与最终回答直接展示。
- 12.18 思考过程展示：捕获 DeepSeek `reasoning_content` 并折叠展示，刷新后可恢复。

这两项属于「因真实体验需要」提前实施的前端展示工作，不属于 Agent 能力战略阶段；其中 12.18
的模型层补丁（`PatchedChatOpenAI` 捕获并回传 reasoning_content）同时修复了工具循环多轮时
缺失历史推理字段导致的潜在 400。

### 阶段 9：健壮性（循环检测 + 工具输出预算，后置）

- **目标**：阻止重复工具调用死循环，限制工具输出体积。
- **建议拆分**：未来出现真实重复调用或输出过大问题时，再独立实现循环检测与工具输出预算。
- **当前状态**：按用户决定后置，不指定为 12.19；下一项等待用户选择。
- **要点**：对照 `loop_detection_middleware.py`、`tool_output_budget_middleware.py` 与 `tool_output_synopsis.py`。Mini Deer 第一版只做结构化摘要和有界截断，不依赖沙箱、Artifact 或完整文件平台。
- **验证**：重复调用能够停止并生成可用结论；超大工具结果不会撑爆上下文，关键结构和少量原始样本仍然可见。

## 5. 留白清单（次要功能，视情况完善）

以下功能**不主动推进**，仅在调试确需时再补。保留在 `WORKPLAN.md` 的对应条目，但不占用后续功能点编号：

- 认证、授权、多租户
- 部署、容器化、PostgreSQL/Redis、迁移体系
- IM 渠道（飞书/钉钉/微信等）
- MCP 配置管理 UI/API、热更新、OAuth、持久 session、Resources/Prompts/Roots 与长任务
- 浏览器自动化、二进制文件解析（PDF/图片）
- 完整 Artifact / 文件上传平台（已完成内联文本附件基础，够用即可；不做待发送附件的前端跨刷新持久化、文件资产库和生命周期管理）
- 完整可观测性 / Trace / 自动化 Evals 平台 / CI（每阶段所需的轻量固定回归样本不属于留白）
- 沙箱与任意命令执行

## 6. 文档治理

- `PROJECT.md` 维护稳定规则和架构边界；本文件维护 Agent 能力的战略顺序；`WORKPLAN.md` 维护当前功能点、进度和验证状态；`HANDOFF.md` 只做跨窗口交接。
- Agent 能力的先后顺序以本文件为准；`WORKPLAN.md` 应镜像当前执行状态，不另建一套竞争路线。
- 每完成并经用户验证一个原子功能点，同步更新 `WORKPLAN.md` 的当前进度，并在 `LEARNING.md` 记录结论；跨窗口时再更新 `HANDOFF.md`。
- 功能点编号继续沿用 `<课号>.<序号>` 连续递增；阶段不等于课程，一个阶段可拆多个功能点。
- 若某个留白功能因真实体验需要而提前实施，先在本文件登记并说明理由。
