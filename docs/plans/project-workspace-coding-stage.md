# 第 13 阶段：项目工作区与 Agent Coding

> 状态：文件能力、Docker 命令、失败修复、Prompt v38 新功能闭环及检查结果审阅区均已验收；当前进行 13.18 文档与源码一致性收口。
>
> 日期：2026-09-03。
>
> 最新插入项：用户要求移除个人学习模式的工作区密码，简化为 Codex 式项目→会话侧栏。本轮已完成免密码接口、自动加载、五条会话及展开显示，用户已于 2026-09-03 完成页面验收。旧实现记录中的凭据/连接/锁定步骤仅供追溯，不再作为后续要求。
>
> 用户目标：前端体验优化到此为止，下一主线是建立项目工作区、读取与管理本地文件夹，让 Agent 完成真实 Coding 任务；必须对照 DeerFlow 源码学习。
>
> 用户已于 2026-09-03 要求沿用本文开发，无需另补设计，并明确全部文件工具应由普通对话与项目对话复用；2026-09-04 进一步澄清普通 Thread 在任何时候都应拥有读文件权限。Project Thread 默认使用项目根；用户本轮明确给出根外绝对路径时可访问该目标。安全与可靠性专项暂不推进。

## 1. 阶段目标与完成标准

本阶段不是再增加几个文件工具，而是建立下面这个可以反复使用的闭环：

```text
用户登记本地项目 → 打开文件树与源码 → 在项目内发起会话
  → Agent 检索并理解代码 → 提出具体修改 → 获得必要授权
  → 修改文件 → 在隔离环境运行测试 → 根据失败结果修复
  → 用户审阅 Diff → 应用到本地项目 → 下次会话继续
```

五项核心能力：

1. 项目与会话：保存项目目录，一个项目关联多个 Thread，项目身份独立于对话。
2. 文件理解：目录浏览、文件检索、带行号读取、项目规范与按需上下文。
3. 文件管理与编辑：创建、精确修改、重命名、受控删除；保留版本、审阅和恢复能力。
4. 受控执行：沙箱内运行检查/测试命令，具有审批、超时、取消和有界输出。
5. Coding 闭环：理解任务、修改、验证、修复、交付；每个结论对应真实文件和执行结果。

以上文件能力也适用于普通对话：普通 Thread 始终可以在服务端允许根内读取文件，无须先登记项目或为每个 Run 重新提供路径。Project 负责更窄的默认目录与持续项目上下文；工具和文件操作服务由两类对话共用。后续写操作仍按对应里程碑实施授权，本条不表示尚未开发的写入能力已经可用。

最终验收：在专门的样例项目中，Agent 能独立完成一个小功能和一个缺陷修复，展示实际 Diff、实际测试结果；刷新、重启后项目及历史可恢复；拒绝审批、停止运行或发生冲突时不损坏用户原文件。

本阶段只增加上述能力必需的 UI，不继续改造现有聊天视觉、COT 风格或通用侧栏体验。

## 2. 当前基线与既有草案

已具备并复用：

- FastAPI → Application Service → LangGraph 主图 → 工具 → RunEvent → SQLite/SSE 的执行链。
- Thread/Run 身份、历史恢复、取消、Event Store、Todo、澄清、Skills、Memory 和受控子 Agent。
- 前端紧凑 COT、输入框上方 Todo 和会话导航；文件操作继续作为紧凑步骤展示，不恢复工具小卡片。
- 文本附件能向模型内联有限内容，但附件上传不等于访问一个持久本地项目目录。

13.1—13.7、通用文件 Scope、文件能力、项目树自动刷新、Docker Provider、Project 根挂载、项目命令、失败修复、Prompt v38 自然语言小功能及可恢复的真实检查结果均已由用户验证。当前进行 13.18 文档与源码一致性收口。
本次明确进入新大阶段，按 `PROJECT.md` 第 18 节使用 **13.1 起的新课程编号**，不继续扩展第 12 阶段。

## 3. DeerFlow 源码学习地图

本次对照仓库：`D:/project/agentstudy/deer-flow`。
已核对基线：`a5acc25de6742b2166b3f41c97bd895822277b94`。实施前重新核对本地提交；如有变化，记录新基线，不假定以下行为永远不变。

下表中后端路径相对于 `backend/packages/harness/deerflow/`。表内结论来自本地源码，不依靠截图或工具名称猜测。

| 学习主题 | 源码入口 | 已核对的机制及 Mini Deer 取舍 |
| --- | --- | --- |
| 目录归属 | `agents/middlewares/thread_data_middleware.py`、`config/paths.py` | 按 Thread 解析 workspace/uploads/outputs；Mini Deer 增加持久 Project，不能把真实项目生命周期绑在 Thread 上 |
| 执行器抽象 | `sandbox/sandbox.py`、`sandbox/sandbox_provider.py`、`sandbox/middleware.py` | 文件/检索/命令统一接口，Provider acquire/get/release，异步获取，惰性初始化；借鉴职责分离，第一版只实现必要适配器 |
| 路径映射 | `sandbox/local/local_sandbox.py` | 映射后 resolve 并验证根目录归属，区分只读映射；Mini Deer 额外覆盖 Windows 盘符、junction、UNC 和文件身份竞争 |
| 文件工具 | `sandbox/tools.py`、`sandbox/search.py` | ls/glob/grep/read_file/write_file/str_replace、行范围和输出上限；对外保持小而清晰的工具契约，不照抄整个大模块 |
| 先读后写 | `agents/middlewares/read_before_write_middleware.py` | 内容哈希读取凭证、同路径临界区、写后凭证失效；源码有无法检查时 fail-open 的分支，Mini Deer 对真实代码修改采用失败关闭，不照搬此行为 |
| 命令权限 | `sandbox/security.py`、`sandbox/tools.py` 的 `bash_tool` | LocalSandbox 不是安全隔离，宿主 bash 默认关闭，显式开关才允许；Mini Deer 不启用任意宿主 Shell |
| 执行环境 | `sandbox/env_policy.py`、`community/aio_sandbox/` | 学习环境变量隔离与容器 Provider；实施时深入阅读，先做本地单实例，不引入远端调度、温池和 Redis 租约 |
| 文件变化 | `workspace_changes/scanner.py`、`recorder.py`、`diff.py`、`types.py` | 前后快照、哈希、增删改、Diff、敏感/二进制/超限标记；借鉴有界扫描，不把扫描期间所有变化都声称为 Agent 所写 |
| Run 归档 | `runtime/runs/worker.py`、`workspace_changes/api.py` | Run 生命周期集成变更记录，从事件查询历史；接入 Mini Deer 自己的 Run/Event Store，不另造并行执行链 |
| 前端变更读取 | `frontend/src/core/workspace-changes/{types,api,hooks}.ts`（仓库根相对路径） | 按 Thread/Run 查询并区分 available、truncated、diff_unavailable_reason；复用这些语义，不引入整个 Next.js 工作台 |

本次是阶段级源码对照，不声称已审计 DeerFlow 的全部实现。各功能实施时必须继续阅读对应函数和测试，尤其是 `test_sandbox_tools_security.py`、`test_local_sandbox_virtual_path_contract.py`、`test_read_file_line_range.py`、`test_sandbox_search_tools.py`、`test_workspace_changes.py`。

每个原子功能点统一交付：**展示 DeerFlow 调用链 → 讲清 Mini Deer 对应边界 → 测试与实现 → 自动化检查 → 用户真实验证 → 确认后写 LEARNING.md**。计划完成不等于任何功能已经验证。

## 4. 架构决策与待确认项

### 4.1 项目、工作副本、会话和执行的关系

```text
Project（用户登记的原目录，持久身份）
├── Workspace（受管工作副本，版本与权限）
├── Thread 1 → Run → 文件操作 / 审批 / 命令 / ChangeSet
└── Thread 2 → Run → 复用同一工作副本，独立对话上下文
```

- Project 可以指向 Git 仓库或普通文件夹；不要求先 git init。
- Thread 最多属于一个 Project；已产生历史的 Thread 不重新绑定另一个项目，避免旧上下文操作新目录。普通聊天继续允许 `project_id = null`。
- 每个涉及文件的 Run 在准入时确定访问上下文，包含目标文件/目录、版本、权限、执行器及环境配置；Project 为可选来源。执行中的范围不能随模型参数或前端选择变化；新增目标须经服务端授权并记录。
- 同一 Workspace 首版只允许一个活动 Coding Run；文件管理写入也通过同一写入仲裁。用户在外部编辑器的改动靠版本校验发现，不声称应用锁能锁住外部编辑器。
- 删除 Thread 不删除 Project 或用户文件；移除 Project 只是解除登记。工作副本及历史快照清理必须单独确认，绝不沿删除会话的级联链删除原目录。

### 4.2 本地目录入口

项目入口：用户在页面登记“后端运行机器上的绝对目录”，由后端校验并保存为 project_id；项目 API 使用项目 ID 和根内相对路径。普通对话入口：Thread 自动绑定后端配置的允许根集合，不创建隐式 Project，并以 `workspace-N` 虚拟路径访问。浏览器不能通过普通上传控件获得可由后端直接写回的任意目录句柄。

全部文件工具共用同一访问与操作服务。项目对话的相对路径默认以项目目录为基准；普通对话先列出 `workspace-N` 虚拟根，再使用虚拟相对路径。读取权限覆盖允许根并不自动授予修改或删除权限；后续副作用仍按操作等级授权和审批。

首版可使用“输入路径 + 受信任根目录下的目录浏览器”，不要求 Electron/Tauri 或桌面原生选择器。部署到远端后，该目录是服务器目录而不是浏览器所在电脑的目录，必须明确展示。

新增根目录是用户管理操作，不是 Agent 工具；不得让 LLM 自行登记磁盘根、用户目录或任意敏感目录。当前个人学习模式保留本地监听、Host/Origin 和允许目录检查，不要求工作区密码；项目随页面自动加载。

### 4.3 原目录修改策略：当前采用直接修改

| 方案 | 好处 | 成本 / 风险 |
| --- | --- | --- |
| 受管工作副本 + 审阅后应用回原目录（推荐） | 原目录不会被测试脚本或模型命令直接破坏；普通文件夹也能预览和恢复改动 | 需实现同步基线、冲突检测和应用流程；UI 必须区分“副本已改”与“原目录已更新” |
| 直接修改登记目录 | 和本地编辑器同步，使用路径直观 | 写入立即影响用户代码；即使命令在容器中，原目录可写挂载也允许删除整个项目；需更严格审批、备份与恢复设计 |

用户于 2026-09-04 明确项目根是默认授信范围，安全与可靠性专项暂不涉及。当前阶段采用直接修改登记目录和普通 Thread 允许根；上表工作副本方案留作未来重新进入安全专项时参考。

推荐方案下：

- 原目录作为导入与最终应用目标；不自动上传到第三方，也不把整个代码库一次塞给模型。
- 原目录按受控、有限扫描复制到应用自有数据区，保留每个纳入文件的基线哈希；保留用户未提交内容，不从 HEAD 擅自重建。
- 工作副本按 Project 持久复用；与宿主依赖目录隔离；日志、备份及数据库存储在代码树之外，不进入代码搜索。
- 用户显式同步外部变化；有未应用修改时做基线/副本/原目录三方冲突检查，不直接覆盖任何一方。
- 沙箱仅挂载工作副本，宿主原目录、应用数据库、密钥和 Docker socket 均不暴露给沙箱内程序。
- Docker Desktop Linux 引擎已确认可连接，服务端版本 29.6.2；状态、Provider 生命周期、Project 根挂载和成功/失败/超时/主动停止命令均已验收。Windows 专用构建任务不承诺首版兼容。

## 5. 已记录、当前后置的安全与可靠性设计

用户已于 2026-09-04 明确要求当前阶段暂不实施安全与可靠性专项。以下内容保留为后续设计记录，不作为当前原子功能的准入门槛，也不再安排受信任项目规范或历史访问门禁作为下一步。

1. **访问范围与路径**：入口可接收用户提供的绝对路径，经服务端授权解析为目标文件或目录范围；内部根内相对路径解析器继续拒绝绝对路径、盘符、UNC、设备路径、ADS、NUL 和 `..` 逃逸。检查真实父目录、符号链接/junction/reparse point；首版拒绝跟随链接，写入时再次检查。不能通过放宽现有相对路径校验来实现普通对话访问，字符串前缀比较不是权限边界。
2. **敏感内容**：默认禁止 `.env`/凭据/私钥等进入读取、搜索、复制、Diff、日志和模型上下文；允许明确的示例文件。`.git` 内部、依赖、构建及应用数据目录使用独立忽略策略。遵守 `.gitignore` 不等于识别全部秘密，也不构成安全隔离。
3. **代码是数据**：README、注释、工具输出不自动升级为指令。仓库 AGENTS.md 仅在用户信任项目规范后按目录作用域加载；规范不能注册工具、扩大目录权限、获取秘密或跳过审批。
4. **有界 IO**：目录懒加载；glob/search/read 都有文件数、字节、行数、时间与输出预算。返回截断原因和续读方式，禁止静默丢内容后声称完整分析。UTF-8/CRLF/BOM 明确处理，二进制先只显示元数据。
5. **修改前置条件**：现有文件需成功读取当前版本；期望哈希不符、读取失败、多处匹配或符号链接变化均拒绝。空文件和新建文件有独立契约；写后原读取凭证失效。原子替换不等于跨文件事务，也不能单靠应用锁消除外部竞争。
6. **操作授权**：按只读、文件修改、文件删除、命令执行、网络/依赖安装分级。Skills allowed-tools 与当前文件访问权限取交集；普通对话与项目对话执行相同策略。涉及本地文件的 Run 首版不继承未声明安全边界的 MCP 工具，防止经 MCP 绕过访问范围和沙箱。子 Agent 首版不开放写文件和 Shell。
7. **审批绑定事实**：审批记录绑定文件访问范围/workspace/version、可选 project、thread/run/tool_call、操作内容摘要哈希及有效期；用户改参数、文件变化、取消、超时或服务重启后原批准不得继续使用。按钮请求幂等，拒绝不能转为“换个工具再做”。普通对话与项目对话访问同一目标时不能绕过共享写入仲裁。
8. **审批生命周期**：首版采用同 Run 的有界 `waiting_for_approval` 等待，由用户端点唤醒；不是复用“澄清结束后新 Run”的机制。等待状态、请求和决定持久化，刷新可查询；超时/断连按现有 Run 取消策略处理，重启标记 interrupted/expired，不自动重放副作用。
9. **执行隔离**：设置 cwd/校验命令字符串/提供白名单都不等于沙箱。测试、构建、包安装脚本都可能执行任意代码，必须经过同一策略。首版无 privileged、无宿主 socket、无宿主环境全量继承；限制 CPU、内存、进程、磁盘/产物、输出和超时，网络默认关闭。
10. **依赖准备**：用户选择可信基础镜像与版本；缺依赖需展示安装命令和网络目标并审批，在隔离环境安装。不得自动读取宿主 `.venv`、`node_modules`、包管理器凭据或平台 API Key；无法联网时明确测试受阻，不伪造测试通过。
11. **取消与重启**：停止 Run 必须终止所拥有的命令及其子进程，并回收沙箱；清理无法确认时显示异常并阻止重用。已有文件修改保留并归档为部分结果，不能把“取消”当作“自动回滚”。
12. **落盘一致性**：文件系统与 SQLite 不共享事务。修改/应用采用操作日志、期望哈希、备份和明确状态；进程崩溃后核对真实文件，禁止盲目重放写入。多文件操作必须显示部分成功/冲突，不承诺虚假的全有或全无。

## 6. 里程碑与原子实施清单

13.1—13.4 均 **用户已验证**；13.5 项目主图只读工具待终端模型验收，并按用户新要求扩展为通用文件访问上下文。后续文件工具逐项覆盖普通对话和项目对话。每项交付都要有页面或实际文件效果；内部基础设施需配一个最小可观察状态或诊断入口。大于一个独立可验收行为的条目，在进入实现前再细分执行步骤，不一次堆完才验证。

### 里程碑一：真正打开本地项目（13.1—13.4）

| 编号 | 功能点 | 用户验证 | DeerFlow 学习入口 |
| --- | --- | --- | --- |
| 13.1 | 登记已有本地目录，持久化项目名/路径/状态；默认只读；解除登记不删文件 | 登记一个样例项目、刷新恢复；非法根拒绝；移除后原文件仍在 | `config/paths.py`、`thread_data_middleware.py`，理解为何需新增 Project |
| 13.2 | Project 与 Thread 归属，项目内新会话与切换；普通聊天兼容 | 两个项目各发起会话，切换/重启后不串目录；历史 Thread 不随意重绑 | Thread 隔离与现有 Mini Deer Thread/Run 准入链 |
| 13.3 | 项目文件树懒加载与刷新，显示忽略/不可访问状态 | 展开真实子目录，列表有界；外部新增文件刷新可见 | `sandbox/tools.py` 的 ls、`sandbox/search.py` |
| 13.4 | 只读源码预览、行号与路径定位；大文件分段，二进制提示 | 打开代码、中文/空文件/大文件；无法读取时明确提示 | `read_file_tool`、行范围与二进制测试 |

退出门槛：项目能保存、会话能正确关联、文件能看；没有写工具和命令工具，也不在界面伪装已经支持。

### 里程碑二：Agent 理解当前项目（13.5—13.7）

| 编号 | 功能点 | 用户验证 | DeerFlow 学习入口 |
| --- | --- | --- | --- |
| 13.5 | 主 Agent 共用 list/read 工具，支持项目默认目录与普通对话明确路径的授权上下文，复用 COT/事件审计 | 项目与普通对话都能读取获准文件并引用真实路径/行号；普通对话无需登记项目，未授权路径拒绝 | `sandbox/tools.py`、Provider 获取链 |
| 13.6 | glob/search 工具与有界结果、忽略规则、续读提示 | 跨文件找符号和调用点，查看超限提示；不能读到根外与秘密文件 | `sandbox/search.py`、glob/grep 及相关测试 |
| 13.7 | 可选文件引用、自动目录概要与本轮明确根外路径 | 不指定文件时模型自主选择；明确绝对路径时可读根外目标；未明确时保持项目根 | 路径上下文与现有 Durable Context 的边界对照 |

退出门槛：Agent 能实际阅读并解释项目，而不是依靠上传附件或自行编造文件结构。

### 里程碑三：直接修改与文件管理（13.8—13.14）

| 编号 | 功能点 | 用户验证 | DeerFlow 学习入口 |
| --- | --- | --- | --- |
| 13.8 | 直接创建新 UTF-8 文本文件；项目根与普通允许根共用工具 | Agent 创建测试文件并读回；同名目标不覆盖 | `write_file_tool` 与本地路径映射 |
| 13.9 | Docker 状态、最小 SandboxProvider 和 Project 根只读挂载均已验收 | 页面已确认 `/workspace` 根条目和容器销毁 | `sandbox.py`、`sandbox_provider.py`、`community/aio_sandbox/` |
| 13.10 | 文件操作审批请求、批准/拒绝、等待/过期和刷新恢复 | 请求一次具体新建操作；批准前无写入，拒绝后不执行，重复批准不重复写 | 对照工具拦截/审计边界；持久审批由 Mini Deer 单独设计 |
| 13.11 | 覆盖写入与完整文本更新 | 修改已有文件并读回真实内容 | `write_file_tool` |
| 13.12 | 唯一匹配精确编辑，返回路径/变更摘要与可打开 Diff | 只改指定函数；无匹配/多匹配拒绝；CRLF/BOM 不被整文件破坏 | `str_replace_tool`、同路径锁、`workspace_changes/diff.py` |
| 13.13 | 文件/目录管理 UI：新建、重命名/移动、删除到受管回收区 | 副本里新建/改名/删除可恢复；目标覆盖和非空目录删除需明确确认；不跨根移动 | ls/write 与变更状态；移动/回收是 Mini Deer 新增，不声称来自 DeerFlow |
| 13.14 | Run 级变更列表、逐文件 Diff 与带冲突校验的撤销 | 正常/失败/停止后都能审阅变化；撤销不覆盖之后的新修改；重启可查询 | `workspace_changes/`、`runtime/runs/worker.py`、前端 changes 查询 |

退出门槛：用户能管理副本文件，Agent 能在批准范围内改代码并交付可审阅变化；原目录尚不自动改变。文件管理器与 Agent 工具必须复用同一文件服务，不能各自绕过安全策略。

13.8—13.14 的创建、编辑、移动、重命名、删除、Diff 和撤销同样覆盖普通对话。工作副本/版本/审批与恢复须能绑定已授权文件访问范围，不要求先创建 Project；具体原目录修改策略仍在 13.8 确认。

### 里程碑四：执行、验证并交付原项目（13.15—13.17）

| 编号 | 功能点 | 用户验证 | DeerFlow 学习入口 |
| --- | --- | --- | --- |
| 13.15 | Agent 命令工具：成功、失败、超时终止和用户主动取消均已验收 | 真实退出码、超时与停止均回收容器 | `bash_tool`、`env_policy.py`、命令超时测试 |
| 13.16 | 原“工作副本审阅后应用”方案已被直写授信根取代 | Agent 文件工具直接修改用户授信的项目根，真实文件与审阅 Diff 已验收；不再安排 ChangeSet 应用步骤 | 用户于 13.8 前确认直写方案；工作副本、备份与恢复留待安全可靠性专项 |
| 13.17 | Coding Prompt 与执行闭环：失败修复、小功能、配套测试和真实命令均已验收 | 样例项目已完成 bug 修复和小功能并运行测试 | 结合 DeerFlow 工具使用规则，复用现有主图/Todo/澄清 |

退出门槛：完整闭环真实跑通，不能只展示“已修改”文字或把测试成功等同于应用到原目录成功。自动修复设有次数/时间预算，耗尽后保留证据并停下；通用循环检测平台仍后置。

### 里程碑五：阶段收口（13.18）

13.18 做专项回归与用户验收。首个收口点已把持久化 `run_project_command` 结果投影到“检查结果”审阅区，显示每次命令的真实终态和退出码并支持刷新恢复，用户已完成页面验收。当前确认项目入口说明、架构说明、状态与源码一致；其余安全与可靠性专项继续按用户决定后置。用户确认后再写第 13 阶段总学习结论。

## 7. 主要模块与集成位置

以下是建议布局，实施时按功能创建，禁止提前铺空目录；复用现有接口优于平行实现。

| 模块 | 责任 |
| --- | --- |
| `domain/workspaces.py`、`domain/conversations.py` | Project/Workspace/ChangeSet/Approval/CommandResult 契约，Thread 归属与 Run 快照 |
| `application/workspaces.py`、`application/approvals.py` | 项目登记、同步、文件用例、审批与变更应用；不依赖 FastAPI |
| `workspace/` | 根路径、忽略、文本读写、版本校验、操作日志、Diff 与备份恢复 |
| `sandbox/` | 执行器/Provider 接口、本地容器适配器、环境和进程生命周期 |
| `tools/`、`agents/main/graph.py`、`agents/prompts/` | 文件/命令薄封装、工具权限、审批路由和 Coding 上下文；不能把文件 IO 塞进主图 |
| `application/run_execution.py`、`application/run_stream.py` | Run 准入、Workspace 独占、等待审批、取消、变更归档与受信任依赖注入 |
| `persistence/`、`streaming/`、`server/` | SQLite 增量迁移；安全 API；审批、命令输出、文件变化事件与历史查询 |
| `frontend/src/entities/project/`、`features/workspace/` | 项目选择、文件树/预览、引用；避免继续扩大 ChatPage |
| `frontend/src/features/changes/`、`features/tool-approval/` | Diff/应用/冲突、审批与命令日志详情；COT 仅显示紧凑摘要及定位入口 |
| `tests/`、`frontend/tests/` | 临时样例项目、假模型/假执行器、路径与事务回归、交互测试 |

继续沿用 Python/FastAPI/LangGraph/SQLite 和 React/TypeScript；不因这个阶段迁移到 DeerFlow 的框架。编辑器首版为源码查看 + Diff，是否引入 Monaco 留待需要手工编辑时决定，不做完整 IDE/LSP。

关键持久事实包括：项目根与状态、Thread 项目归属、Run 工作区/权限快照、文件操作日志/基线与变更集、审批决定、命令身份和终态。进程句柄/沙箱客户端不能写入数据库；完整代码库和无界日志不进入消息历史。已有数据库做兼容迁移，不删除真实数据。

协议原则：先定义领域事件再扩展 SSE parser/reducer；审批等待需要正式状态，不伪装 completed；变更结果必须区分“无变化”“尚不可用”“部分/截断”“应用失败”。所有查询核对 Project/Thread/Run 归属，前端本地选择不是授权来源。

## 8. 阶段验收清单

- [ ] 项目：登记、会话归属、刷新/重启、目录丢失和解除登记均正确。
- [ ] 只读：文件树/搜索/行范围真实可用，无根外、秘密文件或错误项目内容进入模型。
- [ ] 写入：新建/精确修改/移动/删除/恢复均在指定工作区，哈希冲突拒绝，用户原有未提交改动保留。
- [ ] 审批：未批准不执行；拒绝、过期、重复请求、参数变更、重启均不能偷渡执行。
- [ ] 命令：隔离生效，真实退出码，取消清理，超时及日志/磁盘预算；无宿主密钥和额外挂载。
- [ ] 交付：Diff 与真实文件一致；审阅后应用；冲突和多文件部分失败有可恢复记录。
- [ ] Coding：样例 bug 修复与小功能分别真实运行通过，失败时不声称成功。
- [ ] 兼容：旧 Thread、前端 COT/Todo、普通聊天、历史读取不回退。

只用专门验收目录做破坏/冲突/恢复测试，不直接拿本项目真实源码做自动写入安全实验。普通单测用 fake model/provider，真实模型测试单独触发；本计划不触发模型费用、容器安装或包安装。

## 9. 暂不纳入

- 完整 IDE、LSP、代码补全、图形化调试、任意交互终端和长期后台开发服务。
- 多人实时协作、多租户、公开部署、远端集群、Redis/温池/远端沙箱平台。
- 自动 commit/push/PR、worktree 多分支并发开发；Git 首版只用作只读背景信息，不替代文件基线。
- 子 Agent 并发写同一代码树、递归自主执行、自定义插件随项目自动安装。
- PDF/图片等二进制编辑、完整 Artifact 平台、全盘索引、向量代码搜索。
- 自动放行联网/依赖安装、任意宿主命令；不得以“本地单用户”作为开放这些能力的理由。

## 10. 开始实施前的确认与下一步

计划需要用户确认的关键取舍：

1. 是否采用“受管工作副本 + 审阅应用回原目录”，或要求直写原目录；决定点在 13.8 前。
2. 首个隔离执行环境是否接受 Docker Linux；到 13.9 前检查本机条件和样例项目需要，不假定已安装。
3. 首版登记目录用路径输入/受控目录浏览器是否满足使用习惯；原生桌面选择器不是首版前置依赖。

本轮从 **13.1 项目登记与只读状态** 开始，后端登记/持久查询与页面登记/状态/解除闭环均已验证；13.2 后端 Thread 归属也已验证，页面项目会话切换已由用户验证。不得将阶段实施授权理解为跳过每个原子功能点的用户验证。

### 13.1 后端登记与持久查询（已验证）

DeerFlow 对照提交重新核验为 `a5acc25de6742b2166b3f41c97bd895822277b94`。
调用链为 `ThreadDataMiddleware.before_agent()` → `_get_thread_paths()` →
`Paths.sandbox_work_dir()` → `Paths.thread_dir()`；目录属于 Thread，默认惰性创建。
Mini Deer 的项目必须跨 Thread 存续，因此本轮使用独立 Project 和业务数据库登记，
没有将项目目录写入 checkpoint，也没有注册 Agent 文件工具。

Mini Deer 的对应调用链：

```text
POST /api/v1/projects
  → require_workspace_access：回环连接、Host、Origin、独立访问凭据
  → ProjectService.register：名称校验、目录策略、生成 Project ID
  → ProjectRootPolicy.inspect：允许根、逐层 lstat、链接/敏感目录拒绝
  → SqliteProjectRepository.insert：业务 SQLite v9、唯一根路径约束
GET /api/v1/projects 或 /api/v1/projects/{project_id}
  → 查询登记 → 重新核验目录身份 → 返回/持久化可用状态
```

- 登记只接受 `name`、`root_path`，权限固定为 `read_only`；不会遍历或读写项目文件。
- 项目表与对话复用同一连接、锁和迁移链，项目表没有 Thread 外键。
- 状态为 `available / missing / unavailable / changed`；目录移走、权限被收回、
  被替换后不继续声称可用。允许根暂不可用也不会阻止服务重启。
- GET 同样需要凭据，成功响应禁止缓存；列表每页最多 100 条，使用 `next_offset` 续页。
- 凭据来自服务端配置，修改后重启生效。后续页面子步骤已增加手动输入凭据的入口，尚未实现完整用户认证或审批。
- 自动化：后端全量 260 项通过；随后补充允许根缺失重启、权限拒绝和 Windows 路径别名回归，
  涉及模块的 48 项通过。中文目录、真实符号链接/junction、并发重复登记、迁移和只读副作用均已覆盖。

本机验证步骤（无需真实模型）：

1. 在项目 `.env` 中增加下面两项。凭据可用
   `.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"`
   在本机生成，将输出填入第二项；不要使用模型 API Key。

   ```dotenv
   MINI_DEER_WORKSPACE_ALLOWED_ROOTS=["D:/project/agentstudy/mini-deer-agent/examples/workspace-registration-sample"]
   MINI_DEER_WORKSPACE_API_TOKEN=填入刚生成的随机值
   ```

2. 重启后端：

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn mini_deer_agent.api:app --host 127.0.0.1 --port 8001
   ```

3. 打开 `http://127.0.0.1:8001/docs`，点击 **Authorize**，在
   `X-Mini-Deer-Workspace-Token` 对应输入中填入同一凭据。
   执行 `POST /api/v1/projects`：

   ```json
   {
     "name": "Coding 验收项目",
     "root_path": "D:/project/agentstudy/mini-deer-agent/examples/workspace-registration-sample"
   }
   ```

4. 预期 201，返回稳定 `project_id`、`status: available`、`access_mode: read_only`。
   用 GET 列表和单项目接口读回；刷新页面并重启后端后仍是同一 ID。
   重复 POST 返回 409，不覆盖原名称。样例 README 内容不变。
5. 将 POST 路径换为 `D:/` 或允许根外的目录，预期 400；清除 Authorize 后查询预期 403。
   想验证目录失效时，只临时重命名这个样例目录，查询应显示 `missing`，恢复原名后回到 `available`。

用户已明确回复“已验证”，上述后端子步骤的学习结论已写入 `LEARNING.md`。
页面登记与解除入口的完整验收结果见下文；用户确认后已进入 13.2。

### 13.1 页面登记与解除入口（已验证）

本次只增加侧栏“项目”按钮与独立原生 dialog，复用现有登记/查询 API；没有修改
聊天视觉、项目会话归属、Agent 图或目录权限策略。用户回复“继续”后，已补齐解除登记闭环。

DeerFlow 对照 `components/workspace/workspace-sidebar.tsx` 的入口组合方式，以及
`core/workspace-changes/hooks.ts` → `api.ts` 的 UI/请求职责分离。DeerFlow 此处是
Thread/Run 文件变化查询，不是持久本地项目登记；Mini Deer 没有照搬功能语义或引入
TanStack Query，而是沿用现有 React Hook 与有校验的 API 客户端。

```text
ConversationRail → WorkspaceLauncher → ProjectManager
  → useProjects：当前页面凭据、单次请求、取消、锁定、迟到响应拒绝
  → projects.ts：同源 GET/POST/DELETE、凭据请求头、15 秒超时、禁止重定向
  → parseProject / parseProjectPage：身份、权限、状态、时间和分页校验
  → 已验证的后端项目应用服务
```

- 页面挂载不自动请求项目，也不自动创建测试登记；用户输入工作区凭据后才加载实际数据库列表。
- 凭据只保存在当前页面内存，不写入 localStorage/sessionStorage、URL 或前端构建配置。
  关闭面板再打开仍可使用；“锁定工作区”、刷新页面或收到 403 后需要重新输入。
- 项目列表显示规范路径、只读状态和目录可用性；可刷新状态和加载更多项目。
- 登记表单在真实 201 返回且响应校验通过后才显示成功并清空输入。
  拒绝保留输入；网络故障明确提示先刷新核对结果，不自动重发 POST。
- 项目卡片先显示名称明确的解除确认；取消不请求后端，确认仅发送 Project ID。
  后端幂等删除 `projects` 元数据，收到 204 后页面才移除卡片并明确原目录及文件已保留。
  目录已经缺失或不可访问也能解除；失败时保留卡片和确认区域供用户核对、重试。
- 原生 dialog 提供模态焦点与 Esc 关闭；窄屏表单、项目列表改为单列，长路径换行。
- 自动化：后端全量 265 项、前端 33 个测试文件 218 项通过，
  typecheck / ESLint / Prettier / build 和空白差异检查均通过。
- 真实浏览器：使用独立临时数据库验证连接、已登记列表、页面登记成功、桌面与窄屏布局、
  Esc 关闭，以及解除确认、取消保留项目、成功后卡片消失和保留文件提示；
  随后核对数据库项目行数为 0，临时项目原文件内容仍为 `keep original`。
  未使用或更改用户真实凭据及已有项目登记。

DeerFlow 的 `DELETE /threads/{thread_id}` 会进入 `_delete_thread_data()`，再调用
`Paths.delete_thread_dir()` 删除 DeerFlow 自己管理的 Thread 目录，并清理 checkpoint 与元数据。
Mini Deer 此处登记的是用户已有目录，不能复用这条文件删除语义；对应调用链被刻意收窄为：

```text
ProjectManager 确认解除
  → useProjects.unregister：单请求门闩，等待成功事实
  → DELETE /api/v1/projects/{project_id}：本地门禁与 UUID 校验
  → ProjectService.unregister
  → SqliteProjectRepository.remove：仅 DELETE projects 行
  → 204 后移除页面卡片；不检查、不遍历、不删除 root_path
```

用户验证：

1. 保持已配置的后端运行，刷新前端 `http://127.0.0.1:5173`，点击左侧“项目”。
2. 输入刚才在 Swagger 使用的工作区凭据，点击“连接并加载项目”，应看到实际数据库中的已有登记及只读状态。
   自动化里的项目使用隔离临时数据库，不会出现在这里，也不会为实际数据库自动创建测试项目。
3. 在允许根下另选一个尚未登记的现有目录，填写名称与绝对路径并登记，预期出现成功提示和新项目。
   若再次登记同一目录，应提示已登记，保留输入，不新增重复项。
4. 点击“刷新项目”核对状态；关闭面板、重新打开仍可查看。刷新整个页面后重新输入凭据，登记仍在。
5. 点击“锁定工作区”，应清空项目展示并回到凭据输入；Esc 能关闭面板，原聊天仍可使用。
6. 在任一项目卡片点击“解除登记”，应先看到“原目录及文件会保留”；点“取消”时项目仍在。
   再次打开并点“确认解除登记”，预期卡片消失并出现保留原文件的成功提示。到项目目录确认原文件仍在，
   刷新项目列表及后端重启后该登记都不再出现；重复调用同一 DELETE 应保持 204。

用户确认允许根外的 `src` 路径被拒绝，改用实际允许根完成页面闭环后回复“已验证”。
页面实现结论已写入 `LEARNING.md`；原目录策略和 Docker 仍分别后置到 13.8、13.9。

### 13.2 后端 Thread 归属（已验证）

DeerFlow 对照 `ThreadDataMiddleware.before_agent()` → `_get_thread_paths()` →
`Paths.sandbox_work_dir()`：运行配置中的 `thread_id` 直接决定 DeerFlow 受管 workspace，
因此每个 Thread 天然拥有独立目录。Mini Deer 的一个 Project 需要关联多个 Thread，不能继续把
Project 身份隐含在 Thread 路径中；本步把 nullable `project_id` 写成显式、不可重绑的 Thread 元数据。

```text
POST /api/v1/projects/{project_id}/threads
  → require_workspace_access：复用项目管理门禁
  → ProjectThreadService.create：确认 Project 已登记且目录 available
  → SqliteConversationRepository.create_project_thread
       新 Thread：写入 project_id，title=null，status=idle
       同 ID 同 Project：幂等读回
       同 ID 其他 Project/普通聊天：409，禁止重绑
GET /api/v1/projects/{project_id}/threads
  → 只按持久 project_id 查询该项目最近 Thread
GET /api/v1/threads/{thread_id}
  → 普通 Thread 响应同时公开 project_id 或 null
```

- 业务 SQLite v10 为 `threads` 增加 nullable `project_id` 和项目最近活动索引。
  不增加 `projects` 外键：解除登记不能级联清空历史 Thread 的原项目身份。
- 客户端必须提供 UUID `thread_id`，让响应丢失后的相同创建请求可以安全重试。
- 已有普通聊天和后续普通聊天保持 `project_id = null`；已有 Thread 即使当前为空也不能重新绑定。
- 项目目录 missing/unavailable/changed 时拒绝创建新项目 Thread；列出已有归属仍保留历史事实。
- 项目 Thread 的首个 Run 只在标题为空时生成默认标题，绝不覆盖 `project_id`。
- 本步不创建项目目录、文件工具、Run、checkpoint 或工作区副本；Run 准入快照仍按后续原子点推进。
- 自动化：后端全量 268 项通过，覆盖两项目隔离、幂等创建、禁止重绑、普通聊天兼容、
  解除登记后历史归属保留、v8→v10 迁移和重启恢复。

用户验证（无需调用模型）：

1. 重启后端使 v10 迁移生效；在 Swagger 用工作区凭据执行 `GET /api/v1/projects`。
   如果 13.1 验收时已解除项目，请先按允许根重新登记，并复制真实 `project_id`。
2. 本地生成一个新 Thread UUID：

   ```powershell
   [guid]::NewGuid().ToString()
   ```

3. 执行 `POST /api/v1/projects/{project_id}/threads`：

   ```json
   { "thread_id": "把上一步 UUID 填在这里" }
   ```

   预期 200，`title` 为 `null`、`status` 为 `idle`，`project_id` 与路径中的项目一致。
4. 用同一请求再执行一次，预期仍是相同 Thread，列表不会重复。执行
   `GET /api/v1/projects/{project_id}/threads` 和 `GET /api/v1/threads/{thread_id}`，
   两处应返回相同归属；重启后端后再次查询仍存在。
5. 执行普通 `GET /api/v1/threads`，已有普通聊天应显示 `project_id: null`，不受迁移影响。

用户按上述步骤确认幂等创建、项目列表归属、全局查询归属和普通聊天兼容后回复“已验证”。
本小节结论已写入 `LEARNING.md`，下一原子功能点为页面项目会话切换。

### 13.2 页面项目会话切换（用户已验证）

页面沿用 13.1 的当前页面内存凭据，不新增浏览器持久凭据。根据用户反馈，第一版把会话藏在
项目 dialog 内增加了操作路径，现已改为类似 Codex 的左侧项目树：dialog 只负责连接、登记、
状态和解除管理；连接后，项目及其 Thread 直接显示在左侧会话栏。

```text
左侧项目节点展开
  → GET /api/v1/projects/{project_id}/threads：只接收该项目归属
左侧项目行“＋”新建会话
  → 浏览器生成稳定 UUID
  → POST /api/v1/projects/{project_id}/threads
  → 严格核对 200 响应中的 thread_id 与 project_id
  → CurrentThreadRepository 保存当前选择
  → ChatPage 按既有历史加载链切换到该 Thread
```

- 普通“新会话”继续生成 `project_id = null` 的聊天；左侧“最近会话”只展示普通聊天，项目
  Thread 直接嵌套在所属项目下面，避免两个入口混成一个扁平列表。
- 连接成功后不必再次打开管理弹窗；点击项目名称即可展开/收起，项目行的“＋”直接创建，
  Thread 标题直接切换聊天。“管理”保留登记、状态刷新、解除登记和锁定入口。
- 新建请求返回、状态码或身份无法确认时不会切换页面；页面保留错误，可刷新该项目会话核对。
- 页面运行控制器按 Thread 保存独立状态和活动 SSE。当前 Run 执行时仍可新建或切换普通/项目
  Thread，旧流继续在后台消费；新 Thread 可并发启动自己的 Run。切回后恢复该 Thread 的实时状态，
  “停止”只作用于当前 Thread。同一 Thread 仍只允许一个活动 Run；切走后的活动 Thread 在普通
  会话和项目树中持续标记“正在后台运行/运行中”。
- 左侧“＋”创建的项目 Thread 在本地提交首个 Run 前属于当前页面草稿。若用户先切换到
  其他项目 Thread、普通 Thread 或普通“新会话”，页面先调用既有 Thread 删除链清理这条空记录；
  删除失败则停在当前草稿并显示错误。本地提交 Run 时即清除标记，防止响应头到达前切换误删；收到属于该 Thread 的 Run ID 后再次确认清除
  草稿标记；后续 Run 状态重置或切换 Thread 不会重新把它当作草稿，旧 Thread 的 Run 也不能误完成
  新草稿。
- 页面刷新后当前 Thread ID 仍由既有 repository 恢复；工作区凭据按原安全边界需要重新输入，
  再次查看项目时从后端恢复持久归属。
- 刷新包含纯思考中间消息的会话时，允许 Assistant 正文为空且 reasoning 非空；用户空消息以及
  正文、思考均为空的 Assistant 消息仍按无效历史拒绝，避免一条合法中间消息阻断整页恢复。
- 本步不读取项目文件，也不让 Run 获得目录访问能力。前端全量 34 个测试文件 230 项、后端全量
  270 项通过，typecheck、ESLint、Prettier 与生产构建均通过。

用户验证：

1. 刷新 `http://127.0.0.1:5173`，点击“项目”，输入 13.1 使用的工作区凭据并加载项目。
2. 关闭管理弹窗。左侧现在应直接显示已登记项目；点击项目名称展开，Swagger 创建的项目 Thread
   应显示在项目名称下面。点击 Thread，聊天页应切换到相同会话。
3. 点击项目行右侧“＋”，进入新的空项目会话；不要发送消息，直接点击另一个会话或普通“新会话”。
   再展开项目并刷新，刚才的空会话应已消失。
4. 再创建一个项目会话并发送一条普通消息；完成后点击项目树内“刷新会话”，应看到生成后的标题，
   并能在已有项目 Thread 之间切换。左侧“最近会话”不应重复展示这些项目 Thread。
5. 点击左侧普通“新会话”并发送消息，再打开项目确认它没有进入项目会话列表。
6. 刷新整个页面，重新输入工作区凭据并查看项目；项目会话仍存在且不会混入其他项目。
7. 在一个 Thread 发起耗时 Run，不点击停止便切到另一个 Thread 并发起第二个 Run；两个 Thread
   均应继续执行。来回切换应看到各自独立进度，停止其中一个不应终止另一个。

用户已明确回复“已验证，继续”，13.2 收尾结论已写入 `LEARNING.md`。

### 13.3 单层目录列表 API（用户已验证）

调用链：受工作区凭据保护的 `GET /api/v1/projects/{project_id}/directory`
→ `ProjectService.directory` 复核登记根 → `workspace/directory.py` 校验相对路径并单层枚举。
默认最多 200 项，可调到 500；目录优先排序，返回 `truncated` 和原因，不声明已列出全部。
`path` 为空表示根目录，子目录使用 `src/utils` 形式。每次调用重新枚举，所以外部修改后再次请求可见。
固定忽略策略阻止凭据、常见依赖/构建目录和数据库文件展开；目前不解析自定义 `.gitignore`。
链接/reparse point 不跟随，子项返回 unavailable；缺失或不能打开的目录返回错误，不伪装空目录。
只返回名称、相对路径、类型、状态及原因；不读正文，不注册 Agent 工具，无数据库迁移。
枚举循环有 1 秒协作式预算，单次操作系统调用仍可能阻塞；前后身份复核不等于消除外部文件系统竞争。
相关后端 48 项通过，含真实临时目录、链接、路径别名、根失效和 HTTP 凭据/Origin 门禁。

验收：重启后端，打开 Swagger，使用现有工作区凭据和项目 ID。新接口先留空 path，确认只返回直接子项；
再用真实子目录相对路径展开。在外部新增一个文件后重试，结果应更新。limit=1 应在多子项时返回 truncated；
path=../ 应被拒绝。此步骤验证后才接左侧文件树；本接口验证前不记录为 13.3 已完成。

### 13.3 页面文件树（用户已验证）

用户已确认目录 API 验收。左侧展开项目后，点击“文件”加载根目录，点击子目录逐层请求；各目录“刷新”重新加载并清除旧子树。普通文件名仅展示，13.4 才接正文预览。忽略/不可访问项显示状态，截断显示原因；错误可刷新重试。凭据仍只在 useProjects 内存中，节点卸载/收起会取消请求并拒绝迟到响应。前端目录响应校验 Project/path/直接子项身份，复用现有同源、禁止重定向和 15 秒请求超时。相关 27 项通过；等待用户验证展开、刷新、项目切换和锁定行为。

### 13.4 只读文件接口（用户已验证）

用户已确认 13.3 文件树。新增 `GET /api/v1/projects/{project_id}/file?path=src/main.py&start_line=1&limit=200`，复用工作区门禁。按项目根内相对路径只读普通文件，拒绝忽略路径、链接/reparse 和目录；根身份在前后复核，文件句柄与路径身份、大小和修改时间核对。

最大读取 2 MiB；默认返回 200 行、最多 500 行，单次正文预算 32768 字符，next_line 指示下一段。每段读取有界文件快照并返回 SHA-256 revision；这不是无限大小文件的流式读取。UTF-8 BOM 仅在显示时移除，CRLF/CR 归一为行数组，原文件不改写。空文件 text+空数组；binary、unsupported_encoding、too_large、line_too_long 均不返回正文。版本复核不能消除全部外部竞争；后续页面续读应核对 revision，避免混拼不同版本。

测试：相关后端 61 项通过，覆盖中文/CRLF/BOM、空文件、分段和字符预算、编码及超大文件、链接/路径拒绝、HTTP 门禁和根失效。请重启后端，在 Swagger 使用真实相对文件路径，limit=2 验证两行和 next_line，再续读；文件正文预览 UI 尚未接入。

### 13.4 源码预览页面（用户已验证）

读取 API 用户已验收。新增 FilePage 解析器，核验项目、相对路径、起始行、连续 next_line、正文预算与版本字段；fetchProjectFile 复用同源凭据请求。ProjectFiles 组合文件树与原生 dialog 预览，普通文件节点才可点击。FilePreview 按段显示路径、行号和纯文本，支持上下段及重新加载，文件 revision 变化时停止续读；关闭/卸载拒绝迟到响应。预览无编辑和保存操作。当前相关前端 35 项通过，类型、ESLint、格式和构建通过。

用户验收：点击源码文件核对行号和中文；长文件翻页；外部修改后继续翻页应要求重新加载；空文件和不支持类型有明确提示。确认后 13.4 完成，再进入 13.5。

### 13.5 绑定项目的只读工具适配器（待用户验证）

工具工厂按可信 Project ID 取得冻结的根路径/身份/权限，模型只能传相对路径和行数。list_files/read_file 复用已验证的 ProjectService，调用前后核验绑定，解除登记或替换后拒绝；返回 JSON 包含 ok、真实目录/源码行与截断/续读信息。异步入口在线程池执行有界只读 IO，取消等待不表示底层文件系统调用被强制中止。

此原子点不注册到主图，避免普通聊天直接获得文件权限。`examples/inspect_project_tools.py PROJECT_ID --path README.md --limit 5` 可直接验证实际工具输出，不调用模型。相关后端 59 项通过，助手已用真实样例项目执行。

后续按下面的主图终端闭环先验证模型行为，再做网页 Run 与历史访问门禁。

### 13.5 主图只读工具闭环（待终端真实模型验证）

DeerFlow 本地基线仍为 a5acc25de6742b2166b3f41c97bd895822277b94：
`tools/tools.py:get_available_tools` → `agents/lead_agent/agent.py:_make_lead_agent`
筛选工具后交给 create_agent；`sandbox/tools.py:read_file_tool` 从运行时获取读取环境。
Mini Deer 复用现有显式 LangGraph 和 ProjectService，不复制 DeerFlow 的虚拟绝对路径或沙箱实现。

build_agent_graph 新增可信 project_service/project_id 成对参数，先检查绑定，再创建模型；
模型与 ToolNode 使用相同 list_files/read_file 实例。项目图排除 MCP；Skills 白名单仍生效，
task 子图不继承项目工具。v18 Prompt 包含项目 UUID、read_only、证据引用、结构化截断/版本说明和
文件正文不可信规则，不包含宿主根路径；普通图覆盖伪造的项目 Prompt 字段。

`examples/inspect_project_tools.py PROJECT_ID --ask "先列目录，再读 README.md 并引用行号解释用途"`
运行真实主图并打印节点消息；显式 --ask 才调用当前模型并发送读取内容。限制 24 个图步、180 秒等待，
不创建产品 Thread/Run，不保存 checkpoint/事件。原 --path 直接工具检查仍保留。

用户验证看到 list_files/read_file 的实际请求和结果，并核对回答引用后，再做网页闭环：
项目默认范围来自持久 Thread，普通对话始终使用服务端允许根集合；处理 Run/历史访问、旧入口及跨 Thread Memory 的边界，沿用当前本地免密码模式。
当前网页调用方没有传入项目参数，不能宣称网页模型已能读取文件。

本轮自动化：主图、项目工具、Prompt、MCP、Run 执行和 HTTP 相关 90 项通过，
编译与 diff 空白检查通过；使用临时文件和假模型，未调用在线模型。真实模型验收仍待用户完成。

真实模型首次运行按顺序调用 list/read 并引用真实行号，但错误声称 `next_line: null` 的末行被截断。
Prompt 随后升级为 v18，明确 `list_files.truncated = false` 表示目录结果未截断、
`read_file.next_line = null` 表示读到文件末尾，并禁止根据标点或换行猜测截断；针对性 20 项通过。
助手用同一项目和问题再次运行，工具顺序、路径、行号和完整性判断均正确；用户随后回复“继续”，13.5 终端真实模型闭环验收完成。

### 13.5 通用只读文件访问上下文（用户已验证）

对照 DeerFlow 的 `Runtime → thread state/context → SandboxProvider → Sandbox` 解析链，Mini Deer 新增冻结的 `FileAccessScope` 与 `ReadOnlyFileAccess`。可信调用方可从已登记 Project 或用户明确指定的允许根内文件/目录建立 Scope；工具参数仍只有相对路径和行数，不能携带绝对根或自行切换范围。Project 入口改为通用工具工厂的兼容包装，普通路径无需登记 Project。

目录 Scope 继续复用既有 `list_directory/read_project_file`；单文件 Scope 的根列表只暴露该文件，不能读取同目录兄弟文件。每次操作前后复核规范路径、目标类型和文件系统身份；允许根外、敏感文件、链接、目标替换继续失败关闭。此步只提供 `examples/inspect_file_access.py` 诊断入口，不接网页 Run、数据库、搜索、写入或命令。针对性 43 项与后端全量 309 项通过，Python 编译和 diff 空白检查通过；用户运行真实样例 README 命令后回复“已验证，继续”，该原子点验收完成。

### 13.5 无 Project 普通主图只读闭环（用户已验证）

`build_agent_graph(file_access=...)` 接受可信调用方冻结的明确文件/目录 Scope，并与 project_service/project_id 绑定互斥。模型与 ToolNode 使用同一 list/read 工具集合；文件 Scope 排除未声明路径边界的 MCP，Skills 白名单和 task 子图边界保持不变。Prompt v20 区分项目目录与明确单文件/目录，不包含宿主绝对路径或文件系统身份。

第一次真实模型运行正确调用 list/read，但因空行把实际第 3、5 行引用为第 2、4 行。通用读取结果新增与 `lines` 一一对应的 `line_numbers`，Prompt 强制使用该字段而非自行计数；复测正确引用 README.md:1、:3、:5、:6，并确认 `project_id=null`、只见授权单文件。针对性 39 项、后端全量 311 项、编译和 diff 空白检查通过；用户连续回复“继续”，该终端闭环已验收。网页 Run 尚未使用该构图参数。

### 13.5 网页项目 Run 只读闭环（用户已验证）

`ProjectFileAccessResolver` 读取业务库中的 ThreadRecord.project_id；该次项目验收中普通或不存在的 Thread 尚无 Scope，项目 Thread 必须从当前 `ProjectService` 成功冻结只读绑定。`RunStreamService` 在每轮 graph_factory 前解析该 Scope 并传给主图，新版 Run 与旧 `/chat/stream` 共用此链。HTTP 请求体、前端当前项目选择和模型参数均不能提供或改写项目身份；协议没有新增 project_id 字段。

项目解除登记、目录失效或根身份变化会在模型调用前失败关闭；任何文件 Scope 继续排除无路径边界的 MCP。真实持久 Project Thread 的应用层流测试确认模型获得 list/read、Prompt 含项目 UUID 且不含绝对根，工具读取 `main.py` 并返回 `line_numbers=[1]`。针对性 41 项、后端全量 312 项通过；确认 40 个现有 Thread 均无活动 Run 后已重启 8001，用户随后在 tesst 项目会话完成页面真实模型验收。

### 13.5 普通 Thread 常驻允许根（用户已验证）

用户澄清普通 Thread 在任何时候都应拥有读文件权限，因此取消“每个 Run 传入一个明确路径”的下一步。`ProjectRootPolicy` 复核全部配置允许根，`ReadOnlyFileAccess` 将其冻结为 `workspace-N` 虚拟入口；普通或尚不存在的 Thread 每轮自动取得该 Scope，Project Thread 继续只绑定自己的项目根。绝对宿主路径不进入模型或工具结果，敏感项、链接、越界路径与根身份变化仍失败关闭。

Prompt v21 指导模型先列虚拟根再展开。针对性 44 项、后端全量 314 项、编译和 diff 空白检查通过；真实模型正确完成 `list_files("") → list_files("workspace-1") → read_file("workspace-1/README.md")` 并引用真实行号。8001 后端重启后，用户已完成普通页面 Thread 验收。

### 13.6 有界文件名 glob（用户已验证）

对照 DeerFlow `sandbox/search.py` 的相对模式、根文件匹配、忽略目录与结果截断，Mini Deer 新增 `workspace/search.py` 和共用 `glob_files`。工具只返回匹配路径，不读取正文；项目 Scope 返回项目相对路径，普通 Thread 返回 `workspace-N/...`。扫描限制为 10,000 个目录项、1 秒、最多 200 条结果，并返回 `truncated/truncation_reason/scanned_entries`。绝对模式、父级片段、链接、敏感项和越界路径被拒绝或忽略。

Prompt v22 要求 glob 后仍用 read 取得代码证据，页面 COT 显示匹配模式和虚拟搜索目录。针对性后端 47 项、后端全量 319 项、前端全量 244 项通过；类型、Lint、格式和构建通过。真实模型正确完成 `glob_files("README.md") → read_file("workspace-1/README.md")` 并引用真实行号。8001 重启后，用户在普通页面 Thread 使用 `workspace-1/project-test` 完成 glob→read 验收。

### 13.6 有界正文搜索（用户已验证）

`search_files(query, path="", file_pattern=null, case_sensitive=false, limit=100)` 在当前文件 Scope 内搜索单行字面量，不开放任意正则。它支持将搜索目标限制为单个文件或目录，并用安全 glob 筛选候选文件；Project 返回项目相对路径，普通 Thread 返回 `workspace-N/...`，明确单文件 Scope 不会扩张到兄弟文件。

单次搜索最多扫描 10,000 个目录项、500 个文件、8 MiB 正文和 32,768 个输出字符，总预算 1 秒，单文件最多 1 MiB，最多返回 200 行。二进制、非 UTF-8、超大文件和超长行不进入结果；任何跳过、时间/文件/字节/结果/输出上限都通过 `truncated`、`truncation_reason` 与计数字段明确返回。每条命中包含虚拟 `path`、真实 `line_number` 和包含命中位置的有界 `line` 摘要。

Prompt v23 指导模型把 search 命中作为正文证据，并在截断时缩小路径、查询或文件模式后重试；页面 COT 显示字面量查询和虚拟搜索目录。针对性后端 53 项、后端全量 327 项、前端全量 247 项以及类型、Lint、构建、编译和 diff 空白检查通过。真实模型只调用 `search_files`，用 `**/*.py` 在 `project-test` 中找到并引用 `src/main.py:1` 与 `:6`，结果未截断。8001/5173 重启后，用户完成普通页面 Thread 验收。

### 13.7 文件树显式引用项目文件（用户已验证）

项目文件预览新增“引用到当前提问”。它把项目相对路径追加到现有输入草稿、关闭预览并聚焦输入框，不读取或复制文件正文，也不自动发送。只有当前 Thread 归属于正在预览的 Project 时按钮才可用；普通 Thread 与其他项目会话保持禁用，避免相对路径落入错误文件 Scope。

Composer 使用带递增 ID 的一次性插入信号，既保留用户已写草稿，也避免 React 重渲染重复追加。组件相关 18 项、前端全量 250 项、类型、Lint、格式、构建和 diff 空白检查通过。助手与用户均已在真实 `project-test` 项目会话完成 `src/main.py` 引用验收。用户随后指出 Coding 不应依赖手动引用；该入口保留为可选快捷方式，选区引用不再作为当前优先项。

### 13.7 自动项目根概要（等待用户页面验证）

每个 Project Run 构图时读取一次根目录元数据，最多把 40 个可用文件/目录及截断状态放入可信系统提示，不读取正文、不注入宿主绝对路径。路径元数据经过长度、控制字符与 XML 转义约束，并明确标记为不可信数据；普通 Thread 与明确文件 Scope 不接收项目概要，调用方伪造的概要字段由主图覆盖。

Prompt v24 明确用户无需手动引用文件，模型应根据任务和根概要自行选择 `list_files`、`glob_files`、`search_files`、`read_file`，并尽量使用完成任务所需的最小文件集合。概要属于基础系统提示，因此模型工具循环和摘要后调用继续收到同一 Run 快照；若概要截断或需要当前结构，仍须调用 `list_files`。相关后端 41 项、后端全量 330 项与编译、diff 检查通过。真实模型在未给文件名时自行定位并读取 `src/main.py`，准确引用 1、2、5、6 行；最小文件策略仍是模型软约束，实测也额外读取了 README/notes，不能宣称为确定性限制。8001 已重启，等待项目页面自然语言验收。

### 插入项：标题“＋”原生选择项目文件夹（用户已验证）

用户明确“项目”标题旁的小“＋”应打开文件夹选择器，而不是项目管理表单。前端现调用 `POST /api/v1/projects/pick-directory`，后端用独立子进程打开 Windows 原生目录选择器；选择结果仍经过允许根、敏感路径和项目身份校验，取消返回 204。选中目录登记后，侧栏立即展开项目，显示完整真实根路径并自动加载根文件树；“···”继续打开原登记管理界面。

真实验收目录为 `D:/project/agentstudy/project-test`，包含 `README.md`、`notes.txt` 与 `src/main.py`。针对性后端 36 项、前端 35 项通过；全量后端 321 项、前端 246 项以及类型、Lint、构建均通过。8001/5173 重启后，用户在原生窗口选择该目录并回复“已验证，继续”。
