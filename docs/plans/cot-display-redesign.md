# COT 展示改造设计概要

## 参考结论

本次以同级 `deer-flow/frontend` 的真实实现为交互参考，而不是只按截图仿制：

- DeerFlow 先把 reasoning、模型中间文本和 tool call 按原始顺序统一转换为步骤，再交给同一个 COT 容器展示。
- 默认只保留当前/最后一步，并用“查看其他 N 个步骤”控制完整步骤的展开与收起。
- 工具调用只显示图标、语义化动作和少量必要结果，不展示独立的参数/结果大卡片。
- Todo 使用线程级最新快照，作为独立可折叠面板放在输入框正上方。

## 核心功能

1. **统一 COT 时间线**：把每轮的 reasoning、中间 Assistant 文本和普通工具调用合并成按时间排序的紧凑步骤；最终回答仍在 COT 外直接展示。
2. **步骤折叠**：两步及以上默认显示“查看其他 N 个步骤”和最后一步；点击后展示全部步骤，再次点击收起。流式执行期间最后一步持续更新。
3. **移除工具卡片**：普通工具不再渲染参数、完整结果和 tool call ID 卡片；改为 `搜索“关键词”`、`读取网页`、`更新任务清单`、`调用 xxx` 等一行摘要。失败、取消和执行中状态仍清晰可见，搜索链接等少量有价值结果可使用紧凑标签展示。
4. **Todo 移到输入框上方**：从完整时间线中选取最新一份合法 `write_todos` 结果，在 Composer 上方显示可折叠任务面板；空清单隐藏，刷新历史后仍可恢复。
5. **保留交互例外**：`ask_clarification` 继续直接展示为可操作澄清卡，不塞进 COT；附件、最终回答、复制按钮和 Run 耗时行为保持不变。

## 主要文件

- `frontend/src/features/chat/model/project-cot.ts`：把现有时间线项目投影为 COT 步骤，并生成工具的语义摘要。
- `frontend/src/features/chat/ui/CotTimeline.tsx`：步骤折叠、展开、状态与紧凑结果展示。
- `frontend/src/features/chat/ui/ConversationTurn.tsx`：改用统一 COT，继续分离澄清卡与最终回答，停止渲染普通工具卡。
- `frontend/src/entities/todo/model/todo-list.ts`：增加“选择最新 Todo 快照”的纯函数。
- `frontend/src/features/chat/ui/TodoPanel.tsx`、`Composer.tsx`、`ChatPage.tsx`：在输入框上方接入最新 Todo 面板。
- `frontend/src/app/styles.css`：实现 DeerFlow 风格的低密度步骤线、展开按钮和 Composer 顶部 Todo 面板。
- `frontend/tests/`：覆盖步骤顺序、折叠数量、工具摘要、澄清卡例外、最新 Todo 选择及输入框上方布局。

## 技术选型

- 保持 React 19、TypeScript 和现有原生 CSS，不引入 DeerFlow 的 Tailwind、Radix 或图标依赖。
- 继续使用当前 `ChatTimelineItem` 数据，不改 SSE、后端协议或持久化结构。
- JSON 只在投影层做安全解析以提取查询词、URL 和 Todo；原始 input/result 仍留在状态与历史中，但不再直接占用界面空间。

## 原子实施顺序

1. **COT 骨架与折叠交互**：先完成统一步骤、默认末步和“查看其他 N 个步骤”，让用户验证展开/收起与顺序。
2. **紧凑工具摘要**：替换所有普通工具卡片，让用户验证体积、状态和关键结果是否足够。
3. **Todo 面板迁移**：把最新 Todo 放到输入框上方并从工具结果区移除，让用户验证刷新、折叠和状态更新。
4. **视觉收敛与回归**：对齐间距、竖线、颜色与移动端布局，运行完整前端检查后进行最终页面验收。
