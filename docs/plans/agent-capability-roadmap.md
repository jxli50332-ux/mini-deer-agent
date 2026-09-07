# Mini Deer Agent — Agent 能力学习路线

> 文档状态：当前有效（重心调整版）。
>
> 最后更新：2026-09-07。
>
> 当前优先级补充：项目命令、失败修复、自然语言小功能、配套测试和结构化检查结果审阅均已验证；先完成第 13 阶段文档与源码一致性收口，再进入第 14—17 阶段的 Agent 执行质量增强。第一项是 14.1 固定能力基准，不直接重写 Agent 图。公开部署所需的安全与可靠性专项继续后置。
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

### 阶段 9：能力基准与执行收敛（第 14 阶段，下一主线）

#### 当前差距结论

本轮对照使用 Mini Deer 提交 `5c29b68f` 之上的当前未提交工作树，以及 DeerFlow 提交 `a5acc25d`。
Mini Deer 已经具备 Prompt v38、Todo、澄清、受控并发委派、内置 Skills、动态上下文、摘要、
Durable Context、显式长期 Memory、MCP、项目文件工具、Docker 命令和 Coding 失败修复闭环。
因此后续不再重复建设“是否有 Agent 循环”，而是提高循环在真实失败、长输出和复杂任务中的
完成率。

| 差距 | Mini Deer 当前事实 | DeerFlow 对照 | 优先级 |
| --- | --- | --- | --- |
| 结果可比较性 | 各阶段有测试和人工验收，但没有固定的跨阶段同题对照集 | 运行事件、Token 归因和独立评测入口可组合分析行为 | P0 |
| 循环收敛 | 主要依赖 Prompt 的“两轮修复”和图递归上限 | `loop_detection_middleware.py` 与 `tool_progress_middleware.py` 分别治理重复调用和无效结果 | P0 |
| 统一错误语义 | 部分工具自行捕获异常，专用节点各自包装；缺少跨工具一致的可恢复元数据 | `tool_error_handling_middleware.py`、`tool_result_meta.py` | P0 |
| 上下文预算 | 文件、搜索和命令各有局部上限，但任意 ToolMessage 没有统一进入模型前的预算 | `tool_output_budget_middleware.py`、`tool_output_synopsis.py` | P0 |
| Run 资源预算 | 有摘要阈值和子 Agent 数量限制，尚无累计 Token 警告、硬停与稳定终止原因 | `token_usage_middleware.py`、`token_budget_middleware.py`、终止类中间件 | P1 |
| 子 Agent 深度 | 只有固定通用子图，仅有网页搜索/读取，不能继承项目 Scope、Skills 或命令能力 | `subagents/config.py`、`registry.py`、`executor.py` 及内置 general-purpose/bash | P1 |
| 工具规模 | MCP 启动时把全部工具直接注册给模型，工具多时 Schema 和选择噪音线性增长 | `tool_search.py`、`deferred_tool_filter_middleware.py`、MCP routing | P1 |
| 持续自治 | 一个 Run 结束即停止；没有线程级目标、完成评估和隐藏续跑 | `runtime/goal.py` 与 `runtime/runs/worker.py` 的 Goal continuation | P2 |

已存在且不重复实现：`repair_tool_call_message_history` 已处理 dangling tool calls 和孤儿
ToolMessage；项目搜索、读文件和命令本身已有有界输出；Run/Event Store、取消与前端过程恢复
继续作为新能力的承载层。

#### 架构取舍

这里恢复的是 Agent 执行收敛能力，不恢复此前后置的公开部署安全、审批、远程隔离和运维专项。
不以“换成 DeerFlow 的 `create_agent`”作为能力目标。Mini Deer 当前显式图已经承载澄清、
技能权限和并发委派，整体迁移会同时改变过多行为。第 14 阶段先把模型调用前、模型调用后、
工具调用前和工具调用后的策略提炼为小型可组合组件，由现有图调用；完成 14.2—14.6 后再做
一次迁移评估。只有代码重复或策略顺序已经成为真实阻碍时，才单独设计迁移功能点。

#### 原子功能点

1. **14.1 固定能力基准**：增加一组可直接从真实页面运行的固定任务，覆盖简单问答、模糊需求、
   多源调研、重复空结果、超长工具输出、单文件缺陷修复、多文件小功能和并发委派。记录任务是否
   完成、工具轨迹、重复调用次数、最终检查结果、模型调用次数、耗时和 Token（能取得时）。
   第一版只保存小型样例与人工评分表，不建设完整 Evals 平台。验证时用相同模型、参数和输入跑出
   变更前基线。
2. **14.2 统一工具结果契约**：所有工具成功、无结果、部分成功、可重试失败和不可恢复失败都带
   稳定元数据；异常统一转成成对的错误 ToolMessage，让模型能换策略，不能把 Python 异常当作
   整个 Run 的默认终点。验证一个普通工具和一个 MCP 工具失败后，Agent 均能解释并继续。
3. **14.3 重复工具调用检测**：按规范化的工具名和参数签名识别连续重复，先给一次换策略提示，
   达到硬阈值后移除本轮后续 tool calls 并要求基于已有证据收尾。按 Thread/Run 隔离，Todo、澄清
   和必要的分段读文件不误判。验证同参死循环能停止、页码或行号变化的正常调用能继续。
4. **14.4 工具结果停滞检测**：利用 14.2 元数据识别连续 no-results、not-found、限流和近似重复
   内容；可由模型修正的问题只提示换查询，不可恢复问题阻断该工具但保留其他工具。验证搜索词改变
   后恢复正常，认证/配置错误不会反复重试。
5. **14.5 全局工具输出预算**：ToolMessage 进入模型前统一检查大小；小结果原样保留，大结果生成
   确定性结构摘要和头尾样本，并把完整内容写入应用数据区的当前 Run 内部结果目录，通过只读虚拟
   `run-output/...` 路径交给 `read_file` 续读；该目录不计入项目 Diff。若外置失败则有界截断并明确
   声明。验证超大 JSON、命令日志和 MCP 输出都不会撑爆上下文，模型仍能定位并读取关键段。
6. **14.6 Token、轮次与终止原因**：累计主/子 Agent 的 input/output/total Token 和模型轮次；
   软阈值只提醒模型收敛，硬阈值禁止新工具调用并保留已有回答，Run 记录 `token_capped`、
   `turn_capped` 或 `loop_capped`。验证达到上限时页面收到正常终止事件而不是悬挂或 500。
7. **14.7 回归复测与调参**：重跑 14.1；只有复杂任务完成率提高，且简单任务的无效工具调用、
   P95 时延和 Token 消耗没有不可接受回退，才结束本阶段。阈值以实测调整，不照抄 DeerFlow 默认值。

### 阶段 10：可配置专用子 Agent（第 15 阶段）

- **目标**：把当前固定网页调研子图升级为可选择、可限权、可观察的专用执行者，优先提升 Coding
  和复杂调研任务，而不是单纯增加并发数。
- **15.1 注册表与 task 契约**：定义 `name/description/system_prompt/model/tools/
  disallowed_tools/max_turns/timeout_seconds`，`task` 显式选择 Agent；先内置 research 与
  project-reader 两种。
- **15.2 权限交集**：子 Agent 的真实工具集合必须是“父 Run 当前可用工具 ∩ 子 Agent 白名单 ∩
  Skill 权限”，文件 Scope 和项目身份由父 Run 冻结传入，继续禁止递归 `task` 与用户澄清。
- **15.3 Coding 读测闭环**：project-reader 可读/搜项目；test-runner 可在同一冻结 Project 的沙箱
  执行检查。写文件仍由主 Agent 串行完成，先避免并行写冲突。验证主 Agent 能并行委派代码定位与
  测试诊断，再综合为一次实际修复。
- **15.4 生命周期与结果**：每个子任务有 pending/running/completed/failed/cancelled/timed_out、
  stop_reason、Token 和最后可用部分结果；父 Run 取消继续传播，单个失败不抹掉同批成功结果。
- **15.5 前端可观察性**：现有执行过程展示 Agent 名称、状态、耗时、停止原因和摘要；刷新后由
  RunEvent 恢复。最终验收是同一多文件任务相较 14.1 基线减少主 Agent 盲目读取，并保持结论正确。

### 阶段 11：按需工具与 Skills 扩展（第 16 阶段）

- **目标**：工具数量增长时只向模型暴露完成当前步骤所需的 Schema，同时让 Skills 从内置示例
  发展为可安装、可携带资源的能力包。
- **16.1 Deferred Tool Catalog**：先只延迟 MCP 工具；基础 Prompt 只列安全转义后的名称和短描述，
  不绑定完整 Schema。
- **16.2 `tool_search` 与提升状态**：按名称或关键词返回最多若干完整 Schema，并把已提升工具写入
  带 catalog hash 的图状态；未提升工具在模型可见层和执行层都失败关闭，主 Agent 与子 Agent
  复用同一套发现规则。验证发现后可调用，重启可恢复，同名/改版工具不会继承旧提升记录。
- **16.3 路由提示**：为少数明确领域工具配置服务端可信关键词；只做候选排序或自动提升，不让外部
  MCP 描述变成系统指令。用 20+ 假工具验证 Schema Token 明显下降且工具选择不退化。
- **16.4 用户 Skills 最小闭环**：支持本地安装/启停、frontmatter 校验、资源文件只读加载和
  allowed-tools 交集；先不做在线市场和自动生成 Skill。验证一个带参考文件的自定义 Skill 在启用后
  生效、禁用后不污染普通 Run，主/子 Agent 权限一致。

### 阶段 12：线程级 Goal mode（第 17 阶段）

- **目标**：让用户能声明一个需要多轮自主推进的目标；普通聊天继续保持一问一 Run。
- **17.1 Goal 状态与接口**：Thread checkpoint 保存 objective、continuation_count、上限、
  no_progress_count 和最近评估；提供设置、查询、清除，刷新与重启可恢复。
- **17.2 独立完成评估**：每次可见 Run 结束后，用小型非思考模型只依据用户可见证据返回
  satisfied/blocker/reason；缺证据时失败关闭，澄清、外部等待、Run 失败不自动续跑。
- **17.3 有界隐藏续跑**：只有 `goal_not_met_yet` 才注入内部 continuation 消息；设置最大续跑数、
  连续无进展熔断、Token/轮次预算和取消传播。用户新消息或清除 Goal 的并发操作优先，旧评估不能
  覆盖新状态。
- **17.4 页面验收**：显示活动目标、进度、最近评估和停止原因；用户可随时停止。用一个需要
  “定位 → 修改 → 测试 → 修复 → 再测”的样例验证 Agent 无需用户反复说“继续”，但遇到真实阻塞
  会停下并明确请求信息。

### 后续候选（不进入当前主线）

完成第 14—17 阶段后，再根据 14.1 数据决定是否投入图片理解、持久上传与 Artifact 交付、浏览器
自动化、后台任务、MCP 长任务或远程 Sandbox。这些能力能扩大任务范围，但不能替代循环收敛、
专用委派和目标续跑；在核心完成率没有数据改善前不因 DeerFlow 已有对应模块而照搬。

### 阶段总验收

- 固定基准中，复杂调研和 Coding 任务的完成率相对 14.1 基线有可复现提升。
- 重复调用、无效结果、超大输出、Token/轮次耗尽都有稳定可见的收敛原因。
- 20+ 外部工具存在时，模型默认上下文不携带全部 Schema，仍能正确发现并调用目标工具。
- 子 Agent 能在冻结的 Project Scope 内完成读/测子任务，取消、超时和失败均可恢复。
- Goal mode 能自动完成多步闭环，也会在缺少用户输入、外部等待或连续无进展时停止。
- 每个编号仍是一个可立即运行验证的功能点；完成自动化检查后暂停，由用户按文档步骤确认，再进入
  下一个编号。

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
