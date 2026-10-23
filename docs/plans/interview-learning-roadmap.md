# Mini Deer Agent 面试学习概要

## 学习目标

把“能够运行和修改项目”提升为“能够独立解释设计、追踪源码、定位问题并应对连续追问”。所有简历表述都要区分：已实现能力、设计预留和当前限制。

## 核心阶段

1. **一次请求的完整链路**：从 React 提交消息开始，追踪 FastAPI、RunStreamService、LangGraph、工具调用、SSE 投影和前端状态归并。
2. **Agent 编排与上下文**：理解 StateGraph、模型/工具循环、任务规划、用户澄清、上下文摘要、Durable Context、Memory 和 Sub-Agent。
3. **工具、MCP 与 Skills**：理解工具注册和执行边界、结果契约、失败阻断、输出预算、MCP 动态工具，以及 Skill 的发现、激活、安装和权限控制。
4. **持久化与可靠运行**：理解 Thread、Run、Message、RunEvent、Checkpoint 的区别，以及取消、恢复、心跳、事件顺序和并发约束。
5. **工程权衡与面试表达**：结合 Docker Sandbox、前端工作台、测试体系和当前限制，完成简历逐条举证、系统设计追问与模拟面试。

## 主要源码入口

- `src/mini_deer_agent/server/routers/runs.py`：Run HTTP/SSE 入口。
- `src/mini_deer_agent/application/run_stream.py`：单次 Agent Run 的应用编排。
- `src/mini_deer_agent/agents/main/graph.py`：主 Agent 状态图、节点、条件边和工具循环。
- `src/mini_deer_agent/agents/middleware/`：上下文、工具结果、预算、失败与循环治理。
- `src/mini_deer_agent/tools/`、`src/mini_deer_agent/mcp/`、`src/mini_deer_agent/skills/`：能力注册、外部工具和 Skills 生命周期。
- `src/mini_deer_agent/persistence/`、`src/mini_deer_agent/application/conversations.py`：Checkpoint 与产品数据持久化。
- `src/mini_deer_agent/streaming/`：LangGraph 消息到 RunEvent 和 SSE 的投影。
- `frontend/src/features/chat/`：请求发起、SSE 消费、Reducer 和执行时间线。

## 技术主线

- 后端：Python、FastAPI、LangGraph、LangChain、SQLite、SSE。
- 能力扩展：MCP、Skills、Sub-Agent、Docker Sandbox。
- 前端：React、TypeScript、Vite。
- 学习方法：原理讲解 → 源码追踪 → 实际运行 → 故障推演 → 面试复述。

## 单元验收

每次只学习一个可验证单元。完成时必须满足：

1. 能不看文档画出本单元调用链。
2. 能指出关键类、函数和状态字段所在文件。
3. 能解释至少一个设计取舍及其替代方案。
4. 能回答三轮递进追问，并明确项目当前限制。
5. 由用户实际运行或阅读关键证据确认理解后，再进入下一单元。

## 第一单元

**主题**：用户发送一条普通消息后，Mini Deer Agent 内部发生了什么？

**可观察结果**：在浏览器发送一条无需工具的消息，同时从前端请求、后端 Run、LangGraph 模型节点、SSE 事件和前端渲染五个位置找到对应证据，最终独立复述完整链路。
