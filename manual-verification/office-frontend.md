# 文件预览：Word、Markdown、纯文本与代码

同一个右侧面板提供 Word、Markdown、纯文本和代码预览。Excel 和 PPT 预览留待后续。

预览左边缘提供可拖动分隔条，宽度保存在本机浏览器，Word 与文本共用同一偏好。
桌面调宽时至少为导航与聊天保留 640px；平板沿用可调宽浮层，手机全宽显示。
对应 DeerFlow 的 `frontend/src/components/workspace/chats/chat-box.tsx` 共享右侧
`ResizableHandle` 思路，Mini Deer 复用 `useResizablePreference`，由
`PreviewResizeHandle` 捕获拖动并更新 CSS 列宽，不增加面板组件库依赖。

## 对照与调用链

DeerFlow 的 `backend/app/gateway/routers/artifacts.py` 提供真实产物 HTTP 访问，
`frontend/src/components/workspace/artifacts/artifact-file-detail.tsx` 展示独立文件面板。
Mini Deer 采用相同的职责划分：Word 输出目录直接发布产物；工作区和项目文本复用既有
`FileAccess` 的路径映射、目录身份复核和 UTF-8 检查，不接受任意宿主绝对路径。

Word MCP 保存到 `data/word-documents/` → 后端 Office 文档接口 → 实际文件清单
→ 聊天中的 Word 工具参数与清单核对 → 文件卡片 → 右侧内容预览或原始文件下载。

页面链接使用 `/?document=<编码后的文件名>`，复制后可以重新打开同一文档。
列表属于本机 Word 服务的产物库；聊天卡片按本轮工具涉及的文件过滤。
文本页面链接使用 `/?file=workspace-1/<路径>`；项目文本额外保留 `preview_project` 身份。
项目文件树、文本文件工具卡片和有效的工作区 Markdown 链接都进入同一面板。
此步不增加模型调用，也不修改原始文件。

## 浏览器验收

1. 打开 `http://127.0.0.1:5173`，进入先前生成财报的普通会话。
2. 点击回答下方的 Word 文件卡片，预期右侧显示中文正文、标题与表格。
3. 点击“复制链接”，在新标签打开，预期直接恢复同一文档预览。
4. 点击“下载 Word”，用 Word 打开下载结果，检查原始格式。
5. 点击右上角“文件”，可查看文档输出目录中保存的文件。
6. 关闭侧栏或按 Escape，切换会话后不应保留上一个会话的文档面板。

内容预览不模拟 Word 页码、字体、图片与全部排版；精确版式以下载的原文件为准。
7. 打开 `/?file=workspace-1/比亚迪2025年度财报分析.md`，检查“预览/源码”切换。
8. 从项目文件树打开 `PROJECT.md`、`pyproject.toml`，预期同一侧栏分别显示 Markdown 或带行号源码。
9. 点击文本文件“下载文件”，预期保留原文件的 UTF-8 BOM 和 CRLF（如有）。
10. 桌面拖动预览左侧分隔线，预期正文随宽度重排，聊天输入框仍可见；关闭重开和刷新后保留宽度。
11. 双击分隔线复位；聚焦分隔线后按左右方向键微调，Shift 加速，Home/End 到达最窄/最宽。
12. 缩小窗口检查宽度自动收敛，再放大恢复原偏好；手机隐藏分隔线并保持关闭、复制和下载可用。

Word 输出目录在线访问上限为 10 MiB；项目和工作区文本上限为 2 MiB。
预览正文最多 15 万字符，超长内容会明确提示截取。
二进制内容和非 UTF-8 文件会显示不支持提示；HTML/XML 以源码显示，不执行页面内容。
文件列表和预览复用既有本地工作区来源检查。
