# Mini Deer Agent 新窗口交接

> 交接时间：2026-09-03。
>
> 当前停止点：用户明确停止前端优化，转入「项目工作区、读取管理本地文件夹、Agent Coding」。已建立 [第 13 阶段独立计划](docs/plans/project-workspace-coding-stage.md)，须对照同级 DeerFlow 源码学习。本轮仅规划、未实现；等待用户审阅后从 13.1 开始。旧草案 `project-workspace-file-tools.md` 保留参考，不代表直写原目录已获确认。下文第 12 阶段及“等待指定 12.19”内容作为历史，不覆盖本条。

## 1. 新窗口先做什么

按顺序读取：

1. `PROJECT.md`：稳定架构规则、功能点编号和强制学习流程，尤其是第 18 节。
   随后读取 `docs/plans/project-workspace-coding-stage.md`：当前阶段目标、DeerFlow 对照、原子顺序、安全门槛与待确认决策。当前不要按旧路线继续前端优化或实现 12.19。
2. `docs/plans/agent-capability-roadmap.md`：当前 Agent 能力战略路线和明确留白项。
3. 本文件：当前停止位置、用户偏好和下一步操作。
4. `LEARNING.md` 末尾：已经验证的 11.6、11.7、12.1、12.2、12.3、12.4、12.5、12.6、12.7、12.8、12.9、12.10、12.11、12.12、12.13、12.14、12.15、12.16、12.17、12.18。
5. `WORKPLAN.md` 顶部当前状态：只用于核对进度；其中较早的“实施路线”和“下一功能 11.7”等文字属于过期历史，不能覆盖新路线。

然后执行只读检查：

```powershell
git status --short
```

当前工作树有大量用户和其他模型留下的未提交修改，全部视为用户资产。不要重置、覆盖或顺手格式化无关文件。`docs/plans/agent-capability-roadmap.md` 当前还是未跟踪的新文件，也必须保留。

## 2. 当前主线

Agent 能力战略顺序以 `docs/plans/agent-capability-roadmap.md` 为准：

1. System Prompt：已完成 12.1。
2. Plan mode：已完成 12.2。
3. Clarification：12.3 后端闭环、12.4 v1 结构化交互、12.5 v2 基础表单、12.6 全部扩展字段均已完成并验证。
4. Sub-agent：12.7 单个同步委派、12.8 受控并发多委派均已完成并验证。
5. Skills：12.9 内置发现与显式激活、12.10 受控自动激活、12.11 专用工具与 allowed-tools 最小策略均已完成并验证。
6. Context：12.12 动态日期/时间、12.13 摘要触发与历史压缩、12.14 Durable Context 均已完成并验证。
7. Memory：12.15 本地单用户显式 CRUD 已完成并验证；自动提取、多用户和语义检索后置。
8. MCP：12.16 静态可信配置、stdio/HTTP、隔离发现、状态接口和主图注入已完成并验证。
9. 健壮性：循环检测与工具输出预算按用户要求后置；不要自动把它们指定为 12.17。

`PROJECT.md` 维护稳定规则；路线文档维护战略顺序；`WORKPLAN.md` 维护当前功能点与进度；`LEARNING.md` 只记录用户已经验证的结论；`HANDOFF.md` 只负责跨窗口恢复。

不要因为旧 `WORKPLAN.md` 或旧聊天记录里还有可靠性待办，就插回 Last-Event-ID、SSE 重放、多 Worker、部署或完整文件平台。用户已明确要求优先推进 Agent 业务能力。

## 3. 用户协作规则

- 用户要求在当前对话窗口**对照源码详细讲解**，不能只给概念摘要。
- 每个功能点必须先展示 DeerFlow 对应源码、Mini Deer 当前源码和完整调用链，再进入实现。
- 路线文档已经存在，不要重复创建另一份设计文档。用户说“继续”时，直接进入下一功能点的源码对照和具体目标确认。
- 每次只实现一个可以立即运行验证的原子功能点；用户确认前不得继续下一个。
- 功能点只使用连续数字编号，禁止 `A/B`、`12.3a` 等字母后缀。
- 自动化检查不能替代真实浏览器和真实模型验证。
- 只有用户明确回复验证成功后，才能把源码解读、运行结果和结论写入 `LEARNING.md`。
- 用户的真实运行结果优先于终端测试结果；发现问题时暂停新功能，先修复当前功能。
- 新增源码和测试需要准确中文注释，库名、协议名和标识符保留英文。

## 4. 最近完成功能：12.16 MCP 工具接入（已验证）

12.16 对照 DeerFlow `config/extensions_config.py`、`mcp/client.py`、`mcp/tools.py`、
`mcp/cache.py`、`mcp/session_pool.py` 与 Gateway 配置路由。DeerFlow 已包含配置热更新、stdio
会话池、OAuth、路由提示、长任务和管理 API；Mini Deer 只抽取当前简单 Agent 真正需要的工具
发现与注册主链，没有复制完整扩展平台。

新增 `mini_deer_agent.mcp` 包和 `langchain-mcp-adapters>=0.3.2,<0.4.0`。独立 JSON 使用
`mcpServers`，第一版支持 `enabled`、`stdio(command/args/env)` 与 `http(url/headers)`；只在
env/header 值中解析环境变量引用。默认 `mcp_servers.json` 不存在表示未配置，禁用项可以保留
尚未完成的命令或密钥配置。

FastAPI lifespan 按服务器并行执行工具发现并冻结进程级快照。每个服务器有独立默认 10 秒初始化
超时；失败服务器记为 `failed`，不阻断健康服务器或应用。`GET /api/v1/mcp/status` 只返回配置
是否存在、配置路径、服务器 transport/state/tool names 和有界错误，不回传命令、参数、env 或
headers。配置改动需要重启，没有缓存热更新。

`MultiServerMCPClient(tool_name_prefix=True)` 让工具使用 `<server>_<tool>` 名称。Mini Deer 在
模型绑定前再次校验安全字符集、服务器内重复、跨服务器重复和所有内置/动态工具冲突；一个服务器
出现名称问题时整组拒绝，避免部分注册。正常路径每次调用创建独立 session，不保留 stdio 状态；
上游异步工具额外补齐同步学习入口。

启动快照由默认 `RunStreamService` 传给 `build_agent_graph(mcp_tools=...)`，因此模型 schema、Prompt
可用工具清单、Skills 权限决策和 `ToolNode` 使用同一工具对象。普通 Run 可见 MCP；激活带
allowed-tools 的受限 Skill 后，MCP 只有被明确列入才可用。通用子 Agent 第一版不继承 MCP。

仓库提供 `mcp_servers.example.json` 和 `examples/mcp_learning_server.py`。真实 SDK 测试已完成
stdio 子进程的 `initialize → tools/list → tools/call`，并同时验证异步和同步调用；全量后端为
`237 passed`，compileall、pip check、`git diff --check` 通过。12.16 没有修改前端，沿用通用
工具活动展示。用户按状态接口与真实 Agent 调用完成验收并回复“已验证，先更新”。

明确留白：配置写 API/UI、热更新、持久 session pool、OAuth 自动刷新、MCP Resources/Prompts/
Roots、MCP 长任务、工具审批和对子 Agent 的 MCP 下放。循环检测也未在 12.16 实现。

### 上一功能：12.15 本地单用户长期 Memory 显式管理（已验证）

12.15 对照 DeerFlow `agents/memory/manager.py`、`agents/memory/tools.py`、
`memory_middleware.py`、`summarization_hook.py`、DeerMem storage/retrieval 与 Prompt 注入链路。
DeerFlow 同时支持工具驱动与自动抽取，并带多用户、Markdown facts、FTS5/BM25、容量/陈旧度
治理和多后端；Mini Deer 只采用用户显式管理的工具契约，没有复制自动抽取与生产级存储体系。

`application.sqlite` schema 升级到 v7，新增全局 `memory_facts`。Memory 不带 Thread 外键，
因此跨 Thread、进程重启和 Thread 删除持续存在；它也不进入 LangGraph checkpoint。领域对象
包含稳定 `fact_id`、正文、九类 category、0—1 confidence、固定 `source=manual` 和创建/更新
时间。正文最长 2000 字、查询最长 500 字、单次返回 1—50 条。

仓储用 `content.strip().casefold()` 生成唯一 key；数据库 UNIQUE 约束同时保护新增、更新和并发
重复写入。查询使用 `instr(content_key, ?)` 做大小写无关的字面包含匹配，`%`、`_` 不会变成
LIKE 通配符；空查询按最近更新时间列出。更新只修改显式字段并保留创建时间，缺失 fact 或
重复正文返回稳定领域错误，删除为物理删除且不存在时不伪装成功。

主 Agent 新增 `memory_search/add/update/delete`。正式 FastAPI lifespan 把同一个业务仓储注入
`RunStreamService` 和主图，模型 schema 与 ToolNode 复用同一工具对象；异步调用通过
`asyncio.to_thread` 访问 SQLite。未注入 MemoryStore 的独立学习图不会看到四个工具，也不会
获得 Memory Prompt。子 Agent 不继承 Memory 能力。

Prompt 升级到 `mini-deer-agent/system/v16`，且仅在完整四工具真实注册时加入
`<memory_policy>`：历史偏好/纠正/约束可能相关时先搜索；只有用户明确要求记住、修改或忘记
时才能写改删；普通对话不得静默保存。全部事实仍通过低信任 ToolMessage 返回，不能覆盖系统
规则或扩张权限。Mini Deer 没有把所有 Memory 自动注入每轮上下文。

TDD 覆盖跨仓储重开、跨 Thread、Thread 删除不级联、空查询/分类/字面匹配、重复与非法写入、
CRUD 稳定 JSON、异步工具、可选 registry、完整主图注入和条件化 Prompt。最终结果为后端
`224 passed`，compileall、pip check、SQLite smoke 与 `git diff --check` 通过；ruff 未安装，
12.15 未修改前端。

用户按真实模型/UI 清单确认：显式 `memory_add` 后新 Thread 能以 `memory_search` 读回；
`memory_update` 后新 Thread 只使用新值；普通“喝咖啡”陈述没有触发写入；显式
`memory_delete` 后再次跨 Thread 查询无结果。用户随后明确回复“已验证”。

12.15 明确没有实现自动抽取、敏感信息分类器、多用户隔离、向量检索、远程 Memory 后端、
事实自动注入或管理页面。随后 12.16 已按用户决定转为 MCP 接入，循环检测继续后置。

### 上一功能：12.14 Durable Context 压缩后关键状态续接（已验证）

12.14 对照 DeerFlow 的 `durable_context_middleware.py`、`delegation_ledger.py`、
`skill_context.py`、`thread_state.py` 以及 Todo 上下文丢失恢复测试。DeerFlow 会把摘要、委派台账
和已读取技能引用保存为独立 ThreadState 通道，并在模型调用时使用可信 System 规则加隐藏
低信任 Human 数据临时注入；Todo 则由独立 state 和 middleware 恢复。

Mini Deer 新增 `agents/durable_state.py` 与 `agents/middleware/durable_context.py`。
`MiniDeerAgentState` 现在除 `messages/summary_text` 外还保存 `delegations/skill_context/todos`。
模型节点在摘要删除旧消息前扫描协议：task 发出后立即形成 `in_progress`，配对 ToolMessage 后
更新为终态并保存有界简述与 SHA-256；自动技能必须有 AI 调用、成功 ToolMessage 和可信
`skill_activation` 生产者元数据，显式 slash 则从可信 catalog 取引用；Todo 的调用参数与成功
结果必须是完全匹配的合法完整快照。

委派台账最多 50 条且终态不回退；技能引用最多 8 条，只含名称、描述和
`builtin://.../SKILL.md`，绝不复制正文；Todo 保留最近完整快照。模型视图只在原始结构化来源
已被压缩时注入数据，所有正文先转义且整体限制在 8000 字符，不写回 messages、SSE 或产品
历史。`examples/print_thread_context.py` 已同时显示三个 Durable 通道。

Mini Deer 没有照搬 DeerFlow 的跨 Run 技能权限语义。每条状态带 Human turn ID：只有当前
用户回合的可信技能引用可以恢复已激活正文和 allowed-tools；新 Human 回合中的旧引用只是
历史观察，不能自动激活。历史委派可用于续接，但不占新 Run 六次预算，用户要求重试、刷新或
重新核验时仍可再次执行。子 Agent 没有 task/skill/todo 工具，因此不增加无效 durable 通道；
它继续使用 12.13 的一次性摘要契约。

Prompt 升级为 `mini-deer-agent/system/v15`。TDD 覆盖严格提取、伪造拒绝、终态不回退、容量
上限、压缩集成、同步/异步一致、当前技能恢复、下一 Run 失效和 SQLite 重启。最终后端
`213 passed`，compileall、pip check 和 `git diff --check` 通过；未修改前端。用户按真实
模型/UI 清单确认摘要后结构化状态可续接、普通新 Run 不继承旧技能、既有委派没有无故重复，
并明确回复“已验证继续”。

12.14 没有增加长期 Memory、模型自动记忆、跨用户命名空间、后台委派或子图 checkpoint。
12.15 后续已完成本地单用户长期 Memory 的显式写入、读取、修改和删除。

### 上一功能：12.13 上下文摘要触发与历史压缩（已验证）

12.13 对照 DeerFlow 提交 `a5acc25d` 的 `summarization_middleware.py`、
`runtime/context_compaction.py`、Lead/Sub-agent 组装、Durable Context 注入位置和摘要测试。
Mini Deer 没有复制手动 `/compact`、专用摘要模型或 provider 精确 tokenizer；本功能只实现
自动 checkpoint 压缩，并保持 application 产品历史完整。

新增 `MiniDeerAgentState.summary_text`、`ContextSummaryPolicy` 与 `ContextSummarizer`。主图和
通用子图都在模型节点内部先检查消息数/token 数 OR 阈值；成功时使用带 `TAG_NOSTREAM` 的
当前 Run 模型生成累计摘要，以 `RemoveMessage(REMOVE_ALL_MESSAGES)` 原子替换旧消息并保留
近期完整 Human 回合。失败、空摘要或无法形成安全分区时不删除任何历史。产品当前默认预算为
约 50000 tokens 或 40 条消息，保留至少 10 条，摘要输入约 25000 tokens；环境变量可覆盖。

模型请求把 `summary_text` 转义后放入隐藏、低信任的 HumanMessage；SystemMessage 只包含如何
使用摘要的可信规则。Prompt 升级为 `mini-deer-agent/system/v14`。摘要模型输出与删除指令不会
进入 SSE；SQLite checkpoint 可跨重启恢复，而 `application.sqlite` 继续提供全部页面历史。

TDD 覆盖阈值、完整回合、累计摘要、转义、失败开放、同步/异步主图、子图、SQLite 重启以及
产品事件隔离。当前自动化结果为后端 `204 passed`，compileall 与 `git diff --check` 通过。
真实线程 `contex压缩测试` 已观察到页面历史 90 条、checkpoint 摘要 2677 字、近期原文 42 条；
压缩分界为“帮我查一下北京交通大学计算机学院的考研情况”。只读检查脚本位于
`examples/print_thread_context.py`，支持按标题/ID、精简/完整模式解码最新 checkpoint。

12.13 没有实现手动压缩、长期 Memory、Artifact、精确 provider tokenizer 或 Durable
Context；其中 Durable Context 已由随后完成的 12.14 独立实现并验证。

### 上一功能：12.12 动态日期/时间上下文（已验证）

12.12 对照 DeerFlow 提交 `a5acc25d` 的 `dynamic_context_middleware.py`、
`system_message_coalescing_middleware.py`、Lead/Sub-agent 组装位置及相关测试。DeerFlow 为长寿命
图使用带服务端来源标记的隐藏 SystemMessage，按会话冻结日期、跨午夜追加更新，并把可受
用户影响的 Memory 分离为 HumanMessage；严格 provider 前再合并为单一首位系统消息。

Mini Deer 已有 `prepare_model_messages()` 的单一 SystemMessage 边界，而且每个产品 Run 都
重新构图，因此没有复制持久化提醒、消息 ID 交换、跨午夜扫描或 SystemMessage 合并中间件。
新增 `agents/middleware/dynamic_context.py`：每次主 Agent 和通用子 Agent 模型调用都从宿主
aware clock 读取时间，把 ISO 日期时间、日期、时间、中英星期、时区名称和明确 UTC 偏移
追加为服务端可信 `<dynamic_context source="runtime">`。时区名称会转义，naive datetime
直接失败；默认使用 `datetime.now().astimezone()`，当前宿主实测为 `UTC+08:00`。

动态区块在技能激活和 allowed-tools 权限投影之后加入，再由既有消息边界形成唯一首位
SystemMessage。它不会进入 MessagesState、checkpoint、application SQLite、历史 API 或
前端；同 Thread 的下一 Run 和同 Run 工具循环都会重新读取时钟。构图、task 和子图入口均
支持注入测试时钟。Prompt 升级为 `mini-deer-agent/system/v13`，要求相对时间以 Runtime
事实为准，不要只为确认宿主当前时间联网，也不能把宿主时区冒充其他地区时区。

TDD 覆盖格式、时区转义、naive 时间拒绝、主图跨 Run 刷新、同步/异步一致、技能与权限
共存、子 Agent 注入、唯一系统消息和 checkpoint 不污染。自动化结果为后端 `190 passed`；
Python compileall、pip check 和 `git diff --check` 通过。该功能没有修改前端。用户按真实
模型/UI 验收步骤完成当前日期时间、刷新与内部标签不可见检查后，明确回复“已验证”；完整
结论已写入 `LEARNING.md`。

12.12 没有增加 IANA `tzdata`、可配置时区、任意城市时间换算、日程提醒、摘要、Durable
Context 或 Memory；其中摘要已由随后完成的 12.13 独立实现，Durable Context 仍留给 12.14。

### 4.1 上一功能：12.11 Skills 专用工具与 allowed-tools 最小策略（已验证）

12.11 对照 DeerFlow 提交 `a5acc25d` 的 frontmatter/type/parser、`skills/tool_policy.py` 与
`skill_tool_policy_middleware.py`，没有把权限限制实现成 Prompt 文案。Mini Deer 的
`BuiltInSkill` 新增可选 `allowed_tools`，严格区分省略字段、显式空列表和非空列表；非法
类型、非字符串、空白、非法名称、重复项以及构图时发现的未知注册工具都会让受信任发布
资产失败。

工具注册拆为普通 `get_agent_tools()` 和专用 `get_skill_tools()`。仅安装/可发现的
`weather-briefing` 不会让普通模型看到 `get_weather`；显式 slash 或严格自动激活后，
`SkillToolPolicyDecision` 才按执行 registry 顺序生成框架控制工具与声明工具的最小集合。
旧 `structured-explainer` 省略字段，保留普通主 Agent 工具，但不能得到专用天气工具。

同步和异步 model 节点每次调用都用原始 chat model 重新 `bind_tools()`，并把 v12 的
`<active_skill_tool_policy>` 实际清单投影进本次 SystemMessage。执行前的
`skill_policy_block` 路由复核同一决策；包含任意越权调用的批次零执行，分别返回稳定的
`skill_tool_not_allowed` 和 `skill_policy_batch_rejected`，防止隐藏 Schema 被伪造调用绕过。
路由优先级为 clarification → skill activation → skill policy block → delegation → tools。

首个 `/weather-briefing` 声明 `allowed-tools: [get_weather]`，复用既有 Open-Meteo 同步、
异步和取消链。Prompt 升级为 `mini-deer-agent/system/v12`；前端继续复用通用工具卡与历史
恢复，无需天气专用组件。

自动化结果为后端 `183 passed`、前端 27 files / `178 passed`；Python compileall、pip
check、TypeScript、ESLint、Prettier、生产 build、隔离 wheel 中两个 `SKILL.md` 检查和
`git diff --check` 通过，工作区无 `build/`，当前环境未安装 Ruff。用户已在真实页面确认：
普通天气问题走自动激活与天气工具，slash 天气请求直接调用专用工具，下一普通 Run 不继承
天气权限，旧技能与搜索/澄清/委派未回退；随后明确回复“已验证”。完整结论已写入
`LEARNING.md`。

12.11 没有实现多活动技能并集、自定义/外部技能、启用状态、支持资源、动态 registry、
tool search、secrets、子 Agent Skills 或跨摘要 Durable Context。它之后的 12.12 动态
日期/时间上下文现已完成并验证。

### 4.2 上一功能：12.10 Skills 受控自动激活（已验证）

12.10 对照 DeerFlow 提交 `a5acc25d` 的 `describe_skill → read_file → skill_context →
skill_tool_policy` 链路后，没有采用静默关键词路由。Mini Deer 新增模型可见的
`activate_skill(name)`：模型只能依据基础 Prompt 中的名称和描述自主选择；调用在现有
工具卡、RunEvent、application SQLite 与 checkpoint 中可审计，成功结果只含稳定元数据，
不返回技能正文。

`skills/automatic.py` 把成功激活写成带生产者元数据的 ToolMessage。Runtime 只接受当前
最新 HumanMessage 之后、`AIMessage.tool_calls` 与 ToolMessage 通过 `tool_call_id`、工具名、
技能名和元数据版本严格配对的记录；随后才从当前 Run 的受信任 catalog 快照把正文投影进
SystemMessage。激活状态不依赖全局可变变量，因此新 Run、其他 Thread 和空技能目录均不会
继承旧状态。

主图路由优先级升级为 clarification → skill_activation → delegation → 普通 tools。技能
激活必须独占一次模型响应；同批普通工具、task 或额外激活全部获得明确 skipped
ToolMessage。同 Run 重复同名激活幂等，切换或叠加另一技能失败关闭；用户显式 slash 拥有
最高优先级。Prompt 升级为 `mini-deer-agent/system/v11`，明确高置信匹配、简单请求不误用、
独占批次、每 Run 一个和 slash 优先规则。

自动化结果为后端 `167 passed`、前端 27 files / `178 passed`；Python compileall、pip
check、TypeScript、ESLint、Prettier、生产 build、wheel 中 Python 模块与 SKILL.md 检查和
`git diff --check` 通过，当前环境未安装 Ruff。用户按真实页面验收清单确认：无 slash 的
高匹配技术解释出现 `activate_skill` 工具卡并使用四段结构；下一普通 Run 不继承；显式
slash 仍直接激活且不额外调用工具。用户随后明确回复“已确认”，结论已写入
`LEARNING.md`。

12.10 当时没有实现的专用工具与 allowed-tools 已由 12.11 完成；自定义/外部技能、启用
状态、支持资源、多个同时激活技能、Durable Context、请求级 secrets 和子 Agent Skills
仍是明确留白。

### 4.3 上一功能：12.9 Skills 内置技能发现与显式激活（已验证）

12.9 新增只读 `BuiltInSkillCatalog`，每个产品 Run 构图时从随包发布的直接子目录发现
`SKILL.md`。名称必须使用小写 hyphen-case 并与目录一致；描述、文件大小、正文、符号链接
和根目录越界均有严格边界。PyYAML 已成为直接依赖，setuptools package-data 和隔离 wheel
构建已确认内置技能文件进入发布包。

Prompt 升级为 `mini-deer-agent/system/v10`，基础 `<skills>` 只列技能名称与描述，明确
禁止自动激活。严格 `/skill-name 任务` 只解析最新普通用户消息；命中后把只读内置正文
投影到当前 Run 的 SystemMessage，并把模型视图中的用户正文规范化为 slash 后的任务。
原始 MessagesState、SQLite 历史和页面消息不写入技能正文或 `<activated_skill>`。

同 Run 的每次模型调用都会重新生成技能投影，因此工具循环后的最终回答继续受约束；下一
Run 追加普通 HumanMessage 后旧技能自动失效。未知技能和空任务直接产生页面可见 ai_delta，
不调用模型。首个 `/structured-explainer` 技能使用“一句话结论、通俗解释、最小例子、
常见误区”四段结构。

自动化结果为后端 `158 passed`、前端 27 files / `178 passed`；Python compileall、pip
check、TypeScript、ESLint、Prettier、生产 build、隔离 wheel/package-data 检查和
`git diff --check` 通过，当前环境未安装 Ruff。用户已在真实页面确认技能发现、显式四段
结构、刷新无内部上下文、下一 Run 失效、未知技能和空任务错误均正常，并明确回复“已验证”；
结论已写入 `LEARNING.md`。

12.9 当时未实现的受控自动激活已由 12.10 完成，技能专用工具与 allowed-tools 已由 12.11
完成；自定义技能、启用/禁用、支持资源、secrets、子 Agent Skills 或跨 Run 激活仍留白。

### 4.4 上一功能：12.8 Sub-agent 受控并发多委派（已验证）

12.8 把主 Agent 的委派能力扩展为每个模型响应最多 3 个并发 task、每个产品 Run 累计
最多 6 个。`DelegationBudget` 与每 Run 新构建的主图共享生命周期，批次先原子预留名额，
再由同步 ThreadPoolExecutor 或异步 asyncio.gather 并发执行；完成结果始终按原始
tool_call 顺序交回主模型。

单个子 Agent 失败会转换为稳定 failed 结果，不阻断同批其他委派；父 Run 取消会传播并
清理全部子任务。task 与普通工具混用、第 4 个及之后的 task、Run 总量耗尽后的 task 都会
获得明确 skipped ToolMessage，分别使用 batch exclusive、concurrency limit 和 total limit
原因，保证每个 tool_call_id 完整结算。前端生产代码无需修改，新增 reducer 回归证明反序
到达的多个 task 结果仍能落到各自工具卡。

Prompt 已升级为 `mini-deer-agent/system/v9`，明确 3/6 限额、task-only 批次、独立任务
边界、最少委派、自包含 prompt 和结果核验。自动化结果为后端 `144 passed`、前端
27 files / `178 passed`；Python compileall、TypeScript build、ESLint、Prettier、生产
build 和 `git diff --check` 通过，当前环境未安装 Ruff。用户已在真实页面确认两个独立
task 卡、两项结果、主 Agent 综合、简单问题不委派和取消行为均正常，并明确回复“已验证”；
结论已写入 `LEARNING.md`。

12.8 当时未实现的内置 Skills 发现与显式激活现已由 12.9 完成；后台委派、可配置限额、
自定义子 Agent、跨恢复 Run 的 durable ledger、子图 checkpoint、Memory 和文件写入仍是
明确留白。

### 4.5 上一功能：12.7 Sub-agent 单个同步委派（已验证）

12.7 新增一次性 `task` 工具和无 checkpointer 的独立子图。主 Agent 每个产品 Run 最多
真正启动一次 `general-purpose` 子 Agent；参数只有 description、self-contained prompt
和固定 subagent_type。子图复用主模型配置，但只绑定 web_search、web_fetch，不接收主
对话历史，也不能递归 task、修改 todo 或向用户澄清。

主图路由优先级为 clarification → delegation → 普通工具。包含 task 的模型响应进入专用
节点，只执行第一个 task；同批其他调用全部获得 skipped ToolMessage，避免协议悬空。
子结果以稳定 `subagent_result` JSON 回到主模型，再由主 Agent 核验和综合。异步路径直接
等待子图 ainvoke，CancelledError 保持传播；异常结果脱敏，不泄露 provider 细节。

Prompt 已升级为 `mini-deer-agent/system/v8`。前端没有新增专用协议或组件，继续使用通用
工具卡和既有持久化链。自动化结果为后端 `140 passed`、前端 27 files / `177 passed`；
Python compileall、TypeScript build、ESLint、Prettier、生产 build 和 `git diff --check`
通过，当前环境未安装 Ruff。用户已在真实页面确认单个 task 工具卡、子结果、主 Agent
综合、子消息隔离以及简单问题不委派均正常，并明确回复“已验证”；结论已写入
`LEARNING.md`。

12.7 当时未实现的同一 Run 多 task 并发现已由 12.8 完成；自定义子 Agent、后台任务/进度、
子图 checkpoint、Skills/Memory 或文件写入仍是明确留白。

### 4.6 上一功能：12.6 Clarification v2 扩展字段类型（已验证）

12.6 一次补齐 number、date、multi_select、checkbox。后端 `ask_clarification` 现在支持
完整七种字段；select 与 multi_select 共用选项数量、唯一性和稳定 ID 规则，非选项字段
不得携带 options。前端值模型扩展为 string、number、boolean、string[]，number/date
使用原生输入控件，multi_select 使用 aria-pressed 按钮，checkbox 使用原生 checked。

checkbox 初始值显式为 false；required checkbox 只有勾选后才通过校验，可选 checkbox
的 false 则作为“否”进入摘要和 JSON。multi_select 在可读摘要中逗号连接，但在
`[values: {...}]` 中保持数组；回答仍复用 v1 text response，12.4 的完整持久化链路未变。

自动化结果为后端 `132 passed`、前端 27 files / `177 passed`；TypeScript build、ESLint、
Prettier、生产 build 和 `git diff --check` 通过。用户已在真实页面验证五字段表单、必填
拦截、全部控件、数组/布尔提交和刷新恢复，并明确回复“已验证”；结论已写入
`LEARNING.md`。

Clarification v2 的七种字段已经完整覆盖。当时保留的下一连续功能点 12.7「Sub-agent
单个同步委派」现已完成并验证；同一 Run suspend/resume 与多个未回答请求管理仍是明确
留白。

### 4.7 上一功能：12.5 Clarification v2 多字段表单（已验证）

12.5 在 v1 Human Input Card 上增加严格绑定 `version: 2 / input_mode: form` 的多字段
请求。后端 `ask_clarification` 支持 1—8 个 fields，当前字段类型为 text、textarea、
select；字段名必须唯一且安全，select 必须包含 2—8 个不重复选项，fields 优先于旧
options。前端 parser 执行相同的协议和安全校验，卡片提供应用内必填提示。

提交继续复用 v1 `human_input_response / text`，value 同时包含可读摘要和稳定
`[values: {...}]` JSON 映射。因此 12.4 的隐藏消息、request_id 精确关联、新 Run 继续、
SQLite/checkpoint 持久化和刷新恢复链路保持不变。

自动化结果为后端 `129 passed`、前端 27 files / `174 passed`；TypeScript build、ESLint、
Prettier、生产 build 和 `git diff --check` 通过。用户已在真实页面验证三字段表单、空提交
必填提示、填写提交和回答状态，并明确回复“已验证”；结论已经写入 `LEARNING.md`。

12.5 当时保留的 number、multi_select、checkbox、date 已由 12.6 完成并验证。

### 4.8 上一功能：12.4 Clarification 结构化交互（已验证）

12.4 已完成 DeerFlow 风格的 v1 Human Input Card：free text、选项按钮、其他回答、
`human_input_response`、`request_id` 精确关联、隐藏回答和刷新恢复。回答仍创建新 Run，
普通 Composer 保留为兼容入口。application SQLite 已迁移到 v6，在消息上保存
`hidden_from_ui` 与响应 JSON；LangGraph HumanMessage 的 `additional_kwargs` 保存相同
机器元数据。

自动化结果为后端 `124 passed`、前端 27 files / `171 passed`；TypeScript、ESLint、
Prettier、生产 build 和 `git diff --check` 通过。用户已按真实页面验收步骤确认正常，
结论已写入 `LEARNING.md`。

12.4 的 v2 基础多字段表单留白已经由 12.5 完成。

### 4.9 上一功能：12.3 Clarification 后端闭环（已验证）

当前实现已经完成：Prompt v7、`ask_clarification` 稳定请求 JSON、专用图结束
分支、`run_completed / clarification_requested` 终态，以及通用工具卡默认展开。
自动化结果为后端 `120 passed`、前端 24 files / `163 passed`，TypeScript、
ESLint、Prettier、生产 build、Python `compileall` 和 `git diff --check` 通过；
当前环境未安装 Ruff。用户已确认模糊问题先追问、普通回答新 Run 继续、刷新恢复和
简单明确问题不滥用澄清工具均正常；结论已经写入 `LEARNING.md`。

### 可观察目标

当用户给出缺少关键条件、存在多种高影响选择或可能误执行的请求时，Agent 调用 `ask_clarification`，展示一个明确问题并结束当前 Run，而不是自行猜测或继续执行。

用户可以通过普通输入框回答；回答在同一 Thread 创建新 Run，模型能根据已有消息继续任务。第一版不实现“同一个 Run 长期挂起后恢复”。

### 原子边界

12.3 只完成：

- `ask_clarification` 的后端工具契约和稳定结果结构。
- Prompt 中何时必须澄清、何时不应澄清的规则。
- 图执行遇到澄清调用后安全结束当前 Run，不再继续调用其他工具或生成假装已经执行的结果。
- 澄清问题能通过现有事件、持久化历史和通用工具展示被用户看到。
- 用户用普通 Composer 回答后，新 Run 能利用历史中的问题和回答继续。

12.3 暂不完成：

- 专用澄清卡片、选项按钮或表单。
- 前端 `human_input_response` 元数据和 `request_id` 精确关联 UI。
- 同一 Run 的等待状态、暂停/恢复协议。
- 多个未回答澄清请求管理。

以上内容是 12.3 完成时保留给 **12.4** 的历史边界，现已由 12.4 完成并验证。

### 先对照的 DeerFlow 源码

对照仓库：`D:\project\agentstudy\deer-flow`，当前基线提交 `a5acc25d`。

至少阅读并在窗口讲解：

- `backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py`
  - `wrap_tool_call()` 如何识别 `ask_clarification`。
  - 如何生成 `ToolMessage`。
  - `Command(goto=END)` 为什么结束当前图，而不是让工具循环继续。
- `backend/packages/harness/deerflow/agents/human_input.py`
  - `human_input_response` 的版本、`request_id` 和响应种类。
- `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`
  - 用户回答实际通过新的 `sendMessage()` 提交，不要误讲成同一 Run 原地恢复。
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`
  - Clarification First 的 Prompt 规则和强制场景。
- `backend/packages/harness/deerflow/tools/builtins/clarification_tool.py`
  - 核对当前提交中的工具参数契约，不要凭文档猜测。

### 先对照的 Mini Deer 源码

至少阅读：

- `src/mini_deer_agent/agents/main/graph.py`：当前手写 `model → tools → model` 循环和可插入结束条件的位置。
- `src/mini_deer_agent/tools/registry.py`：工具注册边界。
- `src/mini_deer_agent/agents/prompts/templates.py`：当前 Prompt v6 和 planning 规则。
- `src/mini_deer_agent/streaming/langgraph.py`、`projector.py`、`events.py`：工具调用、工具结果和 Run 终止如何投影为产品事件。
- `src/mini_deer_agent/application/run_stream.py`、`run_execution.py`：Run 如何持久化完成或中断。
- `frontend/src/features/chat/ui/ToolActivity.tsx`：12.3 如何先复用通用工具展示。
- `frontend/src/features/chat/model/use-chat-run.ts`：用户下一条消息如何创建新 Run。

源码讲解必须回答：

1. DeerFlow 为什么拦截工具调用并 `goto=END`。
2. Mini Deer 如果把它当普通工具执行，为什么可能再次进入模型循环。
3. 12.3 选择哪一个明确的 Run 终止事件和持久化状态。
4. 澄清问题如何从模型工具调用一路到达页面，并在刷新后仍可见。
5. 用户普通回复为什么能作为新 Run 延续上下文，以及第一版缺少哪些精确关联能力。

讲解完成并与用户确认边界后，再按测试驱动开始编码。

### 12.3 建议验证

至少准备三类固定问题：

1. 缺少关键对象，例如“帮我生成一份报告”，但没有主题和用途：应先追问。
2. 简单明确问题，例如“北京是中国的首都吗”：不应调用澄清工具。
3. 澄清后继续：回答 Agent 的追问，确认新 Run 能继续原任务，不重复询问已经回答的条件。

预期页面行为：能看到澄清问题；当前 Run 正常收敛；输入框仍可发送回答；刷新历史后问题和回答仍存在。

用户已完成以上验证并明确回复“确认正常”。

### 下一功能

当前按用户要求停在记录完成后，不自动开始新功能。下一连续编号是 12.19，主题必须由用户指定
或再次确认。工具循环检测和工具输出预算都已明确后置，不要仅依据旧路线直接开始。

## 5. 当前实现事实

- Prompt 当前版本：`mini-deer-agent/system/v16`。
- 主 Agent 被动工具包含 `web_search`、`web_fetch`、`write_todos`、`ask_clarification`、
  `activate_skill`、`task`、四个 `memory_*` 和启动时成功发现的 MCP 工具；专用 registry 另含
  `get_weather`，只有活动 `weather-briefing` 能把它加入模型 schema；子 Agent 只包含
  `web_search`、`web_fetch`。
- 12.2 的 `write_todos` 结果作为 `ToolMessage` 进入 checkpoint；前端显示状态清单。
- 12.18 当前自动化结果：后端 `239 passed`；前端 vitest 通过；typecheck / lint / build /
  `git diff --check` 通过。12.18 新增 `PatchedChatOpenAI` 捕获 reasoning_content，v8 迁移
  messages 加 reasoning 列；子 Agent 递归上限 8 → 20。
- 产品历史和长期 Memory 在 `data/application.sqlite`，LangGraph checkpoint 在
  `data/checkpoints.sqlite`；不要删除真实数据库。

## 6. 文件上传边界

现有能力：

- 支持 26 个 UTF-8 文本、代码和配置扩展名。
- 每条消息最多 3 个附件；单文件最多 32 KiB，总计最多 64 KiB。
- 附件正文会内联给模型；发送后随消息持久化，历史中可以展开查看正文。

明确留白：

- PDF 和图片解析。
- 完整 Artifact / 文件资产平台。
- 待发送附件的前端跨刷新持久化。
- 文件版本、生命周期和独立资产管理。

不要在 12.3 中顺手继续文件上传工作。

## 7. 运行环境

- Mini Deer：`D:\project\agentstudy\mini-deer-agent`
- DeerFlow：`D:\project\agentstudy\deer-flow`
- 后端：`http://127.0.0.1:8001`
- 前端：`http://127.0.0.1:5173`

后端启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn mini_deer_agent.api:app --host 127.0.0.1 --port 8001
```

启用仓库内 MCP 学习示例时先激活 venv，确保示例配置中的 `python` 指向安装了 MCP SDK 的解释器：

```powershell
.\.venv\Scripts\Activate.ps1
$env:MINI_DEER_MCP_CONFIG_PATH="mcp_servers.example.json"
python -m uvicorn mini_deer_agent.api:app --host 127.0.0.1 --port 8001
```

状态接口为 `GET http://127.0.0.1:8001/api/v1/mcp/status`。修改配置后必须重启后端。

前端启动：

```powershell
cd D:\project\agentstudy\mini-deer-agent\frontend
npm run dev
```

PowerShell 命令中不要复制提示符 `(.venv) PS D:\...>`。如果 5173 已被占用，通常表示现有 Vite 服务仍在运行，不要重复启动。

## 8. 安全与边界提醒

- 不读取、输出或写入 `.env` 中的真实 API Key。
- 不删除 `data/*.sqlite`，除非用户明确要求重置真实历史。
- 不把模型自称的身份当成实际 provider 证据。
- 不把 LangGraph checkpoint BLOB 当成产品历史 API。
- 当前不实现任意请求动态注册 stdio 命令、Sandbox、认证、多租户、部署、MCP 配置管理/热更新/
  OAuth/持久 session、Last-Event-ID、SSE 重放或多 Worker。
- 不主动提交、重置或清理用户现有 Git 改动。
