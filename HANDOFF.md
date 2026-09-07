# Mini Deer Agent 当前任务交接

> 更新：2026-09-05。本文是供新窗口接手的当前状态快照，不是历史开发日志。
>
> **当前主线：第 13 阶段「项目工作区与 Agent Coding」进入 13.18 收口。完整 Coding 闭环和可恢复的真实检查结果均已验收；当前核对文档、状态与源码的一致性。**
>
> **最新用户要求：安全与可靠性专项暂不进入当前主线。Project Thread 默认文件范围是项目根目录；用户在本轮消息明确写出根外绝对文件或目录时，可以把该目标加入本轮只读范围；未明确给出时不得自行探索根外路径。**
>
> **当前插入项：用户要求个人学习模式移除工作区密码并简化侧栏。前后端密码配置/请求头及连接、锁定 UI 已移除，项目自动加载，按项目→会话缩进展示，默认五条及展开显示；用户已于 2026-09-03 完成页面验收。保留允许目录与本地来源检查。不要重新设计凭据传递。**

## 1. 新窗口从这里开始

1. 先读本文，掌握当前停点和待办。
2. 读 `docs/plans/project-workspace-coding-stage.md`：这是当前唯一的阶段实施入口，含 13.1—13.17 顺序、DeerFlow 对照和验收步骤。用户已明确无需另补设计文档。
3. 读 `PROJECT.md` 第 18—20 节及与本次修改相关的架构规则；按需查看 `LEARNING.md` 末尾和 `WORKPLAN.md` 顶部核对依据。
4. 执行 `git status --short`，保留当前所有未提交和未跟踪文件；工作树包含本阶段多个步骤的实现，不能当成临时杂物清理。
5. 根据第 4 节完成 13.18 文档与源码一致性检查；安全与可靠性专项继续后置。

`docs/plans/agent-capability-roadmap.md` 中第 12 阶段路线、旧的“等待指定 12.19”和旧暂停结论仅供追溯，不能作为当前执行指令。此前各课的源码讲解已在 `LEARNING.md`，不再复制进本文。

## 2. 当前主线与真实能力边界

目标是让用户登记本地项目后，Agent 能理解代码、提出修改、受控编辑、执行测试、修复问题并交付可审阅的 Diff。

| 阶段 | 内容 | 当前状态 |
| --- | --- | --- |
| 13.1—13.2 | 项目登记、Project/Thread 归属和项目会话入口 | 已实现，13.2 已由用户验收 |
| 13.3—13.4 | 真实项目文件树、只读源码预览 | 后端和页面均由用户验收 |
| 13.5—13.7 | Agent list/read/search、文件引用和项目上下文 | 已验收，包括普通 Thread 常驻根、自动根概要和 Project Thread 明确根外路径 |
| 13.8—13.14 | 直接文件创建、编辑与管理、Diff | 文件操作、改动清单、正文 Diff 和结构变化后文件树自动刷新均已验收 |
| 13.9、13.15—13.17 | 执行环境、沙箱命令和 Coding 闭环验收 | 命令、失败修复、新功能与配套测试均已验收 |

当前左侧已有项目/Thread 导航、真实目录文件树和源码预览。主图构造器支持 `file_access`，并注入 v38 文件、执行环境、失败修复和新功能测试上下文。`RunStreamService` 从持久 Thread.project_id 解析 Project Scope；Project Thread 默认使用项目根，本轮消息明确出现根外绝对路径时附加该文件或目录；普通 Thread 自动取得服务端允许根的虚拟 Scope。Project 命令新增 `timeout_seconds`，默认 30、范围 1—60；超时后强制删除容器，不返回伪造退出码。

第 12 阶段已有 Prompt、Todo、澄清、Skills、Memory、子 Agent、MCP、搜索/抓取及历史/COT 能力，本阶段复用这些执行基础，不重新做一遍。只增加 Coding 闭环需要的 UI；用户反馈的缺陷先修复。

## 3. 已经实现了什么

| 功能 | 实现事实 | 验证依据 |
| --- | --- | --- |
| 13.1 项目登记 | 独立 Project、只读登记、路径/状态复核、刷新恢复、解除登记不删原文件；SQLite v9 | 用户已在 Swagger 和页面明确确认 |
| 13.2 后端归属 | SQLite v10 为 Thread 增加 nullable `project_id`；按项目创建/列出、幂等、禁止重绑；普通聊天为 null | 用户已确认后端验收 |
| 13.2 页面项目导航 | 项目直接展示在左侧，展开 Thread，项目行“＋”新建；管理弹窗负责连接/登记/状态/解除 | 自动化通过，用户已确认验收 |
| 免密码项目入口与简洁侧栏 | 项目自动加载；按项目→会话缩进展示，默认五条并可展开；管理界面无密码、连接和锁定入口 | 自动化与助手实测通过；用户已于 2026-09-03 页面验收 |
| 原生项目文件夹选择 | 侧栏“项目”标题的“＋”打开 Windows 文件夹选择器，登记选中目录并自动展开真实路径和文件树；“···”保留项目管理 | 使用 `D:/project/agentstudy/project-test` 完成真实页面验收；后端 321 项、前端 246 项及静态检查通过 |
| 项目空会话生命周期 | 页面记录新建草稿，未提交 Run 就离开时删除；提交 Run 时清除草稿标记，防止连接阶段切换误删 | 自动化通过；用户曾报告已运行 Thread 消失，修复后用户已确认 |
| 纯思考历史恢复 | 允许 Assistant 正文为空但 reasoning 非空，避免一条合法中间消息使整页加载失败 | 用户对日本旅游会话明确回复“修复成功” |
| 多 Thread 并发 | 按 Thread 保存状态和活动 SSE，切换不 abort；另一个 Thread 可发起 Run；切回显示各自结果；侧栏显示后台运行；停止定位当前 Thread | 自动化通过；助手已实际用浏览器验证双普通 Thread 并发、切换和结果保留，用户随后已确认验收 |
| 卡住 Run 取消收敛 | 取消底层 Task 最多等待 5 秒，超时写入 interrupted 并释放 Thread | 自动化通过；原南京 Run 已 interrupted、Thread 已 idle，用户已确认本轮验收 |

最近检查：用户已验收 Prompt v38 的自然语言小功能闭环，真实 `project-test` 为 `greet` 增加关键字标点参数并保留既有行为，四项 unittest 通过。前端从持久化 `run_project_command` 时间线投影每次检查的命令、通过/失败/超时/取消/运行中/未完成状态与真实退出码，显示在独立“检查结果”审阅区；全量 37 个测试文件、274 项测试及类型、Lint、格式、构建通过，用户已完成页面与刷新恢复验收。

## 4. 当前停点与下一步动作

项目主图、通用文件 Scope、网页项目 Run、普通 Thread 常驻允许根、13.6 `glob_files`/`search_files`、13.7 可选文件引用、自动项目根概要与明确根外路径读取均已验收。用户明确文件引用不应成为 Coding 前置步骤，因此不继续优先实现手动选区引用。

当前原子点是 13.18 文档与源码一致性检查。旧 13.16 的“工作副本审阅后应用”已被用户选择的“直接修改授信项目根”取代，不再作为缺失功能；检查结果审阅区已通过页面和刷新恢复验收。下一步核对 `PROJECT.md` 的稳定能力边界并补齐项目入口说明，不重新进入已后置的安全与可靠性专项。

13.5 验收命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 examples/inspect_project_tools.py 1351f069-00b4-4b47-90fc-8de29e48b0be --ask "先列出项目根目录，再读取 README.md，解释这个项目的用途，并引用真实相对路径和行号。"
```

--ask 显式调用当前配置的真实模型，会发送被工具读取的项目内容；不创建产品 Thread/Run、checkpoint 或事件记录。第二次真实模型结果依次出现 `list_files`、`read_file` 和最终回答；目录返回 `truncated: false`，文件返回 `next_line: null`，回答引用 `README.md:3`、`:5`、`:6` 且不再误报截断。用户随后回复“继续”，13.5 已验收。

最新调整：文件工具与 Project 的第一层解耦及普通主图接入已验收，项目目录与普通对话指定文件/目录可建立同一种只读访问上下文；普通 Thread 保持 project_id=null，不隐式登记或重绑。该上下文尚未接入网页 Run。

通用只读访问上下文现已实现：`FileAccessScope` 冻结 project/explicit 来源、目标类型、规范路径和文件系统身份；`ReadOnlyFileAccess` 统一执行 list/read 与调用前后身份复核。明确授权单文件时，根列表只暴露该文件，读取兄弟文件被拒绝；明确目录继续使用根内相对路径。现有 `create_project_tools` 已改为通用工具工厂的兼容包装，项目主图行为不变。`examples/inspect_file_access.py` 可在不登记 Project、不调用模型的情况下验证明确路径。针对性 43 项、后端全量 309 项、编译和 diff 空白检查通过；用户运行样例 README 命令后回复“已验证，继续”，该原子点已验收。

普通主图新增可信 `file_access` 构图参数，与 project_service/project_id 互斥；任意文件 Scope 均排除无路径边界的 MCP，并覆盖外部伪造的 Prompt 身份。v20 工具结果带 `line_numbers`，真实模型按 list/read 顺序读取单文件并正确引用 README.md:1、:3、:5、:6，不泄露绝对路径或 Project ID。后端全量 311 项通过，用户连续回复“继续”，该原子点已验收。

网页项目 Run 调用链现为：持久 Thread.project_id → ProjectFileAccessResolver → ReadOnlyFileAccess → RunStreamService 每轮 graph_factory(file_access) → build_agent_graph。普通/不存在 Thread 返回无 Scope；项目解除、目录失效或绑定变化在模型调用前失败关闭。新版 Run 与旧 `/chat/stream` 共用解析链，请求协议未新增 project_id。针对性 41 项、后端全量 312 项通过，用户已完成页面真实模型验收。

网页接入时，项目默认范围来自持久 Thread 归属；用户本轮明确写出的根外绝对路径可成为该 Run 的附加目标；普通对话默认范围来自服务端配置的允许根集合，并使用 `workspace-N` 虚拟入口。项目登记经 v11 迁移为 `read_write`。安全与可靠性专项按用户要求暂不推进；后续覆盖编辑仍复用同一访问上下文。架构事实与待实施变更见 docs/architecture/project-readonly-agent.md。

## 5. 接手修改时的源码入口

| 范围 | 关键文件/目录 |
| --- | --- |
| Project 模型与服务 | `src/mini_deer_agent/{domain,application,persistence}/workspaces.py` |
| 路径与本地访问门禁 | `src/mini_deer_agent/workspace/paths.py`、`server/workspace_access.py`、`core/config.py` |
| 项目 HTTP 接口 | `src/mini_deer_agent/server/routers/projects.py`、`schemas/projects.py`、`dependencies.py` |
| Thread 归属与数据库迁移 | `src/mini_deer_agent/persistence/conversations.py`、`application/conversations.py` |
| 左侧项目与草稿 | `frontend/src/features/workspace/`，重点 `ui/WorkspaceLauncher.tsx`、`model/use-project-thread-draft.ts` |
| 多 Thread 状态与页面组合 | `frontend/src/features/chat/model/use-chat-run.ts`、`ui/ChatPage.tsx`、`ui/ConversationRail.tsx` |
| 项目目录与源码 | `workspace/directory.py`、`workspace/files.py`、`ui/ProjectFileTree.tsx`、`ui/ProjectFiles.tsx`（分别相对后端包和前端 workspace） |
| 项目工具 | `src/mini_deer_agent/tools/project_files.py`、`tests/test_project_tools.py`、`examples/inspect_project_tools.py` |
| 项目主图与 Prompt | `src/mini_deer_agent/agents/main/graph.py`、`agents/prompts/`、`tests/test_project_agent.py` |
| 历史解析 | `frontend/src/features/threads/api/thread-history.ts` |
| Run 执行与取消 | `src/mini_deer_agent/application/run_execution.py` |
| 本轮主要回归 | `tests/test_workspaces.py`、`tests/test_run_execution.py`、`frontend/tests/use-chat-run.test.tsx`、`use-project-thread-draft.test.tsx`、`project-manager.test.tsx` |

DeerFlow 对照仓库：`D:/project/agentstudy/deer-flow`；上次基线 `a5acc25de6742b2166b3f41c97bd895822277b94`，继续实施前重新核对。本阶段各能力的具体入口见阶段计划第 3 节。

## 6. 尚待决策的边界

- 用户已以“项目根为默认授信范围、安全与可靠性暂不涉及”取代工作副本方案；当前文件工具直接作用于授信根。后续若重新进入安全专项再评估工作副本、审批和恢复。
- **13.9/13.15** 已确认 Docker Linux 引擎可连接（29.6.2），并完成 Provider 生命周期、项目挂载及成功/失败/超时/主动停止命令闭环。
- 已支持不同 Thread 对话并发，不代表未来多个 Coding Run 可以同时写共享 Workspace。阶段计划目前要求同一 Workspace 只允许一个活动 Coding Run，文件管理写操作共用仲裁。
- Thread 上下文隔离不等于文件系统隔离；后续 Run 必须冻结项目/工作区/权限身份，不能跟随前端当前选择变化。
- 文件创建、编辑、目录创建、重命名、移动和删除已直接作用于登记目录或普通 Thread 允许根；命令仍未实现。

## 7. 本地环境与复现资料

- 项目：`D:/project/agentstudy/mini-deer-agent`。
- 前端：`http://127.0.0.1:5173`；后端：`http://127.0.0.1:8001`，Swagger 为 `/docs`。
- 真实产品历史：`data/application.sqlite`；LangGraph checkpoint：`data/checkpoints.sqlite`。保留真实数据，不重置数据库来修复显示问题。
- 当前允许根为 `D:/project/agentstudy`，覆盖真实验收目录 `project-test`；配置可能变化，接手时按需核对。当前免工作区密码，旧 MINI_DEER_WORKSPACE_API_TOKEN 配置不再使用；不要输出 `.env` 中的其他秘密。
- 后端本轮已重启以启用原生文件夹选择接口；新窗口仍需确认进程状态。启动日志在系统临时目录 mini-deer-agent-backend.stdout.log / .stderr.log。

后端启动（项目根目录）：

```powershell
.\.venv\Scripts\python.exe -m uvicorn mini_deer_agent.api:app --host 127.0.0.1 --port 8001
```

前端启动（`frontend` 目录）：

```powershell
pnpm dev
```

已有服务时不要重复启动。启用 MCP 学习示例需激活项目 venv，并使用 `MINI_DEER_MCP_CONFIG_PATH=mcp_servers.example.json`；保持用户当前配置，不擅自切换。

南京问题复现身份：Thread `bf539464-2a3e-46f1-9fc5-f153ee8f8e69`，旧 Run `426ae303-e17d-4112-8606-57291c7751e1`；上次查询为 interrupted、Thread idle。

并发实测 Thread：`f460187c-cb54-478f-b46b-b4d3be89777b`、`3d038245-d478-4f04-aba3-a1138dc7771d`，均是普通聊天。

本次 Codex 对话 ID：`01a06628-7141-73a1-bf13-3e346a55be2a`。用户曾反馈 Codex 自身历史显示缺失；本地 rollout 仍在，并已导出可读对话副本，原聊天显示尚未确认修复。这与 Mini Deer 产品 Thread 故障是两件事。

## 8. 协作与交接维护规则

- 每次只推进一个可立即验证的功能点；先讲 DeerFlow 与 Mini Deer 源码及完整调用链，再实现、检查、讲解并交用户验证。新增代码与测试使用准确中文注释。
- 用户已经选择沿用阶段计划，不重复询问是否另建设计文档。
- 用户反馈优先于自动化结论。只有明确确认后才能把该范围记为用户已验收；区分代码存在、自动化通过、助手实测和用户验收。
- 未授权不提交、重置或清理 Git 改动；不改动用户秘密配置或删除真实数据库。
- 下一次交接直接更新本文的“当前停点、实现事实、下一步”，删除失效指令；不要在尾部追加另一套当前主线。
- 历史源码解读放 `LEARNING.md`，完整实施顺序放阶段计划，稳定架构放 `PROJECT.md`；本文只保留接手所需信息。
