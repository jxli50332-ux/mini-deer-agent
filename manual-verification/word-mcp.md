# Word MCP 本地试用

上游：https://github.com/GongRzhe/Office-Word-MCP-Server

## 独立安装

在项目根目录执行，不向项目主环境安装 Word 依赖：

```powershell
& .venv/Scripts/python.exe -m venv data/mcp/word/.venv
& data/mcp/word/.venv/Scripts/python.exe -m pip install --no-cache-dir "office-word-mcp-server==1.1.11" "fastmcp==2.14.7"
```

`mcp_servers.word.example.json` 是 Windows 下从项目根目录启动的配置模板；
本机实际使用的 `mcp_servers.json` 将解释器和脚本路径转换为绝对路径。
`.env` 中使用 `MINI_DEER_MCP_CONFIG_PATH=mcp_servers.json`，修改后重启后端。

启动适配 `examples/mcp_word_server.py` 将上游普通 print 转到 stderr，
保留 stdout 给 MCP 协议；相对文件名默认保存到 `data/word-documents/`。
这个默认目录不是文件访问沙箱，服务仍可以接收绝对路径。

## 页面验收

1. 打开 `http://127.0.0.1:5173/api/v1/mcp/status`，检查 `word` 为 `loaded`。
2. 在普通聊天中新建会话（不要选择项目），发送：

   > 请使用 Word MCP 创建 word-demo.docx，添加标题“Word MCP 试用”、一段中文介绍和一个两列三行的功能表格。完成后用 Word MCP 读回正文，给出生成文件的绝对路径。

3. 打开生成的 Word，检查中文、标题、正文和表格是否正确。

项目会话目前隔离外部 MCP；本轮只验收 docx 读写，不包含 PDF 导出或桌面 Word 控制。
