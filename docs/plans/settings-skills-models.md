# 第 18 阶段：设置中心、Skill 管理、Skill 市场与模型切换设计

> 状态：已实现，并通过后端、前端、静态检查和生产构建的自动验证。
>
> 日期：2026-09-09。
>
> Mini Deer 对照基线：`2ab2e06`；DeerFlow 对照：官方 `main` 分支与 Skill Self-Evolution RFC（查阅于 2026-09-09）。

## 1. 目标

在现有聊天页面增加统一“设置”入口，并形成以下完整能力：

1. 查看全部内置、用户及市场已安装 Skill，区分来源、启用状态和可编辑性。
2. 手工管理用户 Skill，并能从可信 Skill 市场搜索、安装、更新和卸载 Skill。
3. 让 Agent 在受控流程中生成、验证并安装自己的 Skill。
4. 查看已配置模型并切换主 Agent 与 Goal 评估模型，不重启后端。
5. Skill 或模型发生变化时，活动 Run 和 Goal 续跑仍保持稳定、可追溯。

设置属于应用级配置，不属于某个 Project 或 Thread。Project 会话和普通会话共用同一套 Skill 与默认模型。

## 2. DeerFlow 参考与 Mini Deer 取舍

| DeerFlow 设计 | Mini Deer 采用方式 |
| --- | --- |
| `public` / `custom` Skill 分层，只有 custom 可编辑 | 保留现有 `builtin` / `user` 两层；内置只读，用户 Skill 可编辑 |
| Skill 只把名称和描述放入基础 Prompt，正文按需加载 | 沿用 Mini Deer 已有的渐进发现、显式激活和受控自动激活 |
| `.skill` 归档安装，安装前校验和扫描 | 新增浏览器上传 `.skill`；保留旧本地路径 API 仅作兼容，不再作为主要 UI |
| 自定义 Skill 支持编辑、历史和回滚 | 增加逐 Skill 历史；所有人工和 Agent 写入都可追踪、可恢复 |
| `skill_manage` 只写 custom 目录，公共 Skill 不可写 | Agent 只能写用户 Skill 草稿；安装或覆盖还要经过确定性校验和授权规则 |
| Agent 自我进化可关闭，写入后让后续 Run 重新发现 | 人工确认式草稿始终可用；设置中提供“允许 Agent 自动安装全新 Skill”，变更只影响之后启动的 Run |
| Marketplace、签名和权限提示在 DeerFlow Slash Skill RFC 中属于后续能力 | 不自建市场；以 ClawHub 公共 API 为首个外部目录源，在 Mini Deer 内补兼容性、权限预览和来源追踪 |
| `models:` 声明多个可信模型，API 只返回非敏感字段 | 使用受限模型配置列表；前端看不到 API Key，也不能声明任意 Python 类 |
| Run 通过 `model_name` 选择模型 | 设置保存服务端默认选择；Run 启动时解析并冻结模型快照 |

不直接复制的部分：

- DeerFlow 允许通过类路径加载任意 LangChain 模型；Mini Deer 第一版只支持已实现的 `openai` 和
  `openai-compatible` 适配器，避免设置页面变成任意代码加载入口。
- DeerFlow 的 Agent 可以直接修改 custom Skill。Mini Deer 默认使用“草稿 → 检查 → 用户确认 → 安装”，
  只有用户在一次专门的 Skill 创作任务开始前明确选择“自动安装”时，Agent 才能在校验通过后自行安装。
- DeerFlow 允许 custom Skill 覆盖同名 public Skill。Mini Deer 第一版继续禁止与内置 Skill 同名；要定制内置
  Skill，先复制为新名称，减少来源歧义。
- Mini Deer 当前 Skill 只支持 `SKILL.md` 和 `references/` 文本资源。第一版不开放 Agent 生成并执行
  `scripts/`，待独立完成可执行 Skill 的沙箱与安全设计后再扩展。

## 3. 产品设计

### 3.1 设置中心

在左侧栏底部“本地开发环境”旁增加齿轮按钮，打开应用级设置对话框。第一版只有两个页签：

- **Skills**：内部包含“已安装”“市场”“草稿”三个子页，承载详情、编辑、导入、AI 创建、历史和回滚。
- **模型**：新增模型、已配置模型、当前默认模型、Goal 评估模型、连接检查。

设置可在 Run 运行时打开。会改变执行上下文的操作需要明确提示生效范围：

- Skill 启停、安装和修改：只影响之后启动的 Run。
- 模型切换：不改变当前 Run；下一次普通 Run 使用新模型。
- 活动 Goal 的隐藏续跑：继续使用该 Goal 首次执行时冻结的模型，直到完成、清除或替换 Goal。

### 3.2 Skill 清单与人工管理

Skill 清单统一展示内置和用户 Skill：

```text
名称、描述、来源、启用状态、allowed-tools、资源数量、最近修改时间、检查状态
```

交互规则：

- 内置 Skill 可以查看正文和资源清单，可以启停，但不能编辑或删除。
- 用户 Skill 可以查看、启停、编辑、删除和回滚。
- “新建 Skill”提供内置模板编辑器，自动生成合法 YAML frontmatter 骨架。
- “导入 Skill”接收 `.skill` ZIP 归档；前端不要求用户填写后端本机路径。
- 保存前先显示校验结果；名称冲突、非法 frontmatter、越界资源、符号链接、超限文件直接拒绝。
- 删除前显示影响范围，删除操作保留最后一个可恢复版本；人工导入不接受任意远程 URL，市场安装只能走
  受信任 Registry。

现有 `UserSkillManager` 的原子目录安装、资源上限、符号链接拒绝和下一 Run 生效语义继续保留。
现有 `.skill-state.json` 在迁移后继续承载启停状态，避免已安装 Skill 丢失。

### 3.3 Skill 市场

Mini Deer 不建设或托管自己的市场服务。第一版直接复用 ClawHub 的公开只读目录与下载 API；市场搜索、
排行、版本发布、社区治理和远程存储均由 ClawHub 提供，Mini Deer 只负责适配、缓存、兼容性判断和安全安装。
后端通过 `SkillRegistryProvider` 隔离外部协议，避免把 OpenClaw 专属字段渗入本地 Skill 模型；后续可增加
需要 Vercel OIDC 的 skills.sh Provider，或面向企业私有部署的 Skilly Provider。

市场子页提供：

- 按名称、描述和标签搜索，按类别、发布者和兼容性筛选。
- 查看版本、发布者、许可证、更新说明、所需工具、资源清单、包大小和最近更新时间。
- 查看“为什么匹配当前环境”：Mini Deer 支持的 Skill 子集、所需工具和运行时要求是否满足。
- 安装、安装并启用、检查更新、查看变更、更新、回滚和卸载。
- 离线时读取上次成功同步的目录，并明确显示缓存时间，不把空网络结果误报成“市场没有 Skill”。

Provider 统一投影至少包含：

```text
provider、remote_id、name、version、description、publisher、license、tags
source_url、canonical_url、required_tools、runtime_requirements
download_ref、content_hash、scan_status、changelog、published_at
```

安装链路：

```text
从 ClawHub 公共 API 搜索并取得指定版本元数据
  → 用户选择版本
  → 后端按 API 返回的下载方式取得 ZIP 或公开 GitHub 源描述
  → 校验大小、版本/内容哈希、来源和兼容性
  → 安全解压并复用 Skill 格式/路径/资源/工具检查
  → 读取远程 scan/moderation 信息，并执行 Mini Deer 自己的静态安全扫描
  → 页面展示来源、权限和风险摘要
  → 用户确认安装或安装并启用
  → 原子写入受管目录并记录来源与版本
```

外部市场的“clean”“非可疑”或评分只作为提示，不能替代本地检查。第一版仅接受 Mini Deer 已支持的
`SKILL.md` 和 `references/` 文本资源；包含可执行脚本、二进制文件、越界路径、符号链接或未支持运行时要求的
远程 Skill 判定为不兼容，而不是尝试降级安装。远程服务不可用时仅展示带同步时间的缓存，不影响已安装 Skill。

市场安装的 Skill 使用独立 `market` 来源，默认只读，以保证签名、更新和回滚仍有明确基线。用户要修改时，
通过“复制为用户 Skill”生成新名称；不能直接改写市场包。名称与内置或用户 Skill 冲突时拒绝安装，不做静默覆盖。

更新规则：

- 默认只提示新版本，不自动更新；更新前展示版本差异和权限变化。
- 新版本新增 allowed-tools、提高最低版本或检查风险升级时，必须再次确认。
- 更新采用“先完整校验新包、再原子替换”，失败时保留旧版本和启用状态。
- 至少保留一个上一版本供回滚；卸载不影响内置或同名用户目录。
- 第一版不在应用内发布、评分或评论 Skill，也不处理 Skill 之间的自动依赖安装。

Agent 可以使用只返回市场元数据的 `skill_market_search`：当用户需要尚未安装的能力时推荐候选，或在创建
新 Skill 前检查是否已有合适实现。Agent 不能直接下载或安装；用户必须在结构化确认卡中选择具体发布者
和版本。

### 3.4 Agent 创建并安装 Skill

提供两个入口：

1. 设置 → Skills → **AI 创建 Skill**。
2. 普通任务完成后，Agent 可以建议“将这次流程保存为 Skill”；只有用户同意后才进入创作流程。

创建时提供三种模式：

- **平衡模式（默认）**：Agent 根据描述生成第一版，列出假设，用户修改或确认。
- **逐步引导**：Agent 先澄清触发条件、输入输出和边界，再生成。
- **自动完成**：用户在开始时一次性授权本次创作任务；Agent 可迭代、校验并自动安装新 Skill。

无论哪种模式，都走同一条服务端链路：

```text
需求描述
  → Agent 写入隔离草稿目录
  → frontmatter、路径、大小、工具名确定性校验
  → 静态安全扫描与内容审查
  → 生成正文/资源 Diff 和假设摘要
  → 用户确认，或使用本次“自动完成”授权
  → 原子安装并记录历史
  → 后续 Run 重新读取 Skill Catalog
```

权限边界：

- 普通聊天中的 Agent 始终可以在用户明确要求时“建议创建”和“创建草稿”，并推进到人工安装确认；不能静默
  安装、替换、启用或删除 Skill。
- 自动完成授权只对当前 Skill 创作任务、新名称和当前草稿摘要有效，不能复用于之后的 Run。
- Agent 不能写内置目录，也不能通过 `allowed-tools` 扩大运行时权限；Skill 工具权限始终与 Agent 当前真实
  工具集合取交集。
- 覆盖现有用户 Skill、删除和回滚始终要求用户确认，即使选择了自动完成。
- 每次变更记录 `author`、Thread、Run、时间、动作、前后摘要和检查结果，支持查看 Diff 和回滚。

实现上新增受控 `skill_manage` 工具，但不把宿主文件路径暴露给模型。工具第一版只支持：

```text
create_draft、update_draft、validate_draft、request_install
```

真正的 install、enable、delete 和 rollback 仍由应用服务执行，不能仅靠 Prompt 约束安全边界。

### 3.5 模型配置与切换

参考 DeerFlow 的“可信配置声明候选、Run 选择名称”模式，新增项目根目录 `models.yaml`（可由
`MINI_DEER_MODELS_CONFIG_PATH` 覆盖）。文件只保存非敏感信息；仓库提交 `models.example.yaml`，本地
`models.yaml` 不提交：

```yaml
version: 1
models:
  - name: primary-openai
    display_name: Primary OpenAI
    provider: openai
    model: gpt-5
    api_key_env: MINI_DEER_API_KEY
    supports_tools: true
    supports_reasoning: true
  - name: local-compatible
    display_name: Local Compatible
    provider: openai-compatible
    model: local-model
    base_url: http://127.0.0.1:11434/v1
    api_key_env: LOCAL_MODEL_API_KEY
    supports_tools: true
```

设计约束：

- API Key 可来自环境变量，也可在新增模型时一次性写入项目目录之外的本机凭据存储；API 和前端只返回
  “已配置/缺失”，不返回密钥内容。
- 启动时把当前 `MINI_DEER_MODEL_*` 配置映射为“环境默认”模型，保证升级后原配置继续可用。
- 模型 Profile 目录来自 `models.yaml`，当前主模型、Goal 评估模型和 revision 保存到
  `application.sqlite`；切换默认模型不会改写配置文件或 `.env`。
- 设置页可以新增受支持的模型 Profile、选择模型、查看安全元数据和执行“测试连接”；新增配置以 revision
  防止并发覆盖并原子写入 `models.yaml`，无需重启后端即可使用。
- 消息输入区显示当前主 Agent 模型并提供快捷切换；切换先保存选择，当前 Run 不变，下一次 Run 生效。
- 连接检查只发送最小请求，结果显示成功、认证失败、网络失败或能力不兼容，不自动切换默认模型。
- 主 Agent 和 Goal 评估模型分别选择；Goal 评估模型支持“跟随主模型”。
- 不做失败后的静默模型降级，避免用户以为任务由已选择模型完成。创建失败时保留旧选择并返回明确错误。

### 3.6 Run、Goal 与变更一致性

当前 Mini Deer 每次 Run 都重新构图并获取 Skill Catalog，这正好承载“下一 Run 生效”。模型选择也应在
同一边界冻结：

```text
Run 启动
  → 读取当前设置 revision
  → 解析 model profile + Skill Catalog
  → 保存 model/profile revision 与 skill catalog hash
  → 构图并执行
```

Run 启动后不再读取活动配置。设置变化不会改变正在进行的工具权限、模型或上下文。

Goal 特殊规则：

- 首次执行 Goal 时记录主模型快照；自动隐藏续跑和显式“继续续跑”沿用该快照。
- 替换或清除 Goal 会释放旧快照；新 Goal 在首次运行时重新解析当前默认模型。
- Goal 评估记录实际评估模型；更换评估默认值只影响下一次新评估。
- Run 历史和页面执行摘要显示实际模型名称，便于确认切换是否生效。

## 4. 后端接口概要

沿用现有 `/api/v1/skills`，扩展而不是再造第二套 Skill API：

```text
GET    /api/v1/skills                         全部 Skill 与安全元数据
GET    /api/v1/skills/{name}                  详情；内置正文只读
POST   /api/v1/skills/import                  上传并检查 .skill 归档
POST   /api/v1/skills/drafts                  创建人工或 Agent 草稿
PUT    /api/v1/skills/drafts/{draft_id}       更新草稿
POST   /api/v1/skills/drafts/{draft_id}/check 校验并返回检查结果
POST   /api/v1/skills/drafts/{draft_id}/install 原子安装
PATCH  /api/v1/skills/{name}                  启停用户或内置 Skill
GET    /api/v1/skills/{name}/history          变更历史
POST   /api/v1/skills/{name}/rollback         回滚用户 Skill
DELETE /api/v1/skills/{name}                  删除用户 Skill
```

市场接口与已安装 Skill API 分开，防止远程目录故障影响本地 Skill 清单：

```text
GET  /api/v1/skill-market/providers            可用外部市场及同步状态
GET  /api/v1/skill-market/catalog              跨 Provider 搜索缓存目录
POST /api/v1/skill-market/refresh              显式刷新外部目录
GET  /api/v1/skill-market/items/{provider}/{remote_id} 详情、版本与兼容性
POST /api/v1/skill-market/items/{provider}/{remote_id}/install 安装指定版本
POST /api/v1/skill-market/items/{provider}/{remote_id}/update  更新已安装市场 Skill
POST /api/v1/skill-market/items/{provider}/{remote_id}/rollback 回滚上一版本
DELETE /api/v1/skill-market/items/{provider}/{remote_id}/installation 卸载市场 Skill
```

模型接口：

```text
GET  /api/v1/models                           返回已配置模型的非敏感信息
POST /api/v1/models                           新增模型 Profile，可选密钥只写入本机凭据存储
POST /api/v1/models/{name}/probe              测试连接与必要能力
GET  /api/v1/settings/model-selection         当前主模型与评估模型选择
PUT  /api/v1/settings/model-selection         携带 revision 原子更新选择
```

所有设置写操作携带 revision。陈旧页面不能覆盖更新后的 Skill 或模型选择；冲突返回稳定 `409`，前端提示
刷新后重试。

## 5. 主要文件

后端现有入口：

- `src/mini_deer_agent/skills/user.py`：扩展统一清单、草稿、编辑、历史和回滚。
- `src/mini_deer_agent/skills/catalog.py`：继续负责包格式、资源和 allowed-tools 校验。
- `src/mini_deer_agent/server/routers/skills.py`：扩展 Skill 管理 API。
- `src/mini_deer_agent/llms/factory.py`：从模型 Profile 创建模型，不再只读取单一环境配置。
- `src/mini_deer_agent/application/run_stream.py`：Run 开始时冻结 Skill 与模型快照。
- `src/mini_deer_agent/server/app.py`：注册 Skill、模型配置和选择服务；Goal evaluator 改为按快照解析。

建议新增：

- `src/mini_deer_agent/skills/management.py`：草稿、历史、扫描和授权应用服务。
- `src/mini_deer_agent/skills/manage_tool.py`：Agent 可见的受限草稿工具。
- `src/mini_deer_agent/skills/marketplace.py`：Provider 编排、缓存、兼容性检查和市场包生命周期。
- `src/mini_deer_agent/skills/registries/base.py`：`SkillRegistryProvider` 协议与统一市场模型。
- `src/mini_deer_agent/skills/registries/clawhub.py`：ClawHub 公共 API、分页、限流、版本与下载适配。
- `src/mini_deer_agent/llms/profiles.py`：模型配置解析、非敏感投影与 revision。
- `src/mini_deer_agent/application/model_selection.py`：默认选择、Run/Goal 快照和并发更新。
- `src/mini_deer_agent/server/routers/models.py`：模型清单、连接检查和选择 API。
- `src/mini_deer_agent/server/routers/skill_market.py`：市场搜索、刷新、安装、更新和卸载 API。
- `models.example.yaml`：可提交的多模型非敏感配置示例。
- `frontend/src/features/settings/`：设置壳、页签和共享状态。
- `frontend/src/features/skills/`：Skill API、清单、编辑器、Diff 与历史。
- `frontend/src/features/skill-market/`：市场目录、详情、兼容性、权限确认和更新状态。
- `frontend/src/features/models/`：模型 API、选择器和连接检查。

## 6. 原子实施顺序

### 18.1 设置入口与只读 Skill 清单

完成齿轮入口、设置对话框和全部 Skill 清单。暂不允许修改。

验收实例：打开设置 → Skills，应同时看到内置 `structured-explainer` 和已安装用户 Skill，且来源与可编辑性正确。

### 18.2 Skill 启停、手工新建与归档导入

补齐编辑器、`.skill` 上传、校验、安装和启停；所有变化只影响下一 Run。

验收实例：新建 `concise-answer`，要求回答最多三句话；启用后发送
`/concise-answer 用五句话解释什么是上下文窗口`，结果仍不超过三句话；禁用后 slash 激活明确提示不可用。

### 18.3 Skill 编辑、删除、历史与回滚

所有修改写入历史，支持查看 Diff 和恢复上一版本。

验收实例：把 `concise-answer` 从三句话改成一句话并验证生效，再回滚，下一 Run 恢复三句话规则。

### 18.4 Skill 市场目录与详情

完成 ClawHub 同步、缓存、搜索、筛选、详情和兼容性展示，不进行安装。

验收实例：搜索 `meeting`，打开一个实际 ClawHub 结果，应看到发布者、版本、许可证、所需工具、扫描状态、
来源链接、同步时间和明确的兼容性结论；断网刷新失败后仍能看到带缓存时间的旧目录。

### 18.5 市场 Skill 安装与卸载

完成下载、签名/哈希/兼容性验证、安全解压、权限确认、原子安装、启停和卸载。

验收实例：从 ClawHub 安装并启用一个只包含受支持文本资源的 Skill 后可用 slash 激活；尝试安装包含
可执行脚本或越界路径的测试包时必须被本地检查拒绝，原已安装 Skill 不受影响。

### 18.6 市场 Skill 更新与回滚

完成更新提示、版本 Diff、权限变化再确认、原子更新和上一版本回滚。

验收实例：从 `1.0.0` 更新到新增一个 allowed-tool 的 `1.1.0` 时必须再次确认；更新后回滚，详情和实际
激活内容都恢复为 `1.0.0`。

### 18.7 Agent 创建、市场推荐与受控安装 Skill

加入市场元数据搜索、内置 Skill 创作指导、草稿工具、平衡/引导/自动三种模式和一次性安装授权。

验收实例：在设置中要求 Agent 创建“把会议记录整理为决定、行动项、负责人”的 Skill；若市场已有匹配项，
Agent 先展示候选但不能自行安装；选择继续自建后，检查假设与 Diff，安装并在新 Run 中使用。

### 18.8 模型清单、连接检查与默认切换

加载多个可信模型 Profile，设置页可选择主模型和 Goal 评估模型，不重启生效。

验收实例：从 `primary-openai` 切到 `local-compatible`，发送“只回答 OK”，Run 摘要应记录实际使用的
`local-compatible`；连接检查失败时不得改变当前选择。

### 18.9 Run/Goal 快照与跨功能回归

持久化模型 Profile revision、Skill Catalog hash，并保证 Goal 续跑不在中途换模型。

验收实例：Goal 正在自动续跑时切换默认模型，当前 Goal 的后续续跑仍记录旧模型，完成后的下一条普通消息
才记录新模型；另在普通 Run 运行中禁用一个 Skill，当前 Run 不变，之后的新 Run 不再发现该 Skill。

每个编号完成自动检查后暂停，由用户执行该编号的实例验收；确认通过后再进入下一编号。

## 7. 本阶段不做

- 任意 Git URL 安装、用户自定义市场源、多 Provider 合并和后台自动更新。
- 在应用内发布、审核、评分或评论市场 Skill；第一版只消费 ClawHub 的公开只读能力。
- 复制或自托管 ClawHub/skills.sh 的远程目录、搜索索引、用户系统和社区数据。
- 自动解析并安装 Skill 依赖；市场包必须能独立安装，缺少前置能力时明确判定不兼容。
- Agent 在普通对话中无提示地安装、覆盖或删除 Skill。
- 可执行 Skill 脚本及其宿主机执行权限。
- 读取接口回显 API Key，或把明文 API Key 写入 `models.yaml`。
- 根据任务自动路由不同模型、失败后自动换模型或按成本智能调度。
- Project/Thread 独立 Skill 集合或模型覆盖；需要真实使用需求后再增加层级。

## 8. DeerFlow 参考

- [DeerFlow Configuration Guide](https://github.com/bytedance/deer-flow/blob/main/backend/docs/CONFIGURATION.md)：模型列表、环境变量密钥和 Skill 路径。
- [DeerFlow Skill Gateway Router](https://github.com/bytedance/deer-flow/blob/main/backend/app/gateway/routers/skills.py)：清单、安装、编辑、历史、回滚、启停和缓存刷新。
- [DeerFlow API Reference](https://github.com/bytedance/deer-flow/blob/main/backend/docs/API.md)：模型安全投影与 Run 级模型选择。
- [DeerFlow Skill Self-Evolution RFC](https://github.com/bytedance/deer-flow/issues/1865)：`skill_manage`、写入边界、安全扫描、历史和开关。
- [DeerFlow Slash Skill Activation RFC](https://github.com/bytedance/deer-flow/issues/3017)：渐进发现、显式激活和运行时权限边界。
- [DeerFlow Q2 Roadmap](https://github.com/bytedance/deer-flow/issues/1669)：Skills Hub 与自我进化的路线背景。
- [DeerFlow autonomous skill creation discussion](https://github.com/bytedance/deer-flow/discussions/3781)：引导、平衡与自动创作模式的交互取舍。
- [ClawHub API v1](https://github.com/openclaw/clawhub/blob/main/docs/api.md)：公开目录复用、搜索、版本、扫描、文件与下载接口。
- [ClawHub source](https://github.com/openclaw/clawhub)：MIT 开源市场实现及 Skill 元数据约定。
- [skills.sh API](https://www.skills.sh/docs/api)：可选 Provider 的目录、搜索、审计和完整文件树接口；接入需要 Vercel OIDC。
- [Skilly](https://github.com/scalefocus/skilly)：面向企业私有部署的 Apache 2.0 Skill Registry 备选。
