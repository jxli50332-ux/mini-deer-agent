# 项目文件工具与主 Agent 图

当前项目网页 Run、普通 Thread 常驻允许根、文件操作、前端“本轮改动”清单和文件正文差异均已由用户验收；结构变化后项目文件树自动刷新已实现并等待页面验收。用户验收状态以 HANDOFF 为准。

## 已确认的演进方向

用户明确全部文件工具都应适用于普通对话和项目对话，并进一步澄清普通 Thread 在任何时候都应拥有读文件权限。Project 提供默认目录与持续的项目身份，不是工具使用前提。

文件工具与文件访问上下文已经分离：项目归属提供单一项目根，普通 Thread 始终取得服务端配置的允许根集合，两类对话复用同一文件服务、操作权限、版本检查、审批、变更恢复和写入仲裁。普通对话无需隐式创建 Project；允许根通过 `workspace-N` 虚拟路径投影，不能通过绝对路径扩张范围。

当前已完成第一层解耦、普通主图和网页 Run 接入：`FileAccessScope` 表达 project/explicit/workspace 来源以及 directory/file/roots 目标，`FileAccess` 负责绑定并执行 list/read/glob/search/create，`ReadOnlyFileAccess` 仅保留为旧调用兼容别名。网页 Run 由 `ProjectFileAccessResolver` 读取持久 Thread.project_id 和当前消息：项目 Thread 创建项目 Scope，并为本轮明确根外绝对路径组合临时附加 Scope；普通或尚不存在的 Thread 创建允许根 Scope。普通 Scope 以 `workspace-N` 隔离多个允许根。

## 构造与执行

```text
可信调用方传入 ProjectService + project_id
  → build_agent_graph
  → create_project_tools：读取登记快照，检查可用性
  → get_agent_tools：加入绑定的 list_files/read_file，项目模式排除 MCP
  → Prompt v31：项目/明确路径/普通允许根 Scope、自动项目根概要、list/read/glob/search/create/replace/write/mkdir/rename/move/delete
  → 模型请求工具 → 现有 Skills 权限路由 → ToolNode
  → 工具前后复核项目身份 → ProjectService → 有界目录/文件读取
  → ToolMessage 回到模型 → 回答
```

模型不能传 project_id 或 root_path。普通图始终创建允许根文件工具，并覆盖外部 PromptContext
中的 readonly_project_id；该字段本身不构成授权。task 子图继续使用独立工具集合。
模型与执行器共享同一批工具，现有流投影可生成包含 tool_call_id 的 tool_result。

Project Thread 的默认范围始终来自持久项目根。`RunStreamService` 把本轮用户正文交给 `ProjectFileAccessResolver`；正文中明确出现的已有 Windows 绝对文件或目录会成为该 Run 的附加目标，工具结果继续返回用户可识别的绝对路径。相对路径仍解释为项目内路径，未明确给出的根外绝对路径会被拒绝。该附加范围不写入 Project，也不自动延续到下一条消息。

`create_file(path, content)` 直接在当前目录 Scope 创建 UTF-8 文本：Project 使用相对路径，普通 Thread 使用 `workspace-N/...`，明确根外目录可使用其绝对子路径。父目录必须存在，正文上限 80 KiB，已有目标返回 `file_already_exists` 并保持原文件。Project 记录通过业务 SQLite v11 从 `read_only` 迁移为 `read_write`，Project ID、根路径和 Thread 归属保持不变。

`str_replace(path, old_str, new_str)` 直接编辑当前 Scope 中已有的 UTF-8 文本。`old_str` 必须恰好出现一次；零匹配返回 `file_replace_not_found`，多匹配返回 `file_replace_ambiguous`，两者都不写文件。实现保留原文件的 UTF-8 BOM 与 CRLF/LF 形式，成功结果包含替换前后 revision，随后由模型读回核对。

`write_file(path, content)` 使用最多 80 KiB 的完整 UTF-8 正文更新当前 Scope 中已经存在的普通文本。缺失目标返回 `file_write_missing` 并提示使用 `create_file`，不会因拼错路径意外创建文件；已有 UTF-8 BOM 会保留。局部修改仍优先交给 `str_replace`，完整更新成功后由模型读回核对。

`glob_files(pattern, path="", limit=100)` 只递归匹配普通文件名，不读取正文。项目和明确目录返回 Scope 相对路径；普通 Thread 跨全部允许根搜索时返回 `workspace-N/...`。搜索最多扫描 10,000 个目录项并受 1 秒总预算、200 条结果上限和固定忽略规则约束；`truncated` 与 `truncation_reason` 明确表示结果是否完整。链接、重解析点、敏感项和越界路径不会成为结果。

`search_files(query, path="", file_pattern=null, case_sensitive=false, limit=100)` 搜索字面量正文，返回虚拟路径、真实行号和有界单行摘要。它与 glob 使用相同路径、忽略、链接和 Scope 边界，并增加文件数、单文件/累计字节、输出字符与超长行预算；跳过或耗尽预算必须标记结果不完整。首版不接受任意正则。

项目文件预览可把项目相对路径显式追加到当前 Composer 草稿。引用只在当前 Thread 的持久 `project_id` 与文件树 Project 一致时启用，不复制正文且不自动提交；普通 Thread 仍通过自己的 `workspace-N` 路径使用相同读取工具，页面不把项目相对路径误当成普通 Scope 路径。

Project Run 在构图时通过同一个 `ReadOnlyFileAccess` 获取一次根目录快照，最多保留 40 个可用直接子项和截断位。概要只用于让模型自主选择下一步探索位置，不替代任何正文读取；它不含绝对根，在 Prompt 中作为经过转义的不可信路径元数据。基础系统提示会在工具循环和摘要投影后重新进入模型视图，因此该 Run 的项目身份与概要不依赖有损对话摘要。普通 Thread 不注入项目概要。

ProjectService/根路径检查和内容预算沿用 13.3—13.4。每次工具调用检查项目是否解除登记、
失效或替换；OS 只读操作的线程取消和文件竞争限制不因接入模型而消失。

## 当前入口

页面项目入口已简化：useProjects 挂载自动查询项目；WorkspaceLauncher 按项目→会话缩进展示，默认五条会话并可展开其余。标题“＋”通过本地后端打开 Windows 原生文件夹选择器，选中目录经既有允许根策略登记后自动展开真实路径和文件树；“···”打开保留登记、刷新和解除登记的管理弹窗。ProjectAccess 不再携带 token，服务端 Settings 和项目路由不再要求工作区密码；保留允许目录与本地请求来源检查。刷新无需连接或解锁，卸载仍取消请求并拒绝迟到响应。

examples/inspect_project_tools.py 的 --ask 使用正式 build_agent_graph，未装配持久化
checkpointer、MemoryStore 或 MCP。当前配置的模型会收到工具读取的文件内容。
脚本输出实际图节点消息，设定 24 个图步和 180 秒等待；原 --path 模式不调用模型。
脚本不创建产品 Thread/Run，不能当作 HTTP 授权或产品历史隔离的验证。

## 网页接入后的边界

- 项目默认范围来自持久 Thread.project_id；普通对话范围来自服务端配置的允许根集合。每轮构图冻结访问范围，不接受模型参数自由换根。
- 两类文件 Run 启动/取消及历史内容、事件读取共用访问门禁，覆盖旧兼容入口，不以 project_id 是否存在作为保护内容的唯一依据。
- 用户已明确采用个人本地免密码模式：项目自动加载，接口不再要求工作区 token。后续文件 Run 复用本地来源和文件范围检查，不重新添加连接/锁定流程；这不是公开部署的身份认证方案。
- 核对项目内容在共享 Memory 与不同 Thread/checkpoint 之间的边界。

## DeerFlow 对照

本地基线 a5acc25de6742b2166b3f41c97bd895822277b94。
backend/packages/harness/deerflow/tools/tools.py 负责工具组装；
agents/lead_agent/agent.py 过滤后交给 create_agent；sandbox/tools.py 的 read_file_tool
通过运行时读取沙箱文件。Mini Deer 使用已有显式 LangGraph 和已登记的只读 Project，
不把 DeerFlow 的沙箱虚拟路径解释成宿主机任意路径。

`rename_file(path, new_name)` 在目录 Scope 中对普通文件做同目录改名，返回 previous_path、新 path 和 renamed。目标已存在不覆盖，同名原样返回 renamed=false；不提供目录改名、跨目录移动或单文件 Scope 改名。

`move_file(path, new_path)` 在同一个目录 Scope 或普通 Thread 的同一个 `workspace-N` 根内移动普通文件。目标父目录必须存在，目标路径已存在时不覆盖；成功返回 `previous_path`、新 `path` 与 `moved=true`。Project Thread 的明确根外目录可使用两个绝对路径，不能在项目根与附加目录之间跨 Scope 移动。

`delete_file(path)` 只删除一个普通文件，不接受目录或递归删除。目录 Scope、普通 Thread 虚拟根和用户本轮明确给出的单文件均可使用；单文件删除成功后该次 Scope 的目标自然失效。工具返回被删除路径、字节数和 `deleted=true`，模型随后列目录确认。

前端 `projectChanges` 从每个 Conversation Turn 已持久化的 ToolTimelineItem 投影操作级变化。只有 completed 且结果 `ok=true`、语义字段表明确有变化的 create/write/replace/mkdir/rename/move/delete 才进入清单；失败、pending、不可解析结果和 `changed=false` 不展示。该清单不依赖新的前端瞬时状态，刷新后由历史时间线重新生成。

`str_replace` 成功项同时从持久化工具输入提取 old_str/new_str，标准化 CRLF 后逐行显示删除与新增片段。每侧展示上限为 4000 字符，超出时明确标记截断，避免大型工具参数造成页面渲染负担。该视图展示精确替换片段，还不是完整文件 unified diff。

`write_file` 成功且实际变化时，文件服务在工具结果中保存更新前最多 4000 字符的 UTF-8 正文预览和截断标记；前端将它与已持久化的 `content` 工具输入组合成删除/新增两侧。差异因此绑定写入发生时的真实旧内容，刷新后可恢复，也不会事后读取已被覆盖的文件来猜测旧版本。

`create_file` 成功项直接从持久化的 `content` 工具输入生成正文差异。由于文件此前不存在，界面只渲染绿色新增行，不显示虚假的空白删除块；正文同样受 4000 字符展示上限约束。

`delete_file` 在删除普通文件前尝试生成最多 4000 字符的 UTF-8 正文预览，并随成功工具结果持久化。前端据此只渲染红色删除行。二进制、非 UTF-8 或超过文本读取上限的文件继续执行原有删除语义，但不展示正文差异，避免把不可解释的字节伪装成文本。

聊天流把每个正式 SSE 事件交给页面回调。成功的新建文件/目录、重命名、移动或删除会按 `run_id` 记录结构变化；对应 Run 进入终态时只递增一次文件树刷新版本，纯正文编辑不会重复加载目录。刷新版本向所有已展开目录传播，React effect 清理会取消旧请求，避免迟到结果恢复旧结构。
