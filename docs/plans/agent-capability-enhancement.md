# 第 14—17 阶段：Agent 能力增强计划

> 状态：规划完成，等待第 13 阶段文档与源码一致性收口后实施。
>
> 日期：2026-09-07。
>
> Mini Deer 对照基线：`e5dc767`；DeerFlow 对照基线：`a5acc25d`。
>
> 本文是第 14—17 阶段 Agent 能力增强的唯一详细实施入口。战略背景见
> [Agent 能力学习路线](agent-capability-roadmap.md)，当前进度以项目根目录
> [WORKPLAN.md](../../WORKPLAN.md) 为准。

## 1. 目标

Mini Deer 已经具有完整的基础 Agent 循环。下一阶段不再用“有没有工具、Todo 或子 Agent”衡量能力，
而是提高复杂任务的完成率、失败后的策略调整能力，以及长任务的自主收敛能力。

本计划要形成四个结果：

1. Agent 遇到重复调用、无效结果、超长输出和资源耗尽时能够稳定收敛。
2. 子 Agent 能按任务选择专业角色，在冻结的项目范围内完成代码定位与测试诊断。
3. 外部工具和 Skills 增长后，模型仍能按需发现能力，不必携带全部工具 Schema。
4. 用户可以设置线程级目标，让 Agent 在有界预算内自主完成多个连续步骤。

## 2. 当前基线

当前 Mini Deer 已具备：

- Prompt v38、Todo 规划和结构化澄清。
- 每批最多 3 个、每 Run 最多 6 个的并发 `task` 委派及取消传播。
- 内置 Skills 的显式/受控自动激活和 allowed-tools 双层权限。
- 动态日期时间、上下文摘要、Durable Context 和显式长期 Memory。
- MCP 启动快照、网页搜索/读取和可信引用。
- Project/Thread 归属、文件浏览/搜索/读写、Docker 命令、Diff 和检查结果审阅。
- dangling tool-call 与孤儿 ToolMessage 修复、Run/Event Store、刷新恢复和服务端取消。

这些能力说明当前差距已经从“建立 Agent”转向“提高 Agent 的执行质量”。

## 3. DeerFlow 差距

| 差距 | Mini Deer 当前事实 | DeerFlow 对照 | 优先级 |
| --- | --- | --- | --- |
| 结果可比较性 | 各阶段有测试和人工验收，没有固定的跨阶段同题对照集 | 运行事件、Token 归因和独立评测入口可组合分析行为 | P0 |
| 循环收敛 | 主要依赖 Prompt 的“两轮修复”和图递归上限 | `loop_detection_middleware.py` 与 `tool_progress_middleware.py` | P0 |
| 统一错误语义 | 部分工具自行捕获异常，专用节点分别包装 | `tool_error_handling_middleware.py`、`tool_result_meta.py` | P0 |
| 上下文预算 | 文件、搜索和命令各有局部上限，缺少跨工具统一预算 | `tool_output_budget_middleware.py`、`tool_output_synopsis.py` | P0 |
| Run 资源预算 | 有摘要阈值和子 Agent 数量限制，缺少累计 Token/轮次硬停 | `token_usage_middleware.py`、`token_budget_middleware.py` | P1 |
| 子 Agent 深度 | 固定通用子图只有网页搜索/读取，不能继承项目 Scope、Skills 或命令能力 | `subagents/config.py`、`registry.py`、`executor.py` | P1 |
| 工具规模 | MCP 启动时把全部工具 Schema 注册给模型 | `tool_search.py`、`deferred_tool_filter_middleware.py`、MCP routing | P1 |
| 持续自治 | 一个 Run 结束即停止，没有线程级目标、完成评估和隐藏续跑 | `runtime/goal.py`、`runtime/runs/worker.py` | P2 |

不会重复实现的能力：

- `repair_tool_call_message_history` 已覆盖 dangling tool calls 和孤儿 ToolMessage。
- 项目搜索、文件读取和命令工具本身已经有单工具输出上限。
- Run/Event Store、取消、SSE 和历史恢复继续作为新能力的承载层。
- 已有 Coding Prompt 会指导“读取、修改、检查、失败修复、再检查”，后续增加确定性执行约束。

## 4. 架构取舍

本阶段不把迁移到 DeerFlow 的 `create_agent` 当作目标。Mini Deer 的显式 LangGraph 已经承载澄清、
技能权限和并发委派，一次性迁移会同时改变过多已验证行为。

第 14 阶段先把策略拆成四类可组合组件：

```text
模型调用前 → 历史修复、动态上下文、摘要、可见工具过滤、待处理提示
模型调用后 → Tool Call 循环检测、Token/轮次预算、终止原因
工具调用前 → 权限、未提升工具、停滞阻断
工具调用后 → 异常归一、结果元数据、输出预算、进度评估
```

这些组件先由现有节点显式调用。完成 14.2—14.6 后再评估框架迁移；只有策略顺序、复用或测试成本
已经成为真实阻碍时，才单独设计迁移功能点。

本计划恢复的是 Agent 执行收敛能力。公开部署所需的认证、审批、远程隔离、审计和运维专项仍按
现有决定后置。

## 5. 第 14 阶段：能力基准与执行收敛

### 14.1 固定能力基准

建立一组可以从真实页面重复运行的固定任务：

- 简单问答：应直接回答，不调用复杂工具。
- 模糊需求：应澄清关键条件。
- 多源调研：应分解、搜索、深读并正确引用。
- 重复空结果：应改变查询或工具，不能原地重试。
- 超长工具输出：应保留关键结构并支持继续读取。
- 单文件缺陷修复：应先复现、修改、检查并正确交付。
- 多文件小功能：应定位最小文件集合并补充聚焦测试。
- 并发委派：应并行完成独立任务并正确综合。

每次记录：任务是否完成、工具轨迹、重复调用次数、最终检查结果、模型调用次数、耗时和可取得的
Token 数据。第一版使用小型样例、结构化运行记录和人工评分表，不建设完整 Evals 平台。

用户验收：使用固定模型、参数和输入跑出变更前基线，页面上可以查看每个样例的真实过程与结果。

### 14.2 统一工具结果契约

所有工具结果归一为以下语义：

- `success`
- `no_results`
- `partial_success`
- `retryable_error`
- `terminal_error`

结果同时携带 `recoverable_by_model`、`recommended_next_action` 和安全的错误摘要。工具抛出的普通异常
统一转换为成对的错误 ToolMessage，使模型可以改变策略；需要中断图的控制异常继续向上传播。

用户验收：分别制造一个内置工具失败和一个 MCP 工具失败，Agent 都能解释失败、选择可用替代方案，
Run 不因普通工具异常直接变成 500。

### 14.3 重复工具调用检测

按规范化后的工具名和参数签名识别连续重复调用：

1. 达到软阈值时，向下一次模型调用注入一次“改变策略”的提示。
2. 达到硬阈值时，移除新的 tool calls，要求模型使用已有证据收尾。
3. 为 Run 写入稳定的 `loop_capped` 终止原因。

状态按 Thread/Run 隔离。Todo、澄清、技能激活和必要的分段 `read_file` 调用豁免或使用专门签名，
避免把行号、页码变化的正常读取误判为循环。

用户验收：同参数死循环会停止；改变查询、页码或行范围的正常调用仍能继续。

### 14.4 工具结果停滞检测

利用 14.2 的结果元数据跟踪连续 no-results、not-found、限流、不可恢复错误和近似重复正文。

- 模型能修正的问题只发出提示，允许使用新参数重试。
- 认证、配置等不可恢复问题立即阻断该工具。
- 连续瞬时失败达到阈值后阻断该工具，但其他工具仍然可用。
- 成功结果会重置对应工具的停滞状态。

用户验收：搜索词改变后可以恢复；认证或配置错误不会被重复调用；一个工具被阻断后 Agent 仍能使用
其他工具完成可完成部分。

### 14.5 全局工具输出预算

ToolMessage 进入模型上下文前统一检查大小：

- 小结果原样保留。
- 大结果生成确定性的结构摘要和有界头尾样本。
- 完整内容写入应用数据区的当前 Run 内部结果目录。
- 通过只读虚拟 `run-output/...` 路径允许模型使用 `read_file` 续读。
- 内部结果目录不进入项目文件树、搜索结果或 Diff。
- 外置失败时回退为明确标记的有界截断，不静默丢失内容。

摘要优先识别 JSON、CSV/TSV、XML/YAML 和普通文本结构，不额外调用 LLM。

用户验收：超大 JSON、命令日志和 MCP 输出都不会撑爆上下文，Agent 能根据摘要定位并读取关键段。

### 14.6 Token、轮次与终止原因

累计主 Agent 和子 Agent 的 input/output/total Token 及模型轮次：

- 软阈值提醒模型停止扩张并形成结论。
- 硬阈值禁止新的工具调用，保留已生成的可用正文。
- Run 记录 `token_capped`、`turn_capped` 或 `loop_capped`。
- 子 Agent 把停止原因和最后可用部分结果返回给主 Agent。
- 页面通过正式终止事件展示原因，不把预算结束显示成网络失败。

用户验收：达到任一上限时 Run 能正常终止、输入框恢复、刷新后原因仍可查看。

### 14.7 回归复测与调参

重新运行 14.1 的全部任务。只有满足以下条件才结束第 14 阶段：

- 复杂任务完成率提高。
- 重复调用和普通工具失败可以稳定收敛。
- 简单任务的无效工具调用没有增加。
- P95 时延和 Token 消耗没有不可接受的回退。

阈值根据 Mini Deer 的真实模型和任务结果调整，不直接复制 DeerFlow 默认值。

## 6. 第 15 阶段：可配置专用子 Agent

### 15.1 注册表与 task 契约

定义子 Agent 配置：

```text
name
description
system_prompt
model
tools
disallowed_tools
skills
max_turns
timeout_seconds
```

`task` 显式选择子 Agent。第一批只提供 `research` 和 `project-reader`，避免一次引入过多角色。

用户验收：同一个任务可以明确选择两个角色，未知角色返回稳定错误。

### 15.2 权限交集

子 Agent 的真实工具集合必须等于：

```text
父 Run 当前可用工具 ∩ 子 Agent 白名单 ∩ 活动 Skill allowed-tools
```

文件 Scope、Project 身份和执行环境由父 Run 冻结传入；子 Agent 不能扩大目录范围、递归调用 `task`
或直接向用户澄清。

用户验收：project-reader 能读取当前项目但不能访问根外路径；被禁止的工具既不出现在模型 Schema，
也不能绕过执行层调用。

### 15.3 Coding 读测闭环

- `project-reader` 可以列出、搜索和读取项目文件。
- `test-runner` 可以在同一冻结 Project 的 Docker 沙箱中执行检查。
- 写文件继续由主 Agent 串行完成，避免并发子 Agent 修改同一工作区。

用户验收：主 Agent 并行委派代码定位和测试诊断，再依据两个结果完成一次真实修复。

### 15.4 生命周期与部分结果

每个子任务具有 pending/running/completed/failed/cancelled/timed_out，附带 stop_reason、耗时、Token
和最后可用部分结果。父 Run 取消必须传播；同批一个子任务失败不能抹掉其他成功结果。

用户验收：并发执行中分别验证成功、失败、超时和父 Run 取消，刷新后状态一致。

### 15.5 前端可观察性

现有执行过程增加 Agent 名称、状态、耗时、停止原因和结果摘要，并从 RunEvent 恢复。

阶段验收：使用 14.1 的多文件任务对比，主 Agent 盲目读取减少，最终实现和测试仍然正确。

## 7. 第 16 阶段：按需工具与 Skills 扩展

### 16.1 Deferred Tool Catalog

第一版只延迟 MCP 工具。基础 Prompt 仅列经过安全转义的名称和短描述，不向模型绑定完整 Schema。
内置核心工具保持常驻，避免简单任务多一次发现调用。

用户验收：配置 20 个以上假 MCP 工具时，默认模型请求不携带它们的完整 Schema。

### 16.2 tool_search 与提升状态

`tool_search` 支持按准确名称和关键词返回少量完整 Schema。已提升工具记录在图状态中，并使用 catalog
hash 隔离工具目录版本。

- 未提升工具在模型可见层隐藏。
- 未提升工具在执行层失败关闭。
- 主 Agent 与子 Agent 复用相同发现规则。
- 工具改名或 Schema 改变后不能继承旧提升状态。

用户验收：工具经发现后可以调用并跨刷新恢复；目录变更后旧提升记录失效。

### 16.3 可信路由提示

为少数领域工具配置服务端可信关键词，用于候选排序或自动提升。外部 MCP 的名称、描述和结果仍是
低信任数据，不能成为系统指令。

用户验收：20 个以上工具中能够稳定选择目标工具，Schema Token 明显低于全部绑定基线。

### 16.4 用户 Skills 最小闭环

支持本地安装/启停、frontmatter 校验、资源文件只读加载和 allowed-tools 交集。第一版不做在线市场、
远程下载或自动生成 Skill。

用户验收：带参考文件的自定义 Skill 启用后生效，禁用后不污染普通 Run；主/子 Agent 的权限一致。

## 8. 第 17 阶段：线程级 Goal mode

### 17.1 Goal 状态与接口

Thread checkpoint 保存 objective、continuation_count、max_continuations、no_progress_count 和最近评估。
提供设置、查询与清除接口，刷新和服务重启后可恢复。

用户验收：设置、替换、查询和清除目标均正确，同一 Thread 恢复后目标不丢失。

### 17.2 独立完成评估

每次可见 Run 结束后，用小型非思考模型只依据用户可见证据返回：

```text
satisfied
blocker
reason
evidence_summary
```

blocker 至少区分 missing_evidence、needs_user_input、run_failed、external_wait 和 goal_not_met_yet。
缺少证据时失败关闭；澄清、外部等待和 Run 失败不会自动续跑。

用户验收：完成任务会保留带证据的“已完成”状态；需要输入或外部等待时准确暂停，并提供明确恢复入口。

### 17.3 有界隐藏续跑

只有 blocker 为 `goal_not_met_yet` 时才注入内部 continuation 消息。续跑受以下边界共同限制：

- 最大续跑次数。
- 连续无进展熔断。
- Token 和模型轮次预算。
- 用户取消。
- 用户新消息或清除/替换 Goal 的并发竞争。

旧评估不能覆盖新目标或新用户消息。

用户验收：一个需要“定位 → 修改 → 测试 → 修复 → 再测”的任务无需用户反复说“继续”；连续无进展
时会停止。

### 17.4 页面状态与恢复

页面显示活动目标、续跑次数、独立“评估中”阶段、最近评估和停止原因，并按状态提供执行、暂停、恢复、
替换和清除入口。Goal 内部消息不伪装成用户输入，Goal 状态通过 Run SSE 实时同步，产品历史只展示用户
需要理解的状态和结果。所有写操作携带 revision，陈旧操作不得取消或覆盖较新的 Goal。

用户验收：运行中停止、显式恢复、刷新恢复、完成留痕和错误暂停都与后端状态一致。

## 9. 总体验收指标

| 维度 | 验收要求 |
| --- | --- |
| 任务完成率 | 固定基准中的复杂调研和 Coding 任务相对 14.1 基线有可复现提升 |
| 循环质量 | 重复调用、无结果和近似重复输出均能在阈值内换策略或停止 |
| 上下文成本 | 20+ MCP 工具时不默认携带全部 Schema；超大结果不会直接进入模型上下文 |
| 子 Agent | 能在冻结的 Project Scope 内完成读/测任务，失败、超时和取消可恢复 |
| Goal mode | 能自动完成多步闭环，并在缺输入、外部等待或无进展时停止 |
| 简单任务 | 不因新增编排能力而滥用 Todo、子 Agent、tool_search 或额外模型调用 |

每个编号仍是一个可以立即运行验证的原子功能点。实现和自动化检查完成后必须暂停，由用户执行对应
验收；确认通过后才能进入下一个编号。

## 10. DeerFlow 源码学习地图

下列路径相对于 `D:/project/agentstudy/deer-flow/backend/packages/harness/deerflow/`：

| 主题 | 主要入口 |
| --- | --- |
| 中间件组装顺序 | `agents/lead_agent/agent.py`、`agents/factory.py`、`agents/features.py` |
| 工具异常与结果元数据 | `agents/middlewares/tool_error_handling_middleware.py`、`tool_result_meta.py` |
| 循环与停滞 | `agents/middlewares/loop_detection_middleware.py`、`tool_progress_middleware.py` |
| 工具输出预算 | `agents/middlewares/tool_output_budget_middleware.py`、`tool_output_synopsis.py` |
| Token 与终止 | `agents/middlewares/token_usage_middleware.py`、`token_budget_middleware.py`、`terminal_response_middleware.py` |
| 子 Agent | `subagents/config.py`、`registry.py`、`executor.py`、`builtins/`、`tools/builtins/task_tool.py` |
| 工具发现 | `tools/builtins/tool_search.py`、`agents/middlewares/deferred_tool_filter_middleware.py`、`mcp_routing_middleware.py` |
| Skills | `skills/catalog.py`、`parser.py`、`permissions.py`、`projection.py`、`agents/middlewares/skill_activation_middleware.py` |
| Goal mode | `agents/goal_state.py`、`runtime/goal.py`、`runtime/runs/worker.py` |

各功能点开始实施时仍需阅读对应测试和当前源码，确认 DeerFlow 基线是否变化；本文的路径索引不能替代
逐项源码对照。

## 11. 后续候选

完成第 14—17 阶段后，再根据基准数据决定是否投入图片理解、持久上传、Artifact 交付、浏览器自动化、
后台任务、MCP 长任务或远程 Sandbox。这些能力会扩大任务范围，但不能替代循环收敛、专用委派和
目标续跑；核心完成率没有数据改善前，不因 DeerFlow 已有对应模块而直接复制。
