# 前端对话窗口工程化渲染设计概要

> 状态：功能点 0—5 已全部实现并通过用户验证；功能点 6A—6C 已完整实现，等待用户
> 一次性浏览器验证。
>
> 范围：执行时间继续属于前端对话时间线的展示元数据；复用现有 Run 查询中的
> `started_at / finished_at`，不修改当前 SSE v1 和持久化协议。

## 验证结果

用户已依次验证安全 Markdown、用户纯文本、可折叠工具步骤、刷新前后轮次顺序、粘底
滚动与“回到最新”、回答与代码复制以及 320px 窄屏适配。最终自动化结果为前端
`16 files / 111 passed`，Prettier、ESLint、TypeScript typecheck 和生产构建全部通过。

## 可观察目标

同一份历史消息和实时 SSE 时间线经过统一渲染管线后，用户可以在浏览器中看到安全、
稳定、可交互的对话内容：用户消息保持纯文本，Assistant 消息支持 Markdown，工具调用
以可折叠步骤呈现；流式输出时页面不会强行抢走用户的滚动位置，并在每轮 Agent 执行区
显示实时或已定格的总执行时间。

## 当前基线与问题

当前实现已经具备可靠的数据基础：

- `ChatTimelineItem` 使用 `message | tool` 判别联合；
- reducer 按稳定 ID 合并历史与实时项目，并维护工具状态；
- SSE 事件包含稳定 `run_id`、`message_id` 和连续 `sequence`；
- `MessageList`、`ToolActivity`、`Composer` 已经分成独立组件。

目前的渲染仍是原型级直出：

- Assistant 正文只进入 `<p>`，标题、列表、表格、引用、链接和代码块都不会渲染；
- 用户消息、Assistant 消息和工具活动直接在 `MessageList` 内部分支，缺少独立的展示投影；
- 工具参数和结果始终完全展开，长 JSON 或长文本会压过最终回答；
- 没有“仅在贴近底部时自动跟随”的滚动规则，也没有回到底部入口；
- 消息复制、流式状态、长单词溢出和渲染安全边界尚未形成统一约束。
- Run 已经有服务端开始、结束时间，但轮次投影和组件没有消费，用户看不到本轮耗时。

## DeerFlow 对照与取舍

DeerFlow 前端没有把后端消息直接映射成几个气泡，而是先派生稳定的消息分组和流式
状态，再由 `MessageList`、`MessageGroup`、`MessageListItem` 和 `MarkdownContent`
分别承担列表编排、处理中步骤、最终回答和富文本渲染。它还把滚动、长历史、工具步骤、
运行元数据等作为独立边界处理。

DeerFlow 的执行时间也采用独立组件：运行中由 `RunActivity` 每秒刷新，完成后由
`RunDuration` 显示一次 Run 的 wall-clock，并把持久化的权威耗时放在该 Run 最后一个
可见消息组之后。Mini Deer 沿用“Run 元数据独立于正文”的思路；不同点是本项目实时流
已有服务端开始时间，因此不需要把组件挂载时刻当成执行起点。

Mini Deer 学习这套职责分离，但不复制它当前的 Next.js、Tailwind、LangGraph SDK、
Vercel AI Elements、Artifact、Sidecar 和虚拟列表。当前数据量与产品能力还不需要那套复杂度。

本轮采用以下原则：

1. 历史与实时流共用一条渲染管线，不能维护两套组件。
2. 用户输入永远按纯文本显示；只有 Assistant 内容进入 Markdown 渲染器。
3. 原始时间线是业务事实，分组、是否流式、是否允许复制均为可重新计算的展示状态。
4. 工具结果和模型正文一律视为不可信内容，不允许原始 HTML 进入 DOM。
5. 先实现当前协议能真实表达的内容，不为 reasoning、artifact、citation 等未来类型伪造字段。
6. 执行时间以服务端 Run 生命周期为事实：运行中只让浏览器推进显示，结束后必须由
   `started_at / finished_at` 定格，刷新历史后仍恢复同一结果。

## 渲染架构

```text
SSE / 历史 API
      ↓
chatRunReducer（业务事实：消息、工具、状态、顺序）
      ↓
projectConversation（纯函数：按用户轮次分组、派生 streaming/final）
      ↓
ConversationTurn / UserMessage / AssistantMessage / ToolActivity
      ↓
PlainTextContent 或 MarkdownContent（安全内容边界）

Run started_at / finished_at
      ↓
RunTiming（运行中每秒刷新；终态和历史使用权威差值）
```

`MessageList` 只负责列表语义、渲染顺序与滚动容器，不再解析具体内容。建议增加仅供
展示使用的模型：

```ts
type ConversationTurn = {
  id: string;
  user: MessageTimelineItem | null;
  steps: readonly (MessageTimelineItem | ToolTimelineItem)[];
  status: "streaming" | "final" | "failed" | "cancelled";
};
```

分组以用户消息为新一轮边界，保持 `timeline` 原顺序；最后一轮的展示状态由当前
`ChatRunPhase` 派生。该投影不修改 reducer 数据，也不持久化，因此刷新历史与实时输出
自然走同一套组件。

## 核心功能

### 1. 安全消息正文

- 用户消息继续使用 `white-space: pre-wrap` 的纯文本节点，即使输入 Markdown 或 HTML
  也不解释。
- Assistant 使用统一 `MarkdownContent`，支持 GFM 常用标题、列表、引用、表格、链接、
  行内代码和围栏代码块。
- 禁止原始 HTML；链接只接受安全 URL，外链补充 `noopener noreferrer`。
- 流式阶段使用轻量代码块外观，不做重量级语法高亮；结束后仍保持相同内容结构，减少
  增量解析造成的跳动。
- 代码块需要横向滚动和语言标签；复制按钮单独作为后续原子功能接入。

技术上优先使用 `react-markdown + remark-gfm`，不引入 `dangerouslySetInnerHTML`，也不
直接搬入 DeerFlow 的 Streamdown 封装。依赖版本在实现时按当前 React 19 与 Vite 8
兼容性锁定。

### 2. 对话轮次与工具步骤

- `projectConversation()` 负责从扁平时间线生成稳定轮次，组件不自行猜测前后关系。
- Assistant 的文字与工具步骤保持服务端事件顺序，避免把工具统一移动到回答顶部或底部。
- 工具卡头部始终展示名称、状态和摘要；参数与结果放入可折叠详情。
- `pending` 默认展开，`completed` 默认收起，`failed/cancelled` 展开并显示明确状态。
- 合法 JSON 只做可读格式化，不改变或丢弃原始字符串；普通文本保持原样并限制最大可视高度。

### 3. 流式状态与滚动所有权

- 当前最后一条 Assistant 消息由页面阶段派生 `streaming`，历史消息一律视为 `final`。
- 用户位于底部阈值内时，新 delta 自动跟随；用户向上阅读后停止自动滚动。
- 离开底部且有新内容时显示“回到最新”按钮，点击后恢复跟随。
- 加载更早历史时保持当前可见锚点，不因列表头部插入内容而跳页。
- `prefers-reduced-motion` 下禁用平滑滚动和不必要动画。

### 4. 消息操作与适配

- 仅 final Assistant 消息显示整条复制；流式消息隐藏复制，避免复制到半截内容。
- 代码块提供独立复制，复制失败时保留可选择文本并显示非阻塞提示。
- 长 URL、长单词、长 JSON 和代码块不能撑破消息列。
- 保留现有桌面双栏和移动端布局；触控目标不小于 40px，并继续使用 `role="log"`、
  `aria-live="polite"` 和清晰的工具状态文本。

### 5. 执行时间

- 展示位置属于一轮对话的尾部元数据，与 Assistant 正文、工具卡和复制操作分离。
- `run_started.created_at` 到达后开始显示“执行中（n 秒）”，每秒更新一次；计时从服务端
  时间开始，不从 React 组件挂载或用户点击开始。
- Run 进入完成、失败或取消状态后，刷新现有 Run 列表的 `started_at / finished_at`，按
  `max(0, finished - started)` 定格，避免网络延迟进入最终耗时。
- 历史加载时用 Run 列表的 `user_message_id` 关联轮次的用户消息 ID，使刷新页面后的旧轮次
  仍显示相同耗时；`run_id` 继续保留为执行身份。一次 Run 即使包含多条 Assistant/工具
  记录，也只在所属轮次尾部显示一次。
- 显示精度为整秒：0 秒显示“少于 1 秒”，不足一小时显示“m 分 s 秒”，一小时以上补充
  小时；非法或不完整的时间戳不显示猜测值。
- 秒级刷新不进入 `aria-live`，避免读屏软件每秒播报；可见文本之外提供稳定的执行中说明。

## 主要文件

- `frontend/src/features/chat/model/project-conversation.ts`：纯展示投影与轮次类型。
- `frontend/src/features/chat/ui/MessageList.tsx`：列表编排、滚动容器和回到底部入口。
- `frontend/src/features/chat/ui/ConversationTurn.tsx`：一轮对话的文字与工具步骤顺序。
- `frontend/src/features/chat/ui/MessageContent.tsx`：用户纯文本与 Assistant Markdown 的安全边界。
- `frontend/src/features/chat/ui/ToolActivity.tsx`：可折叠工具步骤和长内容约束。
- `frontend/src/features/chat/model/run-timing.ts`：纯耗时计算与中文时长格式化。
- `frontend/src/features/chat/ui/RunTiming.tsx`：实时计时、终态耗时格式化和无障碍边界。
- `frontend/src/features/threads/api/thread-runs.ts`：读取并校验 Thread 的持久化 Run 列表。
- `frontend/src/features/threads/model/use-thread-runs.ts`：管理刷新、切换和失败降级。
- `frontend/src/features/threads/api/thread-history.ts`：历史项目继续保留 Run 追踪元数据。
- `frontend/src/app/styles.css`：补充 Markdown、工具详情、消息操作和滚动控件样式；暂不引入
  新 CSS 体系。
- `frontend/tests/project-conversation.test.ts` 与组件测试：覆盖投影和用户可见行为。

为了遵守小步验证，以上文件不会一次性全部改完；每个原子功能只创建或修改当步必需的
文件。

## 原子实施与验收顺序

### 功能点 0：Markdown 依赖基线

- 只安装并锁定 Markdown 依赖。
- 验证：`pnpm typecheck`、`pnpm test`、`pnpm build` 保持通过。
- 本步骤修改关键配置，验证通过后再接入页面。

### 功能点 1：Assistant Markdown / 用户纯文本

- 接入 `MessageContent`，先完成正文安全渲染，不改工具卡与滚动。
- 浏览器验证：让 Agent 返回标题、列表、链接、行内代码、代码块；再发送含 `#`、`<b>`
  的用户消息。
- 预期：Assistant 富文本正确，用户输入仍逐字显示，恶意 HTML 不执行，长代码可横向滚动。

### 功能点 2：可折叠工具步骤

- 只改工具卡展示和必要样式，不同时引入轮次操作。
- 浏览器验证：发起一次天气或搜索工具调用，展开参数与结果。
- 预期：调用中状态清楚，完成后默认收起，展开后内容完整且不撑破页面。

### 功能点 3：轮次投影

- 增加纯函数投影并让 `MessageList` 使用 `ConversationTurn`。
- 浏览器验证：连续完成“文字 → 工具 → 文字”的一轮，再刷新页面。
- 预期：实时阶段和刷新后的顺序一致，历史与实时重叠项不重复。

### 功能点 4：粘底滚动

- 增加底部检测、自动跟随和“回到最新”，不同时添加复制操作。
- 浏览器验证：生成长回答时分别停留底部和主动上滚；随后加载更早历史。
- 预期：底部时自然跟随，上滚后不抢位置，按钮能回到最新，加载历史不跳动。

### 功能点 5：复制与最终适配

- 增加整条回答复制、代码复制、长内容和移动端细节。
- 浏览器验证：流式中、完成后、复制失败降级、窄屏四种场景。
- 预期：流式内容不可误复制，完成后复制准确，320px 宽度下无横向页面溢出。

### 功能点 6A：当前 Run 实时执行时间

- 实施状态：已实现，与 6B—6C 一起等待真实浏览器验证。
- 将 reducer 中已有的服务端 `startedAt` 传入最后一个活动轮次，由独立 `RunTiming` 每秒刷新。
- 浏览器验证：发起一次会持续数秒的工具调用或回答。
- 预期：收到 `run_started` 后轮次尾部出现“执行中（n 秒）”，数字按秒增长；新 Thread 和
  历史轮次不会误显示活动计时。

### 功能点 6B：终态权威定格

- 实施状态：已实现，等待真实浏览器验证。
- Run 结束后刷新现有 Run 列表，把 `started_at / finished_at` 保存为当前轮次展示元数据。
- 浏览器验证：等待正常完成，再分别测试停止和失败路径。
- 预期：实时文案切换为“执行完成，用时 ……”或对应终态文案，数字停止变化且不包含网络延迟。

### 功能点 6C：刷新后的历史耗时恢复

- 实施状态：已实现，等待真实浏览器验证。
- 历史加载时读取 Thread 的 Run 列表并按 `user_message_id` 投影到对应轮次。
- 浏览器验证：完成两轮不同时长的对话后刷新页面，并加载更早消息。
- 预期：每轮只显示自己的服务端权威耗时，刷新前后数值一致，分页不会重复计时标签。

每完成一个功能点都暂停，由用户在真实浏览器确认后再进入下一项；未确认的功能只能标记
为“待验证”。

## 暂不包含

- reasoning/thinking 展示；
- citation、artifact、文件预览和右侧 Sidecar；
- human-in-the-loop 表单、Todo、Sub-Agent 卡片和 token usage；
- 消息编辑、重新生成和分支；
- 虚拟列表与代码语法高亮。

这些能力需要新的业务协议或真实性能需求。未来新增时应扩展展示投影和块组件，而不是把
更多条件继续堆回 `MessageList`。

## DeerFlow 参考

- [DeerFlow frontend README](https://github.com/bytedance/deer-flow/blob/main/frontend/README.md)
- [DeerFlow MessageList](https://github.com/bytedance/deer-flow/blob/main/frontend/src/components/workspace/messages/message-list.tsx)
- [DeerFlow MessageGroup](https://github.com/bytedance/deer-flow/blob/main/frontend/src/components/workspace/messages/message-group.tsx)
- [DeerFlow MarkdownContent](https://github.com/bytedance/deer-flow/blob/main/frontend/src/components/workspace/messages/markdown-content.tsx)
- [DeerFlow message utilities](https://github.com/bytedance/deer-flow/blob/main/frontend/src/core/messages/utils.ts)
