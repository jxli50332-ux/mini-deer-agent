# 联网搜索工具设计概要

> 状态：功能点 1 和 2 已实现；`get_weather` 已从 Agent 注册表注销，当前只暴露
> `web_search`，等待用户界面验收。

## 架构判断

当前架构足以直接加入联网搜索工具，无需改造 Agent 图或前端协议：

- `tools/registry.py` 是工具的唯一组装入口；同一工具集合会同时传给模型和
  LangGraph `ToolNode`，不会出现“模型能请求、执行器未注册”的分叉。
- 现有工具事件、SSE、产品历史和前端 `ToolActivity` 都按通用工具名称、参数和结果
  工作，不依赖 `get_weather` 的业务结构。
- 新工具只需实现稳定的 LangChain 工具契约并加入注册表；搜索结果仍会沿现有
  `model -> tools -> model` 循环回到模型生成最终回答。

原有 `get_weather` 实现文件继续保留，但不再进入模型绑定、Prompt 工具清单或
`ToolNode`；天气问题统一通过 `web_search` 获取网页结果。

## 核心功能

1. 提供 `web_search(query, max_results=5)`，用于查询新闻、文章和时效性事实。
2. 使用无需 API Key 的 DuckDuckGo/DDGS，默认返回最多 5 条结果。
3. 将供应商结果归一化为固定 JSON：`query`、`total_results` 和
   `results[{title, url, content}]`，让模型能够引用来源链接。
4. 同时提供同步与异步调用；异步调用不阻塞 Web Run，并让取消立即终止 Agent 对
   搜索结果的等待。
5. 对空查询、无结果、超时和搜索服务异常返回清晰、有限长度的工具结果。

本轮只实现“搜索结果列表”，不包含网页全文抓取、图片搜索、多供应商动态配置或
前端专用搜索结果卡片；这些应在基础搜索真实可用后分别验证和扩展。

## 主要文件

- `src/mini_deer_agent/tools/web_search.py`：搜索、结果归一化、同步/异步工具契约。
- `src/mini_deer_agent/tools/registry.py`：注册 `web_search`。
- `src/mini_deer_agent/tools/__init__.py`：公开新工具。
- `tests/test_web_search.py`：验证工具 schema、结果格式、输入校验、异常和异步取消。
- `tests/test_agent.py`：验证模型绑定及 Prompt 中出现真实的两个工具名称。
- `pyproject.toml`：增加 `ddgs>=9.16,<10.0` 依赖。

## 技术选型

- LangChain `StructuredTool`：沿用现有天气工具模式，显式提供同步函数和 coroutine。
- `ddgs`：与 DeerFlow 默认搜索实现一致，无需新增密钥配置。
- `asyncio.to_thread`：DDGS 当前公开的是同步搜索接口；Web Run 中放到工作线程执行。
  取消后 Agent 立即停止等待且不会继续回答，但底层线程可能运行到 DDGS 的 10 秒
  HTTP 超时后才退出；不会把它误述为可强制中断底层 socket。
- JSON 文本作为 `ToolMessage` 内容：保持通用流式与持久化协议不变，也与 DeerFlow
  的标准化搜索输出思路一致。

## DeerFlow 对照与取舍

DeerFlow 通过配置加载多个同名 `web_search` 实现，默认示例使用 DDGS，并统一输出
标题、URL 和摘要。本项目当前只有两个内置工具，没有必要先引入 DeerFlow 的 YAML
反射加载、工具分组和多供应商体系；先保留现有静态注册表，复用其最重要的边界：

- 对模型只暴露稳定的 `web_search` 名称，而不暴露具体供应商。
- 在工具内部把 DDGS 的 `href/body` 归一化为 `url/content`。
- 把 `max_results` 限制在 1 至 10，并把单条摘要截到 1,000 字符，控制模型上下文体积。
- 中文查询使用 `cn-zh`，其他查询回退 `us-en`，规避 DDGS `wt-wt` 与 Wikipedia
  后端组合时产生无效语言域名的问题。

参考：

- [DeerFlow DDGS 搜索工具](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/community/ddg_search/tools.py)
- [DeerFlow 工具组装](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/tools/tools.py)
- [DeerFlow 配置说明](https://github.com/bytedance/deer-flow/blob/main/backend/docs/CONFIGURATION.md)

## 原子实现与验证顺序

### 功能点 1：独立搜索工具（已实现）

只增加依赖、`web_search.py` 和隔离网络的单元测试，暂不注册到 Agent。用户可在命令行
直接调用工具，看到结构化搜索结果；确认真实网络可用后再继续。

### 功能点 2：接入 Agent 工具循环（已实现）

把 `web_search` 加入注册表并更新 Agent 契约测试。用户在聊天页询问近期事实时，应
看到 `web_search` 调用活动，随后得到带来源链接的回答。

## 最终验收

1. 直接调用 `web_search` 搜索一个近期主题，返回 1 至 5 条包含标题、URL、摘要的结果。
2. 在聊天页提出“搜索今天的 AI 新闻并附来源”，界面显示 `web_search` 调用完成。
3. 最终回答基于工具结果并包含可访问的来源链接，而不是声称无法联网。
4. 中途取消搜索 Run 后，Run 状态能够结束为取消，不继续生成最终回答；底层搜索线程
   最迟在配置的网络超时后自然退出。

最新自动化结果：天气工具注销后，后端完整测试仍为 `76 passed`；真实天气关键词搜索
返回 2 条带 URL 的网页结果，注册表只包含 `web_search`。
