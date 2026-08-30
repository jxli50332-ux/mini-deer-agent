.\.venv\Scripts\python.exe -m uvicorn mini_deer_agent.api:app --host 127.0.0.1 --port 8001```powershell
.\.venv\Scripts\python.exe -m uvicorn mini_deer_agent.api:app --host 127.0.0.1 --port 8001# Mini Deer Agent 从零学习手册

这不是一份一次性写完的教程，而是一份会和项目代码一起生长的学习记录。

我们以 DeerFlow 为架构参考，但不会直接复制它。每一课只完成一个可以立即运行和验证的小功能：先理解最小原理，再看代码，最后亲手验证。

## 学习方式

每一课固定包含以下内容：

1. **本课目标**：这一次只解决什么问题。
2. **核心原理**：先理解为什么需要它。
3. **代码解读**：说明新增文件和关键代码。
4. **运行验证**：给出可以直接执行的命令和预期结果。
5. **常见问题**：记录容易踩到的坑。
6. **本课小结**：确认真正掌握了什么。

只有当前一课验证通过后，我们才进入下一课。如果运行结果和文档不一致，先修复当前问题，不继续堆叠功能。

## 学习路线

1. 项目骨架与健康检查
2. 配置系统与环境变量
3. 第一次调用大模型
4. 用 LangGraph 建立 Agent 状态图
5. 增加工具调用循环
6. 保存线程和对话历史
7. 流式返回 Agent 输出
8. 制作最小聊天页面
9. 在基础闭环稳定后，再学习沙箱、子代理、MCP 和 Skills

---

# 第 0 课：建立安全、独立的学习仓库

## 本课目标

确保学习项目和官方 DeerFlow 仓库完全分离，后续代码只会进入自己的 `mini-deer-agent` 仓库。

## 核心原理

一个本地 Git 仓库主要由两部分组成：

- **工作目录**：我们实际编辑的文件。
- **`.git` 目录**：保存提交历史、分支和远程仓库地址等 Git 元数据。

Git 中通常把远程仓库命名为 `origin`。执行 `git push` 时，Git 会根据当前仓库的远程配置决定代码发往哪里。因此，在提交或推送前检查“当前目录”和“远程地址”，是避免误操作最简单有效的方法。

当前两个仓库的位置是：

```text
D:\project\agentstudy\deer-flow       官方项目，仅作为参考
D:\project\agentstudy\mini-deer-agent 我们自己的学习项目
```

它们各自拥有独立的 `.git` 目录，所以提交历史和远程地址互不影响。

## 当前状态

学习仓库的远程地址应当是：

```text
https://github.com/jxli50332-ux/mini-deer-agent.git
```

官方 DeerFlow 仓库仍然保留自己的远程地址：

```text
https://github.com/bytedance/deer-flow.git
```

## 运行验证

在 PowerShell 中执行：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
git remote -v
git status --short
```

预期看到 `origin` 的 fetch 和 push 地址都指向：

```text
https://github.com/jxli50332-ux/mini-deer-agent.git
```

`git status --short` 当前会显示尚未提交的学习文档和设计文档，这是正常现象。

## 安全约定

后续开发遵守三条规则：

1. 新代码只写入 `D:\project\agentstudy\mini-deer-agent`。
2. 提交前检查 `git remote -v` 和 `git status --short`。
3. `.env`、API Key、访问令牌等敏感配置永远不提交到 Git。

## DeerFlow 参考仓库约定

本地官方 DeerFlow 仓库位于：

```text
D:\project\agentstudy\deer-flow
```

后续学习和实现过程中，如需了解 DeerFlow 的架构或具体做法，可以自行读取该仓库作为参考，但必须遵守以下边界：

1. DeerFlow 仓库仅用于只读参考，不在其中修改、提交或推送任何内容。
2. 所有学习代码和文档改动只写入 `D:\project\agentstudy\mini-deer-agent`。
3. 借鉴 DeerFlow 的核心思路时，优先重新实现最小版本，不直接复制其完整生产架构。

## 常见问题

### 为什么不直接在 DeerFlow 仓库里新建一个文件夹？

因为它仍会受 DeerFlow 的 Git 仓库管理。稍不注意就可能把学习文件和上游项目改动混在一起。独立仓库的边界更清晰，也更适合从零学习。

### GitHub 上的仓库为什么暂时是空的？

我们目前只完成了本地隔离，还没有获得提交和推送授权。等第一批文件经过确认后，再明确执行提交和推送。

## 本课小结

完成这一课后，你应该理解：

- 本地目录不等于 Git 远程仓库。
- `.git` 决定当前目录属于哪个仓库。
- `origin` 是远程仓库的常用名称。
- 开发前确认目录，推送前确认远程，可以有效避免误提交。

下一课将创建最小 Python 项目骨架，并实现一个无需大模型 API Key 就能验证的 `/health` 健康检查接口。

---

# 第 1 课：项目骨架与健康检查

## 功能点 1.1：项目骨架与应用入口

### 本次目标

建立最小 Python 项目，使 FastAPI 应用对象可以被正常导入。本功能点暂不添加 `/health` 接口。

### 核心原理

Uvicorn 启动 FastAPI 服务时，需要找到一个可以导入的 Python 应用对象：

```text
mini_deer_agent.api:app
```

其中 `mini_deer_agent.api` 是模块路径，`app` 是模块中的 FastAPI 应用对象。只有项目安装方式、包结构和依赖都正确，Uvicorn 才能找到它。

项目采用 `src` 布局，将源码放在 `src/mini_deer_agent` 中。这样测试使用的是实际安装的包，可以更早发现打包或导入配置错误。

### 源码解读

#### `pyproject.toml`

- `[build-system]` 指定使用 `setuptools` 构建和安装项目。
- `[project]` 声明项目名称、版本、Python 版本和运行依赖。
- FastAPI 用于定义应用和接口，Uvicorn 用于监听端口和处理 HTTP 连接。
- `dev` 依赖中的 pytest 和 `httpx2` 用于测试。FastAPI 的 `TestClient` 在当前依赖版本中使用 `httpx2` 模拟 HTTP 请求。
- `where = ["src"]` 告诉 setuptools 在 `src` 目录寻找 Python 包。

安装名称使用 `mini-deer-agent`，Python 导入名称使用 `mini_deer_agent`，因为模块名不能包含连字符。

#### `src/mini_deer_agent/__init__.py`

这个文件让 `mini_deer_agent` 成为一个明确的 Python 包。

#### `src/mini_deer_agent/api.py`

```python
from fastapi import FastAPI

app = FastAPI(title="Mini Deer Agent")
```

第一行导入 FastAPI 应用类，第二行创建真正的应用对象。此时应用可以导入，但还没有注册任何业务接口。

#### `tests/test_app_import.py`

测试先导入 `app`，然后用 `isinstance` 确认它确实是 FastAPI 应用。pytest 会自动发现以 `test_` 开头的测试文件和测试函数。

#### `.gitignore`

忽略本地虚拟环境、Python 缓存、pytest 缓存和 `.env`，避免把生成文件或敏感配置提交到 Git。

### 运行验证

在 PowerShell 中执行：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
.\.venv\Scripts\python.exe -m pytest tests\test_app_import.py -q
.\.venv\Scripts\python.exe -c "from mini_deer_agent.api import app; print(app.title)"
```

预期分别看到：

```text
1 passed
Mini Deer Agent
```

### 常见问题

如果 PowerShell 禁止执行 `Activate.ps1`，不必修改系统执行策略，可以直接调用 `.venv\Scripts\python.exe`。

### 功能点 1.1 小结

完成这一功能点后，已经掌握：

- `pyproject.toml` 如何描述一个 Python 项目。
- `src` 布局如何把源码组织成可安装的包。
- `mini_deer_agent.api:app` 入口字符串的含义。
- 如何用最小测试验证应用对象能够正确导入。

下一个功能点将在这个应用对象上注册 `GET /health` 接口。

## 功能点 1.2：健康检查接口

### 本次目标

增加 `GET /health` 接口。服务正常运行时，接口返回 HTTP 200 和固定 JSON：

```json
{"status":"ok"}
```

健康检查不依赖大模型、数据库或 API Key，因此可以用它快速判断 Web 应用本身是否已经成功启动。

### 核心原理

FastAPI 使用路由装饰器，把一个 HTTP 方法和 URL 路径绑定到 Python 函数：

```python
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

收到 `GET /health` 请求后，FastAPI 匹配装饰器、调用 `health()`，再把返回的 Python 字典自动序列化成 JSON。没有显式指定状态码时，成功响应默认为 HTTP 200。

### 源码解读

#### `src/mini_deer_agent/api.py`

- `@app.get("/health")` 将 GET 请求和 `/health` 路径注册到应用。
- `health()` 是处理请求的普通同步函数。
- `dict[str, str]` 表明返回字典的键和值都是字符串。
- 返回字典后，由 FastAPI 完成 JSON 序列化。

请求流程如下：

```text
GET /health
    → FastAPI 匹配路由
    → 调用 health()
    → 返回 Python 字典
    → 转换为 JSON 和 HTTP 200
```

#### `tests/test_health.py`

`TestClient(app)` 在进程内模拟 HTTP 客户端，不需要先启动真实端口。测试发送 `GET /health`，然后分别验证：

1. `response.status_code == 200`：接口请求成功。
2. `response.json() == {"status": "ok"}`：响应内容完全符合约定。

本功能点先编写测试。路由尚未实现时，测试得到 404 并失败；加入最小路由后测试通过。这是一次最小的“红 → 绿”测试驱动过程。

### 运行验证

先运行全部自动测试：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
.\.venv\Scripts\python.exe -m pytest -q
```

预期输出包含：

```text
2 passed
```

然后启动真实服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn mini_deer_agent.api:app --reload
```

在浏览器访问：

```text
http://127.0.0.1:8000/health
```

预期看到：

```json
{"status":"ok"}
```

还可以访问 `http://127.0.0.1:8000/docs`，查看 FastAPI 自动生成的接口页面。验证结束后在启动服务的终端按 `Ctrl+C` 停止。

### 常见问题

#### 为什么访问根路径 `/` 会返回 404？

当前只注册了 `/health`，还没有为 `/` 定义路由，因此 404 是正确结果。

#### 为什么测试接口时不需要启动 Uvicorn？

`TestClient` 直接调用 ASGI 应用，可以快速验证应用内部行为；浏览器验证则会经过真实端口，用于确认 Uvicorn、FastAPI 和路由能够完整协作。

### 本课小结

完成本课后，已经掌握：

- 创建可安装的 Python `src` 布局项目。
- 创建能够被 Uvicorn 导入的 FastAPI 应用对象。
- 使用装饰器注册 GET 路由。
- 理解 Python 字典如何变成 JSON 响应。
- 使用 pytest 和 `TestClient` 验证状态码与响应内容。
- 先观察测试失败，再用最小实现让测试通过。

下一课将学习配置系统与环境变量，为后续安全地连接大模型做准备。

---

# 第 2 课：配置系统与环境变量

## 功能点 2.1：配置模型与默认值

### 本次目标

建立一个集中、可校验的配置模型，先管理模型提供方和模型名称。配置类能够在没有 `.env` 和 API Key 的情况下创建，不影响现有健康检查。

### 核心原理

配置不应散落在业务代码里。Pydantic Settings 将“字段定义、外部读取和类型校验”集中到一个类中。创建 `Settings` 时，它会检查环境变量，解析字段类型，并在没有外部值时使用代码中的安全默认值。

当前配置读取流程是：

```text
Settings()
    → 检查 MINI_DEER_ 开头的环境变量
    → 解析并校验字段类型
    → 没有外部值时使用默认值
```

完整 DeerFlow 使用 YAML 模型列表，并通过 `$OPENAI_API_KEY` 等表达式引用环境变量。学习项目先实现同一个核心原则：配置与业务代码分离，敏感信息以后由外部环境提供。

### 源码解读

#### `pyproject.toml`

- `pydantic` 提供字段类型、数据校验和后续使用的秘密类型。
- `pydantic-settings` 在 Pydantic 基础上增加环境变量和 `.env` 读取能力。
- 它们属于运行依赖，因为应用启动时需要读取配置。

#### `src/mini_deer_agent/config.py`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MINI_DEER_",
        extra="ignore",
    )

    model_provider: str = "openai"
    model_name: str | None = None
```

`Settings` 继承 `BaseSettings`，因此字段既可以使用默认值，也可以从外部配置读取。

`env_prefix="MINI_DEER_"` 为项目环境变量增加独立前缀：

```text
model_provider → MINI_DEER_MODEL_PROVIDER
model_name     → MINI_DEER_MODEL_NAME
```

`extra="ignore"` 表示配置来源包含未定义字段时忽略它们。

`model_provider` 默认使用非敏感字符串 `openai`。`model_name` 使用 `str | None`，表示可以是模型名称字符串，也可以是尚未配置时的 `None`。这里不默认指定具体模型，避免假设用户使用某个可能变化的模型。

#### `tests/test_config.py`

默认值测试使用 pytest 的 `monkeypatch` 临时删除同名系统环境变量，避免用户电脑上的配置影响测试。测试结束后 pytest 会恢复原环境。

```python
settings = Settings(_env_file=None)
```

`_env_file=None` 明确禁止本次实例读取 `.env`。这样以后加入 `.env` 支持后，这个测试仍然只验证代码默认值。

### 运行验证

在 PowerShell 中执行：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
.\.venv\Scripts\python.exe -m pytest tests\test_config.py -q
.\.venv\Scripts\python.exe -c "from mini_deer_agent.config import Settings; print(Settings(_env_file=None))"
```

预期分别看到：

```text
1 passed
model_provider='openai' model_name=None
```

### 常见问题

#### 为什么模型名称不提供默认值？

模型名称会随提供方和账号能力变化。使用 `None` 可以让健康检查等无模型功能继续工作，同时把“是否已配置模型”的判断留到真正调用模型之前。

#### `_env_file=None` 会忽略系统环境变量吗？

不会。它只关闭 `.env` 文件读取，所以测试还需要用 `monkeypatch.delenv` 隔离系统环境变量。

### 功能点 2.1 小结

完成这一功能点后，已经掌握：

- Pydantic 与 Pydantic Settings 的职责区别。
- 如何用 `BaseSettings` 集中定义配置。
- 环境变量前缀如何减少命名冲突。
- `str | None` 如何表达“配置尚未提供”。
- 如何隔离外部环境并测试配置默认值。

下一个功能点将读取环境变量和 `.env`，并使用秘密类型保护 API Key。

## 功能点 2.2：环境变量、`.env` 与秘密配置

### 本次目标

让 `Settings` 从系统环境变量和 `.env` 文件读取模型配置，同时隐藏 API Key 的普通输出，并提供一个不含真实密钥的公开配置模板。

### 核心原理

代码负责定义“允许有哪些配置”，运行环境负责提供“这次使用什么值”。同一套代码因此可以在不同机器上使用不同模型和密钥，而不需要修改源码。

本项目使用以下配置名称：

```text
model_provider → MINI_DEER_MODEL_PROVIDER
model_name     → MINI_DEER_MODEL_NAME
api_key        → MINI_DEER_API_KEY
api_base_url   → MINI_DEER_API_BASE_URL
```

真实 `.env` 只属于当前机器并已被 Git 忽略；`.env.example` 只列出字段模板，可以安全提交。

### 源码解读

#### `src/mini_deer_agent/config.py`

```python
model_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    env_prefix="MINI_DEER_",
    env_ignore_empty=True,
    extra="ignore",
)
```

- `env_file=".env"`：创建 `Settings()` 时默认读取当前工作目录中的 `.env`。
- `env_file_encoding="utf-8"`：固定配置文件编码。
- `env_prefix="MINI_DEER_"`：为项目环境变量增加独立前缀。
- `env_ignore_empty=True`：模板中的空白值不覆盖字段默认值。
- `extra="ignore"`：忽略当前配置模型尚未定义的额外字段。

新增的配置字段是：

```python
api_key: SecretStr | None = None
api_base_url: AnyHttpUrl | None = None
```

`SecretStr` 会在配置对象的普通字符串输出中把密钥显示为星号。它不是加密存储；真正调用模型时仍可通过 `get_secret_value()` 显式取得原值，因此不能随意打印该方法的结果。

`AnyHttpUrl` 校验 Base URL 是否是 HTTP 或 HTTPS 地址。该字段可选，只有使用兼容网关或本地模型服务时才需要设置。

#### `.env.example`

模板包含：

```dotenv
MINI_DEER_MODEL_PROVIDER=openai
MINI_DEER_MODEL_NAME=
MINI_DEER_API_KEY=
MINI_DEER_API_BASE_URL=
```

复制模板后只编辑真实 `.env`：

```powershell
Copy-Item .env.example .env
```

`.env.example` 可以提交，真实 `.env` 不得提交。

#### `tests/test_config.py`

配置测试现在覆盖四种行为：

1. 没有外部配置时使用安全默认值。
2. 系统环境变量可以覆盖默认值，且配置对象输出不含明文密钥。
3. `Settings(_env_file=...)` 可以读取指定的临时 `.env`。
4. `.env.example` 中的空白占位符会保持为 `None`。

环境变量测试使用 pytest `monkeypatch`，临时 `.env` 测试使用 `tmp_path`。两者都不会污染用户的真实系统配置或项目 `.env`。

### 测试驱动过程

增加新测试但尚未定义秘密字段时，配置测试出现 `3 failed`。加入 `.env` 设置、秘密字段和 Base URL 后测试转绿；再增加模板保护测试，完整测试最终为 `6 passed`。

### 运行验证

先运行全部测试：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
.\.venv\Scripts\python.exe -m pytest -q
```

预期看到：

```text
6 passed
```

再使用当前 PowerShell 会话中的临时变量验证覆盖和密钥隐藏：

```powershell
$env:MINI_DEER_MODEL_NAME = "demo-model"
$env:MINI_DEER_API_KEY = "demo-secret"
.\.venv\Scripts\python.exe -c "from mini_deer_agent.config import Settings; print(Settings(_env_file=None))"
Remove-Item Env:\MINI_DEER_MODEL_NAME
Remove-Item Env:\MINI_DEER_API_KEY
```

预期输出包含：

```text
model_name='demo-model'
api_key=SecretStr('**********')
```

普通输出中不应出现明文 `demo-secret`。

### 常见问题

#### `SecretStr` 是否代表 API Key 已经加密？

不是。它只隐藏常见的字符串表示，降低日志和调试时意外泄露的风险。程序仍然必须能取出真实值并发送给模型服务。

#### `.env` 和系统环境变量同时存在时使用哪个？

系统环境变量优先于 `.env`。这允许部署环境在不修改文件的情况下覆盖本地配置。

#### 为什么模板中的空值没有变成空字符串？

`env_ignore_empty=True` 会忽略空白配置，让可选字段继续使用默认值 `None`。

### 本课小结

完成本课后，已经掌握：

- 使用 `BaseSettings` 集中定义和读取配置。
- 使用项目专用环境变量前缀。
- 区分可提交的 `.env.example` 与不可提交的 `.env`。
- 使用 `SecretStr` 降低密钥意外泄露风险。
- 使用 `AnyHttpUrl` 校验可选服务地址。
- 隔离并测试默认值、系统环境变量、`.env` 和空白模板。

下一课将使用这些配置创建聊天模型，并完成第一次真实的大模型调用。

---

# 第 3 课：第一次调用大模型

## 功能点 3.1：模型配置校验与工厂

### 本次目标

把第 2 课的 `Settings` 转换为 LangChain `ChatOpenAI` 模型对象。创建对象时只整理和校验配置，不发送网络请求。

### 核心原理

模型 SDK 的构造参数不应散落在业务代码中。统一的模型工厂把“配置校验、提供方差异和 SDK 构造”集中在一个入口：

```text
Settings
    → 检查必要配置
    → 判断模型提供方
    → 整理 ChatOpenAI 参数
    → 创建聊天模型对象
```

以后 LangGraph、HTTP API 和工具循环只调用模型工厂，不需要重复理解密钥、Base URL 和提供方参数。

### 源码解读

#### `pyproject.toml`

新增 `langchain-openai` 运行依赖。它提供 `ChatOpenAI`，并通过统一的 LangChain 聊天模型接口为下一课接入 LangGraph 做准备。

#### `src/mini_deer_agent/models.py`

```python
def create_chat_model(settings: Settings | None = None) -> ChatOpenAI:
    settings = settings or Settings()
```

调用者可以显式传入配置，也可以不传参数，让 `Settings()` 自动读取 `.env`。创建 `ChatOpenAI` 对象本身不会请求模型，只有调用 `.invoke()` 等方法时才会访问网络。

模型名称和 API Key 在 `Settings` 中允许暂时为 `None`，使 `/health` 等无模型功能仍可启动；进入模型工厂后，它们成为必需值：

```python
model_name = (settings.model_name or "").strip()
if not model_name:
    raise ValueError("MINI_DEER_MODEL_NAME is required to create a chat model")
```

API Key 使用 `get_secret_value()` 检查是否为空，但不会被打印或记录。错误信息直接包含需要修复的环境变量名称。

提供方名称先通过 `strip().lower()` 标准化。工厂支持两个明确分支：

```text
openai
    → 使用官方默认地址
    → use_responses_api=True

openai-compatible
    → 必须提供 MINI_DEER_API_BASE_URL
    → use_responses_api=False
```

官方 OpenAI 文档建议新的文本生成应用优先使用 Responses API，因此官方分支显式启用它：[OpenAI 文本生成指南](https://developers.openai.com/api/docs/guides/text)。第三方兼容网关未必支持 Responses API，所以兼容分支不强制使用。

未知提供方会立即抛出 `ValueError`，避免把拼写错误带到远程请求阶段。

#### `tests/test_models.py`

前四个测试分别验证：

1. 缺少模型名称。
2. 缺少 API Key。
3. 使用未知提供方。
4. 兼容提供方缺少 Base URL。

后两个测试使用 `monkeypatch` 把真正的 `ChatOpenAI` 临时替换为测试函数。测试函数只捕获构造参数，不创建客户端、不访问网络。测试结束后 pytest 会自动恢复真实类。

测试分别确认官方分支启用 Responses API，以及兼容分支传递 Base URL 并关闭 Responses API。

### 测试驱动过程

测试最初因为 `mini_deer_agent.models` 不存在而在收集阶段失败。加入依赖和最小模型工厂后，模型专项测试为 `6 passed`，完整测试为 `12 passed`。

随后使用假密钥构造真实 `ChatOpenAI` 对象，确认当前 SDK 接受这些参数。整个过程没有调用 `.invoke()`，因此没有发送网络请求。

### 运行验证

运行模型工厂测试：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
.\.venv\Scripts\python.exe -m pytest tests\test_models.py -q
```

预期看到：

```text
6 passed
```

再使用假配置验证对象构造：

```powershell
.\.venv\Scripts\python.exe -c "from mini_deer_agent.config import Settings; from mini_deer_agent.models import create_chat_model; model=create_chat_model(Settings(model_name='test-model', api_key='fake-key', _env_file=None)); print(type(model).__name__, model.model_name, model.use_responses_api)"
```

预期看到：

```text
ChatOpenAI test-model True
```

### 常见问题

#### 为什么 `Settings` 允许缺少配置，模型工厂却不允许？

配置对象需要支持健康检查等无模型场景；模型工厂是即将使用模型的边界，所以必须在这里拒绝不完整配置。

#### 创建 `ChatOpenAI` 会消耗额度吗？

不会。只有调用 `.invoke()`、`.stream()` 等请求方法时才会向模型服务发送请求。

#### 为什么测试要替换 `ChatOpenAI`？

单元测试只验证我们的参数整理逻辑，不应依赖网络、真实密钥、模型权限或余额。真实 SDK 构造另行使用假密钥验证，真实请求留到下一功能点由用户执行。

### 功能点 3.1 小结

完成这一功能点后，已经掌握：

- 为什么用模型工厂隔离 SDK 构造。
- 如何在真正使用模型的边界校验必要配置。
- 如何区分官方 OpenAI 和 OpenAI 兼容接口。
- 创建模型对象与发送模型请求的区别。
- 如何用 `monkeypatch` 验证构造参数而不访问网络。

下一个功能点将调用模型的 `.invoke()`，完成第一次真实单轮回复。

## 功能点 3.2：调用 DeepSeek-V4-Flash

### 本次目标

通过 DeepSeek 官方的 OpenAI 兼容接口调用 `deepseek-v4-flash`，输入一条用户消息并返回模型回复文本，完成第一个真实大模型闭环。

### 模型配置

DeepSeek 官方文档给出的 OpenAI 兼容配置是：

```text
model    = deepseek-v4-flash
base_url = https://api.deepseek.com
```

项目的公开模板使用：

```dotenv
MINI_DEER_MODEL_PROVIDER=openai-compatible
MINI_DEER_MODEL_NAME=deepseek-v4-flash
MINI_DEER_API_KEY=
MINI_DEER_API_BASE_URL=https://api.deepseek.com
```

模型名和 Base URL 来自 [DeepSeek 官方快速开始](https://api-docs.deepseek.com/zh-cn/)。模板中的 API Key 必须保持空白；用户只在被 Git 忽略的真实 `.env` 中填写密钥。

### 核心原理

创建 `ChatOpenAI` 对象只保存模型、密钥和地址等客户端配置。真正调用 `.invoke()` 时，消息才会通过网络发送给模型服务，并可能产生费用。

单轮调用流程是：

```text
用户消息
    → invoke_once()
    → create_chat_model()
    → Settings() 读取 .env
    → ChatOpenAI.invoke()
    → DeepSeek API
    → AIMessage
    → response.text
    → 回复字符串
```

### 源码解读

#### `pyproject.toml`

项目直接使用 `BaseChatModel` 和 `AIMessage` 等 LangChain 核心类型，因此显式声明 `langchain-core` 运行依赖，而不只依赖 `langchain-openai` 间接安装它。

#### `src/mini_deer_agent/models.py`

```python
def invoke_once(message: str, model: BaseChatModel | None = None) -> str:
    """向聊天模型发送一条用户消息，并返回响应中的纯文本。"""
```

参数 `model` 使用 LangChain 的统一 `BaseChatModel` 类型。测试可以传入替身模型，真实运行时则不传，由模型工厂创建 DeepSeek 客户端。

函数先拒绝空白输入：

```python
if not message.strip():
    raise ValueError("message must not be blank")
```

这样无意义请求会在本地失败，不会访问网络或产生费用。

真正的网络边界是：

```python
response = chat_model.invoke(message)
```

LangChain 返回 `AIMessage`。它的 `content` 可能是普通字符串，也可能是文本内容块，因此使用统一的文本访问属性：

```python
return str(response.text)
```

#### `.env.example`

模板中的中文注释明确说明复制方式和密钥边界。`.env.example` 可以公开，真实 `.env` 已写入 `.gitignore`，绝对不能提交。

#### `tests/test_models.py`

测试定义带中文注释的 `FakeChatModel`。它记录收到的消息，并返回固定 `AIMessage`，因此可以验证调用流程而不访问 DeepSeek。

三个新增测试覆盖：

1. 空白消息在本地失败。
2. 原始消息正确传给模型，响应文本正确返回。
3. 未显式传模型时通过统一模型工厂创建。

配置测试还验证 `.env.example` 固定使用 DeepSeek V4 Flash 的公开参数，同时保证 API Key 为空。

### 测试驱动过程

`invoke_once` 尚未实现时，三个新增测试出现 `3 failed`。公开模板尚未切换模型时，模板测试出现 `1 failed`。完成调用函数和 DeepSeek 模板后，完整测试变为：

```text
15 passed
```

### 真实排错：密钥写错文件

第一次人工验证出现两个现象：

1. 模板测试发现 `.env.example` 中存在非空 API Key。
2. 真实调用提示缺少 `MINI_DEER_MODEL_NAME`。

只检查字段是否存在和是否非空、不输出字段内容后，确认真实 `.env` 不存在，而密钥被误填进了 `.env.example`。

修复过程是：

1. 将含真实配置的 `.env.example` 原样移动为被 Git 忽略的 `.env`。
2. 重新创建无密钥的 `.env.example`。
3. 验证 `.env` 显示为 Git ignored，公开模板显示为无密钥文件。
4. 只输出 `api_key_configured=True`，不输出密钥内容。
5. 重新运行全部测试，恢复为 `15 passed`。

这个问题说明：密钥内容即使被 `SecretStr` 隐藏，也必须先放在正确的文件中。配置模板和真实配置的文件边界是第一层安全保护。

### 运行验证

先运行全部测试：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
.\.venv\Scripts\python.exe -m pytest -q
```

预期看到：

```text
15 passed
```

然后执行真实单轮调用：

```powershell
.\.venv\Scripts\python.exe -c "from mini_deer_agent.models import invoke_once; print(invoke_once('请用一句中文介绍你自己。'))"
```

该命令会访问 DeepSeek 并产生真实用量。`deepseek-v4-flash` 当前默认启用思考模式，因此响应可能需要等待一段时间。

### 常见问题

#### 为什么使用 `openai-compatible`，而不是 `openai`？

DeepSeek 提供兼容 OpenAI Chat Completions 的协议，但使用自己的 API Key、模型名和服务地址。兼容分支会传入 DeepSeek Base URL，并且不强制启用官方 OpenAI Responses API。

#### 为什么单元测试不直接调用 DeepSeek？

网络状态、账号余额、模型权限和服务限速都会让测试结果不稳定。单元测试只验证本地调用逻辑，真实连通性由用户单独验证。

#### `.env.example` 为什么不能填写真实密钥？

它是用于提交和共享的公开模板。真实密钥只能写入 `.env`；如果密钥曾经进入 Git 历史或远程仓库，应立即在服务平台撤销并重新生成。

### 本课小结

完成本课后，已经掌握：

- 使用模型工厂集中创建 LangChain 聊天模型。
- 区分构造模型对象与发送真实请求。
- 通过 OpenAI 兼容接口调用 DeepSeek-V4-Flash。
- 使用 `BaseChatModel` 和 `AIMessage.text` 保持统一接口。
- 使用替身模型测试调用流程而不访问网络。
- 识别并修复 `.env.example` 与 `.env` 的密钥边界错误。
- 为新增代码同步编写解释职责和原因的中文注释。

下一课将使用 LangGraph 建立最小 Agent 状态图，让模型调用进入可扩展的图执行流程。

---

# 第 4 课：LangGraph 状态图

## 功能点 4.1：最小状态图骨架

### 本次目标

使用固定回复节点建立第一张 LangGraph 状态图，走通 `START → respond → END`。本功能点只学习状态、节点、边和编译，不访问 DeepSeek。

### 核心原理

LangGraph 节点共享一份状态。每个节点读取当前状态并返回自己负责的部分更新，LangGraph 根据状态字段的 reducer 合并更新，再沿着边进入下一个节点。

最小执行流程是：

```text
输入状态
    → START
    → respond_node 读取状态
    → 节点返回部分状态更新
    → reducer 合并消息
    → END
    → 输出最终状态
```

本地 DeerFlow 已经使用更高层的 `create_agent()`、模型工厂、工具和 middleware 组合完整 Agent。本课先直接使用 `StateGraph`，看清这些高层封装依赖的底层机制。

### 源码解读

#### `pyproject.toml`

项目新增 `langgraph>=1.2.9,<1.3` 运行依赖，当前虚拟环境安装的是 LangGraph 1.2.11。

#### `src/mini_deer_agent/agent.py`

模块导入：

```python
from langgraph.graph import END, START, MessagesState, StateGraph
```

- `MessagesState` 定义共享消息状态及消息合并规则。
- `StateGraph` 是图结构构建器。
- `START` 和 `END` 是虚拟起点与终点。

`MessagesState` 可以概念性理解为一个包含 `messages` 字段的 `TypedDict`，该字段使用 `add_messages` reducer。节点返回新消息后，reducer 会把它追加到已有消息列表，而不是覆盖输入消息。

节点函数是：

```python
def respond_node(state: MessagesState) -> dict[str, list[AIMessage]]:
    last_message_text = str(state["messages"][-1].text)
    return {
        "messages": [AIMessage(content=f"LangGraph 已收到：{last_message_text}")]
    }
```

节点可以读取完整状态，但只返回自己负责的状态变化。这里不能手动返回“旧消息 + 新消息”，否则 reducer 再合并时可能重复添加旧消息。

构图函数先创建 builder 并注册节点：

```python
builder = StateGraph(MessagesState)
builder.add_node("respond", respond_node)
```

然后用有向边声明唯一执行顺序：

```python
builder.add_edge(START, "respond")
builder.add_edge("respond", END)
```

最后调用：

```python
return builder.compile()
```

`StateGraph` 只描述结构，不能直接执行。`compile()` 检查图结构并生成 `CompiledStateGraph`；编译后的对象才支持 `.invoke()`、`.stream()` 和异步接口。

#### `tests/test_agent.py`

节点级测试直接调用 `respond_node`，验证它只返回一条新的 `AIMessage`，不依赖 LangGraph 执行器。

完整图测试调用 `graph.invoke()`，验证最终状态同时包含：

```text
HumanMessage("请测试最小状态图。")
AIMessage("LangGraph 已收到：请测试最小状态图。")
```

这证明节点被执行、输入消息被保留、新消息被 reducer 追加，并且执行路径最终到达 `END`。

### 测试驱动过程

测试最初因为 `mini_deer_agent.agent` 不存在而在导入阶段失败。添加 LangGraph 依赖和最小图后，图专项测试为 `2 passed`，完整测试为 `17 passed`。

编译后的图导出为以下结构：

```text
__start__ → respond → __end__
```

### 运行验证

运行图专项测试：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
.\.venv\Scripts\python.exe -m pytest tests\test_agent.py -q
```

预期看到：

```text
2 passed
```

再直接调用图：

```powershell
.\.venv\Scripts\python.exe -c "from langchain_core.messages import HumanMessage; from mini_deer_agent.agent import build_agent_graph; result=build_agent_graph().invoke({'messages':[HumanMessage(content='你好，状态图！')]}); print([(type(message).__name__, str(message.text)) for message in result['messages']])"
```

预期输出包含一条 `HumanMessage` 和一条追加的 `AIMessage`。

### 常见问题

#### 节点为什么不返回完整状态？

节点只负责描述自己的更新。LangGraph 使用 reducer 把更新合并回共享状态，节点不需要复制其他字段或已有消息。

#### `StateGraph` 和 `CompiledStateGraph` 有什么区别？

`StateGraph` 用于声明结构；`CompiledStateGraph` 是检查并编译后生成的可执行对象。只有后者可以调用 `.invoke()`。

#### 为什么固定回复，不直接调用 DeepSeek？

确定性节点可以独立验证图结构和消息合并。如果一开始同时加入网络模型，失败时难以判断问题来自图、配置、网络还是模型服务。

### 功能点 4.1 小结

完成这一功能点后，已经掌握：

- LangGraph 状态、节点和边的基本职责。
- `MessagesState` 如何通过 reducer 合并消息。
- 节点为什么只返回部分状态更新。
- `START`、`END` 如何声明执行路径。
- `compile()` 如何把结构构建器变成可执行图。
- 如何分别测试单个节点和完整状态图。

下一个功能点将把 `BaseChatModel` 注入节点，用 DeepSeek 替换固定回复。

## 功能点 4.2：向状态图注入聊天模型

### 本次目标

把功能点 4.1 的固定回复节点替换为真正的模型节点，使图沿着 `START → model → END` 调用 DeepSeek。同时让节点依赖 `BaseChatModel` 抽象，单元测试可以注入假模型并保持完全离线。

最终执行流程变为：

```text
HumanMessage
    → START
    → model_node 读取完整消息历史
    → BaseChatModel.invoke(messages)
    → 返回 AIMessage 部分更新
    → MessagesState reducer 追加回复
    → END
```

### 为什么需要依赖注入

如果模型节点内部直接创建 DeepSeek 客户端，节点逻辑就会同时负责配置读取、客户端构造和模型调用。这样不仅职责混在一起，单元测试也必须访问真实网络。

本项目改为让节点接收 `BaseChatModel`：

```python
def model_node(
    state: MessagesState,
    model: BaseChatModel,
) -> dict[str, list[BaseMessage]]:
```

`BaseChatModel` 是 LangChain 聊天模型的统一抽象。真实运行可以传入 `ChatOpenAI`，测试可以传入 `FakeMessagesListChatModel`，节点本身不需要知道具体提供方。

### 源码解读

#### `src/mini_deer_agent/agent.py`

模型节点调用：

```python
response = model.invoke(state["messages"])
return {"messages": [response]}
```

这里向模型传入完整消息对象列表，而不是最后一条消息的纯文本，原因是：

- `HumanMessage`、`AIMessage` 等对象保存了消息角色。
- 完整列表保存了消息顺序和多轮对话上下文。
- 将来加入系统提示词和工具消息时，不需要改变节点调用形式。

模型返回的 `response` 本身就是一条消息。节点仍然只返回本次新增的消息，`MessagesState` 的 reducer 负责把它追加到原历史中。

构图函数允许显式注入模型：

```python
def build_agent_graph(model: BaseChatModel | None = None) -> CompiledStateGraph:
    chat_model = model if model is not None else create_chat_model()
```

它有两种使用方式：

```python
build_agent_graph(fake_model)  # 单元测试：使用调用方传入的假模型
build_agent_graph()            # 正常运行：由模型工厂创建 DeepSeek 客户端
```

节点注册使用：

```python
builder.add_node("model", partial(model_node, model=chat_model))
```

原始 `model_node` 需要 `state` 和 `model` 两个参数。`partial()` 预先固定 `model`，得到的可调用对象只等待 LangGraph 在执行时传入 `state`。它可以概念性理解为：

```python
def injected_model_node(state):
    return model_node(state, model=chat_model)
```

图的边也同步更新为：

```python
builder.add_edge(START, "model")
builder.add_edge("model", END)
```

编译后的最终结构是：

```text
__start__ → model → __end__
```

#### `src/mini_deer_agent/models.py`

`agent.py` 不重复编写模型参数，而是继续调用上一课的模型工厂：

```python
from mini_deer_agent.models import create_chat_model
```

因此职责边界保持为：

```text
Settings               读取和校验配置
create_chat_model()     构造 BaseChatModel
model_node()            使用模型处理消息状态
build_agent_graph()     把模型节点装入执行图
```

### 与 DeerFlow 源码的对应关系

本地 DeerFlow 的模型工厂同样返回 `BaseChatModel`：

```python
def create_chat_model(...) -> BaseChatModel:
```

DeerFlow 在构建主 Agent 时把工厂返回的模型传给高层 `create_agent()`：

```python
return create_agent(
    model=create_chat_model(...),
    ...
)
```

Mini Deer 与 DeerFlow 的共同核心是：

```text
配置 → 模型工厂 → BaseChatModel → 注入 Agent/Graph
```

区别在于 DeerFlow 的 `create_agent()` 隐藏了模型节点、工具节点和循环图等底层结构；Mini Deer 直接使用 `StateGraph`，因此可以清楚看到模型怎样读取状态、生成消息并更新状态。

### 离线测试

`tests/test_agent.py` 使用 LangChain 提供的 `FakeMessagesListChatModel`：

```python
model = FakeMessagesListChatModel(
    responses=[AIMessage(content="这是测试模型生成的回复。")]
)
```

假模型直接返回预设消息，不读取 API Key、不访问网络，也不消耗模型额度。

两个测试分别验证：

1. `model_node` 返回注入模型生成的单条消息更新。
2. 编译图保留输入 `HumanMessage`，并追加假模型生成的 `AIMessage`。

测试驱动过程首先因 `model_node` 尚不存在而在导入阶段失败；实现模型节点与注入接口后，图专项测试为 `2 passed`，完整项目测试为 `17 passed`。

### DeepSeek 真实验证

真实调用命令是：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
.\.venv\Scripts\python.exe -c "from langchain_core.messages import HumanMessage; from mini_deer_agent.agent import build_agent_graph; result = build_agent_graph().invoke({'messages': [HumanMessage(content='请用一句中文说明什么是 LangGraph。')]}); print(result['messages'][-1].text)"
```

不传模型参数时，`build_agent_graph()` 会通过 `.env` 创建 DeepSeek-V4-Flash 客户端。用户已经实际运行该命令并确认调用成功，证明以下完整链路可以工作：

```text
.env 配置
    → create_chat_model()
    → DeepSeek-V4-Flash
    → model_node
    → MessagesState
    → 最终 AIMessage
```

### 常见问题

#### 为什么传完整 `messages`，而不是 `messages[-1].text`？

纯文本会丢失角色和历史上下文。聊天模型接口本来就接收消息序列，保留消息对象可以自然支持系统消息、多轮对话和后续工具消息。

#### 为什么模型在构图时注入，而不是每次执行节点时重新创建？

构图时创建一次模型对象，可以复用客户端配置和连接资源。节点执行只负责调用，避免每次经过节点都重新读取配置和构造客户端。

#### `partial()` 是否调用了模型？

没有。`partial()` 只生成一个已经固定部分参数的新可调用对象；真正执行到 `model` 节点时，才会调用 `model.invoke()` 并访问 DeepSeek。

#### 为什么真实调用不放进 pytest？

真实 API 受到网络、余额、限速和服务状态影响，也会产生费用。pytest 验证确定性的本地逻辑，真实连通性由独立命令验证，两种测试解决不同问题。

### 本课小结

完成第 4 课后，已经掌握：

- 使用 `MessagesState` 保存和合并消息历史。
- 使用节点和有向边声明最小 LangGraph 执行路径。
- 通过 `compile()` 得到可执行状态图。
- 让模型节点接收 `BaseChatModel`，而不依赖具体模型提供方。
- 使用 `partial()` 把模型依赖注入 LangGraph 节点。
- 使用假模型完成稳定、离线、无费用的图测试。
- 通过真实 DeepSeek 调用验证配置、模型工厂和状态图的完整链路。
- 理解 Mini Deer 的显式 `StateGraph` 与 DeerFlow 高层 `create_agent()` 的对应关系。

下一课将在这张线性模型图上加入第一个工具，并通过条件边形成“模型决定是否调用工具”的 Agent 循环。

---

# 第 5 课：工具调用与条件循环

## 功能点 5.1：真实天气工具契约

### 本次目标

使用 `@tool` 把一个 Python 函数转换成模型可见工具。工具内部实时访问 Open-Meteo：先用城市名查询经纬度，再用经纬度查询当前天气。

本功能点只完成工具契约和真实工具实现，尚未把工具绑定给 DeepSeek，也尚未加入 `ToolNode`。

### 当前调用流程

直接执行：

```python
get_weather.invoke({"city": "北京"})
```

完整链路是：

```text
导入 tools.py
    → @tool 把函数包装成 StructuredTool
    → invoke() 根据 Schema 校验 city
    → get_weather() 清理输入
    → 创建带超时的 HTTP 客户端
    → 地理编码 API 把城市名转换成经纬度
    → 天气 API 根据经纬度查询当前天气
    → WMO 天气代码转换为中文
    → 格式化天气、数据时间、时区和来源
    → 关闭 HTTP 客户端
    → 返回工具结果字符串
```

### 工具契约

#### `src/mini_deer_agent/tools.py`

工具入口是：

```python
@tool
def get_weather(city: Annotated[str, "要查询的城市名称"]) -> str:
    """查询城市当前天气，实时请求 Open-Meteo 数据。"""
```

模块导入时，装饰器可以概念性理解为：

```python
get_weather = tool(get_weather)
```

所以导入后的 `get_weather` 是 `StructuredTool`，主要包含：

- `name`：默认来自函数名，这里是 `get_weather`。
- `description`：来自函数文档字符串，帮助模型判断何时使用。
- `args_schema`：由类型标注生成的 JSON Schema。
- `invoke()`：统一的工具调用入口。

`Annotated[str, "要查询的城市名称"]` 同时声明参数类型和模型可见说明，最终 Schema 的核心结构为：

```json
{
  "type": "object",
  "properties": {
    "city": {
      "type": "string",
      "description": "要查询的城市名称"
    }
  },
  "required": ["city"]
}
```

模型将来看到的是工具名、说明和参数 Schema，而不是 Python 函数源码。因此清晰的命名、类型标注和文档字符串会直接影响模型能否正确选择工具和生成参数。

### 工具入口的职责

`get_weather()` 首先处理业务输入边界：

```python
normalized_city = city.strip()
if not normalized_city:
    raise ValueError("city 不能为空")
```

Schema 可以验证 `city` 是否存在及是否为字符串，但空白字符串在类型上仍然合法，所以函数内部还需要语义校验。

然后使用上下文管理器调用实际业务流程：

```python
with _create_http_client() as client:
    return _fetch_current_weather(normalized_city, client)
```

无论查询成功还是发生异常，退出 `with` 时都会关闭客户端和网络连接资源。

### HTTP 客户端与运行依赖

项目在 `pyproject.toml` 中显式声明：

```toml
"httpx>=0.28,<1.0"
```

源码直接导入 `httpx`，所以即使它已经被其他库间接安装，也必须把它列为本项目的直接运行依赖。

客户端工厂是：

```python
def _create_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "mini-deer-agent/0.1"},
    )
```

- 有限超时防止外部服务异常时让 Agent 永久卡在工具节点。
- 自动跟随 HTTP 重定向。
- `User-Agent` 标明请求来自 Mini Deer Agent。
- 独立工厂允许测试替换客户端而不修改业务代码。

### 统一 HTTP 响应处理

两个 API 请求都经过：

```python
def _request_json(client, url, params):
    response = client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("天气服务返回了无效的 JSON 结构")
    return payload
```

它统一负责：

1. 发送带查询参数的 GET 请求。
2. 使用 `raise_for_status()` 拒绝 4xx 和 5xx 响应。
3. 解析 JSON。
4. 确认顶层数据是业务代码期望的对象结构。

### 第一次请求：城市地理编码

工具首先访问：

```text
https://geocoding-api.open-meteo.com/v1/search
```

请求参数为：

```python
{
    "name": city,
    "count": 1,
    "language": "zh",
    "format": "json",
}
```

响应提供城市名称、国家、纬度、经度和时区。公开接口支持中文地点搜索，本项目不需要额外配置天气 API Key：[Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api)。

如果 `results` 缺失、类型错误或为空，工具会抛出：

```text
未找到城市：输入城市
```

如果存在城市结果但缺少有效经纬度，则说明外部响应结构异常，工具会抛出 `RuntimeError`。

### 第二次请求：当前天气

取得经纬度后访问：

```text
https://api.open-meteo.com/v1/forecast
```

请求的当前天气字段是：

```text
temperature_2m         地面以上 2 米温度
apparent_temperature   体感温度
weather_code           WMO 天气代码
wind_speed_10m         地面以上 10 米风速
```

同时传入 `timezone=auto`，让服务按照地点返回当地数据时间。Open-Meteo 文档说明这些 current 字段来自当前时刻的天气模型数据：[Open-Meteo Weather API](https://open-meteo.com/en/docs)。

代码检查 `current` 是否存在，并确认时间、温度、体感温度、天气码和风速全部返回。缺少字段时会给出明确错误，而不是在格式化阶段产生含义不清楚的 `KeyError`。

### WMO 天气代码转换

API 使用数字描述天气状况，`_weather_code_to_text()` 将常用代码转换为中文：

```text
0          晴
1          晴间多云
2          多云
3          阴
45、48     雾
61、63、65 雨
71、73、75 降雪
80、81、82 阵雨
95、96、99 雷暴
```

工具应该尽量返回模型和用户都容易理解的信息，而不是把不必要的代码解释工作交给模型。

### 最终结果

工具结果包含地点、国家、天气状况、温度、体感温度、风速、数据时间、时区和来源，例如：

```text
北京（中国）当前天气：晴；温度 31.1°C，体感 36.9°C，
10 米风速 2.3 km/h；数据时间 2026-08-24T15:45
（Asia/Shanghai）；来源 Open-Meteo。
```

具体数值会随调用时间变化。这是通过真实 API 获取的当前天气模型数据，不应描述为气象站实时观测值。

### 测试策略

#### `tests/test_tools.py`

测试使用 `httpx.MockTransport` 接住生产代码发出的 HTTP 请求：

```python
transport = httpx.MockTransport(handle_request)
monkeypatch.setattr(
    "mini_deer_agent.tools._create_http_client",
    lambda: httpx.Client(transport=transport),
)
```

生产代码仍然真实执行 `client.get()`、状态码检查、JSON 解析和业务处理，只是请求不会离开本机，而是由测试返回预设 API 响应。

测试验证：

1. 工具名称、说明和 `city` 参数 Schema。
2. 请求顺序确实是“地理编码 → 当前天气”。
3. 城市名、经纬度和时区参数正确传递。
4. WMO 天气代码和单位正确格式化。
5. 未知城市与空白城市得到明确错误。

测试驱动过程中，新测试首先因缺少 `_create_http_client` 和真实请求流程而失败；实现后工具专项测试为 `4 passed`，完整项目测试为 `21 passed`。

真实 Open-Meteo 连通性也已独立验证成功，证明工具并非只对模拟响应有效。

### 与完整 Agent 循环的关系

当前已完成：

```text
Python 调用方 → get_weather.invoke() → Open-Meteo → 天气字符串
```

后续完整 Agent 循环将是：

```text
用户问题
    → DeepSeek 返回 AIMessage.tool_calls
    → tools_condition 路由到 ToolNode
    → ToolNode 调用 get_weather.invoke()
    → ToolMessage 携带天气结果和 tool_call_id
    → 再次调用 DeepSeek 组织最终回答
    → 没有新的 tool_calls 时进入 END
```

第一次模型调用负责决定工具名和参数；第二次模型调用负责读取工具结果并回答用户。工具不会调用 DeepSeek，DeepSeek 也不会亲自发送天气 HTTP 请求，两者通过工具调用消息协议协作。

### 与 DeerFlow 源码的对应关系

DeerFlow 的工具同样使用 `@tool` 声明。工具内部可以调用外部 API、查询数据库、读写文件或执行本地业务逻辑；`@tool` 只负责提供统一的模型可见契约。

当前需要掌握的职责分工是：

```text
@tool       让模型认识工具
工具函数    真正完成外部动作
ToolNode    按照模型请求执行工具
ToolMessage 把执行结果交回模型
```

本功能点已经完成前两层。下一个功能点将使用 `bind_tools()` 把 `get_weather` 的名称、说明和参数 Schema 交给 DeepSeek，并观察模型生成的结构化 `tool_calls`，暂不执行工具。

## 功能点 5.2：模型绑定工具并生成调用请求

### 本次目标

把功能点 5.1 的 `get_weather` 工具绑定给聊天模型，让 DeepSeek 能根据用户问题选择工具并返回结构化 `AIMessage.tool_calls`。

本功能点刻意不执行天气工具。图仍然沿 `START → model → END` 运行，用于单独观察“模型决定调用什么工具、生成什么参数”的阶段。

### 当前执行流程

```text
HumanMessage("请查询北京当前天气")
    → START
    → 绑定了 get_weather 的模型节点
    → DeepSeek 阅读消息和工具 Schema
    → AIMessage.tool_calls
    → MessagesState 追加 AIMessage
    → END
```

最终状态只有：

```text
HumanMessage
AIMessage(tool_calls=[...])
```

当前不会产生 `ToolMessage`，也不会访问 Open-Meteo。

### 集中维护工具集合

#### `src/mini_deer_agent/agent.py`

Agent 可用工具集中定义为：

```python
AGENT_TOOLS: tuple[BaseTool, ...] = (get_weather,)
```

集中注册的原因是，后续模型绑定与 `ToolNode` 必须使用同一组工具：

```text
模型看到的工具集合 == ToolNode 能执行的工具集合
```

如果两侧分别维护，模型可能请求一个没有注册到工具节点的工具，执行阶段就无法按名称找到它。

这里使用元组表示构图期间的注册集合保持稳定，防止后续代码意外增删工具。

### `bind_tools()` 的作用

构图函数新增：

```python
chat_model = model if model is not None else create_chat_model()
tool_model = chat_model.bind_tools(AGENT_TOOLS)
```

`bind_tools()` 读取工具对象的：

- `name`
- `description`
- `args_schema`

然后把它转换成模型提供方使用的函数调用定义。`get_weather` 对应的核心结构可以理解为：

```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "查询城市当前天气，实时请求 Open-Meteo 数据。",
    "parameters": {
      "type": "object",
      "properties": {
        "city": {
          "type": "string",
          "description": "要查询的城市名称"
        }
      },
      "required": ["city"]
    }
  }
}
```

工具 Schema 会随消息一起发送给 DeepSeek。模型根据用户问题、工具名称、用途说明和参数结构，决定是直接回答还是生成工具请求。

`bind_tools()` 只绑定契约，不会：

- 调用 DeepSeek。
- 执行 `get_weather`。
- 访问 Open-Meteo。
- 生成 `ToolMessage`。

真正执行 `tool_model.invoke(messages)` 时才访问 DeepSeek；真正经过未来的 `ToolNode` 时才执行天气工具。

### 为什么必须使用绑定后的返回值

代码保存：

```python
tool_model = chat_model.bind_tools(AGENT_TOOLS)
```

而不是调用后继续使用原来的 `chat_model`，因为 LangChain 的绑定方法返回一个新的 `Runnable`，不保证原地修改模型对象。

因此节点注册改为：

```python
builder.add_node("model", partial(model_node, model=tool_model))
```

如果仍把原始 `chat_model` 注入节点，模型请求中不会携带工具 Schema，也就不知道 `get_weather` 存在。

### `model_node` 为什么改用 `Runnable`

绑定工具前，节点参数类型是具体的模型抽象：

```python
BaseChatModel
```

绑定后，`bind_tools()` 返回的是可执行包装对象，所以节点现在依赖：

```python
Runnable[LanguageModelInput, BaseMessage]
```

含义是：节点只要求这个依赖能够：

1. 接收 LangChain 模型输入。
2. 通过 `.invoke()` 返回一条消息。

节点不需要知道传入对象究竟是原始模型、绑定工具后的模型、测试假模型还是其他 Runnable 包装器。这是面向行为而不是面向具体实现的依赖方式。

模型节点本身仍然保持简单：

```python
response = model.invoke(state["messages"])
return {"messages": [response]}
```

### `AIMessage.tool_calls`

当 DeepSeek 判断需要查询天气时，可以返回类似：

```python
AIMessage(
    content="",
    tool_calls=[
        {
            "name": "get_weather",
            "args": {"city": "北京"},
            "id": "call-weather-1",
            "type": "tool_call",
        }
    ],
)
```

各字段含义是：

- `name`：请求执行的工具名。
- `args`：模型根据 Schema 生成的结构化参数。
- `id`：本次调用的唯一标识，后续 `ToolMessage.tool_call_id` 必须与它对应。
- `type`：LangChain 标准化后的工具调用类型。

`content` 为空是正常情况。模型此时没有最终天气数据，它表达的是“需要先调用这个工具”，而不是直接回答用户。

DeepSeek 官方工具调用流程同样分为“模型生成工具请求 → 应用执行函数 → 把结果交回模型 → 模型最终回答”，并明确说明模型本身不会执行函数：[DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls)。

### 为什么当前图直接进入 `END`

图仍然使用：

```python
builder.add_edge(START, "model")
builder.add_edge("model", END)
```

因此工具调用请求只会作为一条 `AIMessage` 保存到状态，然后结束执行。

这样可以独立确认：

- 工具是否成功绑定。
- 模型是否选择正确工具。
- 模型是否生成正确参数。
- LangChain 是否把提供方响应标准化为 `tool_calls`。

如果本阶段同时加入工具执行和第二次模型调用，失败时就难以判断问题来自 Schema、模型选择、路由、天气 API 还是结果回传。

### 离线测试

#### `tests/test_agent.py`

LangChain 的 `FakeMessagesListChatModel` 不实现真实 `bind_tools()`，所以测试定义：

```python
class ToolAwareFakeModel(FakeMessagesListChatModel):
```

它重写绑定方法并记录收到的工具名：

```python
def bind_tools(self, tools, ...):
    self.bound_tool_names = [tool.name for tool in tools]
    return self
```

测试假模型预设返回一条带 `tool_calls` 的 `AIMessage`，因此不访问 DeepSeek，也不产生模型费用。

测试还把天气客户端工厂替换成必定失败的函数：

```python
def fail_if_weather_tool_runs() -> None:
    raise AssertionError("不应执行天气工具")
```

完整测试能够通过，证明当前图：

1. 确实把 `get_weather` 绑定给了模型。
2. 能把结构化工具请求追加到 `MessagesState`。
3. 没有执行天气工具。
4. 没有访问 Open-Meteo。
5. 没有产生 `ToolMessage`。

测试驱动过程中，新测试首先因 `bound_tool_names` 为空而失败；加入 `chat_model.bind_tools(AGENT_TOOLS)` 后，图专项测试为 `2 passed`，完整项目测试为 `21 passed`。

### DeepSeek 真实验证

真实验证命令为：

```powershell
Set-Location D:\project\agentstudy\mini-deer-agent
.\.venv\Scripts\python.exe -c "from langchain_core.messages import HumanMessage; from mini_deer_agent.agent import build_agent_graph; result=build_agent_graph().invoke({'messages':[HumanMessage(content='请调用 get_weather 工具查询北京当前天气。')]}); last=result['messages'][-1]; print('消息类型:', [type(message).__name__ for message in result['messages']]); print('文本:', last.text); print('工具请求:', last.tool_calls)"
```

用户已经完成真实验证，DeepSeek 能返回 `get_weather` 及 `city` 参数的结构化工具请求。此时没有天气结果是符合设计的，因为图还没有工具节点。

### 与 DeerFlow 源码的对应关系

DeerFlow 先收集 `effective_tools`，再把模型和工具列表一同传给高层 `create_agent()`：

```python
return create_agent(
    model=model,
    tools=effective_tools or None,
    ...
)
```

`create_agent()` 内部封装了模型工具绑定、工具执行和循环路由。Mini Deer 当前显式实现的是其中的模型绑定阶段：

```text
DeerFlow: create_agent(model, tools)
                       ↓ 内部封装
Mini Deer: model.bind_tools(AGENT_TOOLS)
```

### 功能点 5.2 小结

完成这一功能点后，已经掌握：

- 模型看到的是工具契约，而不是工具源码。
- `bind_tools()` 只绑定工具 Schema，不执行工具。
- 为什么必须保存并使用绑定后的 Runnable。
- `AIMessage.tool_calls` 如何表达工具名、参数和调用 ID。
- 为什么生成工具请求与执行工具要分成两个阶段。
- 如何用脚本化假模型验证工具绑定且不产生网络访问。
- Mini Deer 显式绑定与 DeerFlow `create_agent()` 高层封装的对应关系。

下一个功能点将加入 `ToolNode` 和 `tools_condition`，执行 `get_weather`、生成与调用 ID 对应的 `ToolMessage`，再回到模型节点生成最终回答。

## 功能点 5.3：完整工具执行循环

### 本次目标

在已经能生成 `tool_calls` 的模型图中加入工具执行节点和条件路由，完成以下闭环：

```text
模型请求工具
    → 应用执行工具
    → 工具结果交回模型
    → 模型生成最终回答
```

这是 Mini Deer Agent 第一张真正具备“观察问题、选择动作、获得结果、继续回答”能力的 Agent 图。

### 最终图结构

编译后的拓扑是：

```text
START
  ↓
model
  ├─ 没有 tool_calls → END
  └─ 存在 tool_calls → tools
                         ↓
                       model
```

对应源码为：

```python
builder.add_node("model", partial(model_node, model=tool_model))
builder.add_node("tools", ToolNode(AGENT_TOOLS))

builder.add_edge(START, "model")
builder.add_conditional_edges("model", tools_condition)
builder.add_edge("tools", "model")
```

这里不再使用固定的 `model → END` 边，因为模型节点之后的目标取决于最后一条 `AIMessage` 是否包含工具请求。

### `ToolNode` 如何执行工具

工具节点创建为：

```python
builder.add_node("tools", ToolNode(AGENT_TOOLS))
```

当状态最后一条消息包含：

```python
AIMessage(
    tool_calls=[
        {
            "name": "get_weather",
            "args": {"city": "北京"},
            "id": "call-weather-1",
            "type": "tool_call",
        }
    ]
)
```

`ToolNode` 会自动：

1. 读取 `AIMessage.tool_calls`。
2. 根据 `name` 在 `AGENT_TOOLS` 中找到 `get_weather`。
3. 调用 `get_weather.invoke({"city": "北京"})`。
4. 获得 Open-Meteo 查询结果。
5. 创建 `ToolMessage` 并追加到 `MessagesState`。

生成的消息可以概念性理解为：

```python
ToolMessage(
    content="北京（中国）当前天气：……",
    name="get_weather",
    tool_call_id="call-weather-1",
)
```

### 工具调用 ID 为什么重要

模型请求中的：

```python
"id": "call-weather-1"
```

必须与工具结果中的：

```python
tool_call_id="call-weather-1"
```

对应。一次模型响应可能请求多个工具，调用 ID 让模型能够确定每条 `ToolMessage` 对应哪个请求。

`ToolNode` 自动维护这种对应关系，避免应用手工创建错误的工具结果消息。

### `tools_condition` 如何路由

模型节点使用条件边：

```python
builder.add_conditional_edges("model", tools_condition)
```

`tools_condition` 检查状态中的最后一条消息：

```text
最后一条 AIMessage 包含 tool_calls
    → 返回 tools
    → 进入 ToolNode

最后一条 AIMessage 不包含 tool_calls
    → 返回 __end__
    → 图结束
```

因此模型可以根据问题动态决定是否使用工具，而不是每次调用都强制查询天气。

### 为什么需要 `tools → model` 回边

工具只返回事实数据，不负责组织最终对话回答。例如：

```text
北京（中国）当前天气：雷暴；温度 24.2°C……
```

所以工具执行后必须回到模型：

```python
builder.add_edge("tools", "model")
```

第二次模型调用读取完整消息历史，包括用户问题、工具请求和工具结果，再生成自然语言回答。

如果缺少这条回边，用户只能得到原始工具字符串，模型没有机会解释天气、调整表达或给出适当提示。

### 四条消息如何形成

一次典型天气查询最终包含四条消息。

第一条是用户问题：

```python
HumanMessage(content="北京现在天气怎么样？")
```

第二条是模型第一次响应：

```python
AIMessage(tool_calls=[get_weather 请求])
```

第三条是工具执行结果：

```python
ToolMessage(
    content="北京当前天气……",
    tool_call_id="与模型请求 ID 相同",
)
```

第四条是模型最终回答：

```python
AIMessage(content="北京当前有雷暴，温度……")
```

状态变化为：

```text
[HumanMessage]
    → [HumanMessage, AIMessage(tool_calls)]
    → [HumanMessage, AIMessage(tool_calls), ToolMessage]
    → [HumanMessage, AIMessage(tool_calls), ToolMessage, AIMessage(final)]
```

最后一条 `AIMessage` 没有新的工具请求，`tools_condition` 因此路由到 `END`。

### 为什么这是循环而不是固定四步

如果模型读取第一个工具结果后仍需要另一个工具，它可以再次返回 `tool_calls`：

```text
model → tools → model → tools → model → END
```

所以停止条件不是“已经执行过一次工具”，而是：

```text
最后一条 AIMessage 不再包含 tool_calls
```

当前天气问题通常只执行一次工具，因此最常见结果是四条消息。

### 离线图测试

#### 工具循环路径

`tests/test_agent.py` 使用脚本化假模型依次返回：

```python
responses=[
    AIMessage(tool_calls=[get_weather 请求]),
    AIMessage(content="北京当前晴，温度 26°C。"),
]
```

第一次响应让条件边进入工具节点，第二次响应模拟模型读取工具结果后的最终回答。

图测试把 `StructuredTool.func` 临时替换为：

```python
def fake_weather(city: str) -> str:
    called_cities.append(city)
    return "北京当前天气：晴，温度 26°C。"
```

这样只测试 LangGraph 循环，不重复访问 DeepSeek 或 Open-Meteo。真实天气 HTTP 流程已经由 `tests/test_tools.py` 单独覆盖。

测试验证：

- `get_weather` 收到的参数确实是 `北京`。
- 最终状态包含四条消息。
- 工具请求名称和参数正确。
- `ToolMessage.tool_call_id` 与模型请求 ID 一致。
- 第二次模型响应出现在最终状态末尾。

#### 直接结束路径

另一测试让假模型直接返回普通回答，不包含 `tool_calls`，并把天气函数替换为一个只要执行就报错的函数。

测试通过证明：

```text
普通问题 → model → END
```

条件边不会在没有工具请求时误执行天气工具。

测试驱动过程中，完整循环测试首先因 `called_cities` 为空而失败，说明旧图确实停在模型节点。加入 `ToolNode`、条件边和回边后，图专项测试为 `3 passed`，完整项目测试为 `22 passed`。

### DeepSeek 与 Open-Meteo 端到端验证

用户使用真实 DeepSeek-V4-Flash 和 Open-Meteo 完成验证，消息顺序为：

```text
['HumanMessage', 'AIMessage', 'ToolMessage', 'AIMessage']
```

DeepSeek 第一次响应生成：

```python
{
    "name": "get_weather",
    "args": {"city": "北京"},
    "id": "call_00_...",
    "type": "tool_call",
}
```

本次验证的 Open-Meteo 示例结果为：

```text
北京（中国）当前天气：雷暴；温度 24.2°C，体感 29.5°C，
10 米风速 3.1 km/h；数据时间 2026-08-25T16:30
（Asia/Shanghai）；来源 Open-Meteo。
```

天气数值只记录本次调用结果，会随时间变化，不能作为测试固定值。

DeepSeek 第二次调用成功读取工具结果，并生成包含天气情况、温度、风速和雷暴提示的最终自然语言回答。这证明以下链路全部可用：

```text
用户问题
    → DeepSeek 选择 get_weather
    → tools_condition 路由
    → ToolNode 执行真实天气工具
    → Open-Meteo 返回当前数据
    → ToolMessage 关联调用 ID
    → DeepSeek 读取工具结果
    → 最终回答
    → END
```

### 与 DeerFlow 源码的对应关系

DeerFlow 使用高层 `create_agent(model, tools)` 封装工具 Agent。其内部核心仍然是：

```text
模型节点
    → 检查工具请求
    → 工具节点执行
    → 工具结果回到模型
    → 没有工具请求时结束
```

Mini Deer 直接写出的对应关系是：

```python
ToolNode(AGENT_TOOLS)                  # 工具执行节点
tools_condition                       # 是否调用工具的路由
builder.add_edge("tools", "model")    # 工具结果回传模型
```

理解这三行之后，再阅读 DeerFlow 的工具、中间件和 `create_agent()` 时，就能知道高层封装解决了哪些底层工作。

### 第 5 课小结

完成第 5 课后，已经掌握：

- 使用 `@tool` 定义包含名称、说明和参数 Schema 的工具契约。
- 在工具内部通过真实 HTTP API 完成外部动作。
- 使用 `bind_tools()` 让 DeepSeek 生成结构化工具请求。
- 理解模型生成工具请求不等于模型执行工具。
- 使用 `ToolNode` 根据工具名和参数执行已注册工具。
- 使用 `ToolMessage.tool_call_id` 关联工具请求和结果。
- 使用 `tools_condition` 在工具节点与 `END` 之间动态路由。
- 使用 `tools → model` 回边把工具结果交给模型形成最终回答。
- 分层测试工具 HTTP、模型绑定、工具循环和真实端到端链路。
- 理解 Mini Deer 显式状态图与 DeerFlow `create_agent()` 工具循环的对应关系。

下一课将为状态图加入 Checkpointer 和线程 ID，让同一个 Agent 线程能够保存消息并进行连续多轮对话。

---

# 第 6 课：Checkpointer 与线程记忆

## 功能点 6.1：内存线程状态

### 本次目标

给现有工具 Agent 注入 `InMemorySaver`，使用 `thread_id` 保存和恢复 `MessagesState`，验证：

1. 相同线程的下一次调用自动续接历史。
2. 不同线程的消息状态互相隔离。
3. `graph.get_state()` 可以读取线程最新状态。
4. 启用 Checkpointer 后必须提供 `thread_id`。

本功能点只使用当前进程内存；关闭 Python 后状态会消失，尚未实现跨进程持久化。

### 构图函数的存储边界

#### `src/mini_deer_agent/agent.py`

构图函数新增可选参数：

```python
def build_agent_graph(
    model: BaseChatModel | None = None,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
```

`BaseCheckpointSaver` 是 LangGraph checkpoint 存储的统一抽象。构图函数只依赖这个接口，因此将来可以传入：

- `InMemorySaver`
- `SqliteSaver`
- PostgreSQL saver
- 其他实现了同一接口的存储

图编译时注入：

```python
return builder.compile(checkpointer=checkpointer)
```

节点、工具和条件边都不需要知道状态保存在哪里。存储职责留在图的编译与执行层，而不是混入业务节点。

如果 `checkpointer=None`，图保持前几课的无状态调用方式，也不要求 `thread_id`，所以已有调用方式继续兼容。

### Checkpointer 保存什么

当前图使用 `MessagesState`，因此 checkpoint 的核心状态是消息列表：

```python
{
    "messages": [
        HumanMessage(...),
        AIMessage(...),
        ToolMessage(...),
        ...,
    ]
}
```

Checkpointer 不是单独保存一段“记忆摘要”，而是在图步骤执行过程中保存状态快照。

一次工具 Agent 调用可能经过：

```text
model → tools → model
```

每一步都可能写入新的消息状态，因此 Checkpointer 同时也是恢复中间执行状态、支持后续中断与时间旅行等能力的基础。本课只使用其线程级消息记忆。

### `thread_id` 是状态主键

调用带 Checkpointer 的图时传入：

```python
config = {
    "configurable": {
        "thread_id": "thread-a"
    }
}
```

`thread_id` 不属于用户消息，也不属于 `MessagesState`。它位于运行配置中，供 Checkpointer 决定加载和保存哪一份状态。

可以理解为：

```text
thread-a → 线程 A 的最新 checkpoint
thread-b → 线程 B 的最新 checkpoint
```

LangGraph 官方说明 `thread_id` 是保存、加载和恢复 checkpoint 的主键：[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。

### 相同线程怎样续接历史

第一次调用：

```python
graph.invoke(
    {"messages": [HumanMessage(content="第一轮问题。")]},
    config,
)
```

执行过程：

```text
根据 thread-a 查询 checkpoint
    → 当前没有历史
    → 合并第一轮问题
    → 执行图
    → 追加第一轮回答
    → 保存 thread-a 最新状态
```

第二次调用仍使用相同配置，但只提交本轮新消息：

```python
graph.invoke(
    {"messages": [HumanMessage(content="第二轮问题。")]},
    config,
)
```

此时流程变成：

```text
根据 thread-a 加载已有状态
    → 恢复第一轮问题和回答
    → MessagesState 追加第二轮问题
    → 模型读取完整历史
    → 追加第二轮回答
    → 保存更新后的 checkpoint
```

最终消息顺序是：

```text
HumanMessage("第一轮问题。")
AIMessage("第一轮回答。")
HumanMessage("第二轮问题。")
AIMessage("第二轮回答。")
```

### 为什么调用方只提交本轮新消息

Checkpointer 已经负责恢复旧状态。如果第二次调用又手工传入第一轮完整历史，就会同时出现：

```text
Checkpointer 恢复的旧消息
调用方重复提交的旧消息
```

可能导致消息重复。

正确职责是：

```text
调用方        只提交本轮新增消息
Checkpointer  自动恢复旧状态
MessagesState 根据 reducer 合并新消息
```

### 不同线程怎样隔离

改用：

```python
{"configurable": {"thread_id": "thread-b"}}
```

Checkpointer 会访问另一个状态键。即使复用同一张 graph 和同一个模型，线程 B 的第一次调用仍从空状态开始，不会加载线程 A 的消息。

```text
thread-a:
    A 的问题和回答

thread-b:
    B 的问题和回答
```

线程隔离来自 Checkpointer 对 `thread_id` 的分区，不是模型自行区分用户会话。

### 使用 `graph.get_state()` 查看状态

测试调用：

```python
snapshot = graph.get_state(config)
```

返回的 `StateSnapshot` 中，最新消息位于：

```python
snapshot.values["messages"]
```

`get_state()` 读取 checkpoint，不重新调用模型，也不修改线程。

StateSnapshot 还可以包含：

- `config`：checkpoint ID 和线程配置。
- `metadata`：状态由哪个执行步骤写入。
- `next`：如果图处于暂停状态，下一步执行哪些节点。
- `created_at`：checkpoint 创建时间。

本课只读取最新消息；完整历史、时间旅行和分叉不在当前范围内。

### 为什么启用 Checkpointer 后必须传 `thread_id`

如果这样调用：

```python
graph = build_agent_graph(checkpointer=InMemorySaver())
graph.invoke({"messages": [HumanMessage(content="你好")]})
```

LangGraph 会在模型执行前拒绝请求，因为存储层无法判断：

```text
应该从哪里加载状态
应该把新状态保存到哪里
```

测试用以下规则固定该边界：

```python
with pytest.raises(ValueError, match="thread_id"):
    graph.invoke(...)
```

### `InMemorySaver` 的生命周期

本功能点使用：

```python
from langgraph.checkpoint.memory import InMemorySaver
```

它把所有 checkpoint 放在当前 Python 进程内存中，适合：

- 单元测试
- 学习线程语义
- 临时开发
- 不要求重启恢复的程序

它不能跨进程保存：

```text
Python 进程退出
    → 内存释放
    → 线程 checkpoint 消失
```

因此使用内存存储的两轮验证必须在同一个 Python 进程内完成。

### 测试驱动过程

#### `tests/test_agent.py`

同线程测试执行两次 `graph.invoke()`，第二次只传新问题，然后同时检查：

```python
second_result["messages"]
snapshot.values["messages"]
```

两处都必须包含第一轮和第二轮共四条消息。

线程隔离测试使用相同 graph 分别调用 `thread-a` 和 `thread-b`，确认线程 B 的最终状态只有自己的两条消息。

缺少线程 ID 的测试确认启用 Checkpointer 后，无配置调用会产生包含 `thread_id` 的 `ValueError`。

测试最初因为 `build_agent_graph()` 不接受 `checkpointer` 参数而失败。构图函数接收 `BaseCheckpointSaver` 并传给 `compile()` 后，图专项测试增加到 `6 passed`，完整项目测试为 `25 passed`。

### DeepSeek 真实多轮验证

真实验证在同一 Python 进程、同一 `thread_id` 下进行两轮对话：

```text
第一轮：请记住，我最喜欢的代号是青松。
第二轮：我最喜欢的代号是什么？
```

第二轮只提交新问题，DeepSeek 能从恢复的消息历史中回答“青松”，`graph.get_state()` 中共有四条消息。这证明以下链路可用：

```text
第一轮消息
    → InMemorySaver 保存 thread_id 对应状态
    → 第二轮使用相同 thread_id
    → 加载第一轮历史
    → 合并第二轮问题
    → DeepSeek 读取完整上下文
    → 保存第二轮状态
```

### 与 DeerFlow 源码的对应关系

DeerFlow Agent 工厂同样接收：

```python
checkpointer: BaseCheckpointSaver | None = None
```

并把它传给高层 `create_agent()`。DeerFlow 客户端明确说明，没有 Checkpointer 时每次 `chat()` 或 `stream()` 都是无状态调用；需要同一个 `thread_id` 多轮对话时必须提供 Checkpointer。

DeerFlow 运行配置同样包含：

```python
configurable = {
    "thread_id": thread_id,
    ...,
}
```

Mini Deer 和 DeerFlow 的共同结构是：

```text
构图阶段：注入 BaseCheckpointSaver
调用阶段：传入 thread_id
```

### 功能点 6.1 小结

完成这一功能点后，已经掌握：

- Checkpointer 保存的是图状态，而不只是最终文本。
- `thread_id` 如何作为 checkpoint 的加载与保存主键。
- 相同线程如何恢复历史并追加本轮消息。
- 不同线程如何共享 graph 但隔离状态。
- 为什么调用方只能提交本轮新消息。
- 如何使用 `graph.get_state()` 查看最新 `StateSnapshot`。
- `InMemorySaver` 为什么不能跨 Python 进程保存。
- Mini Deer 与 DeerFlow Checkpointer 注入方式的对应关系。

下一个功能点将安装 `langgraph-checkpoint-sqlite`，创建 SQLite 连接生命周期管理函数，并验证关闭 saver、重新创建 graph 后仍能恢复相同 `thread_id` 的消息。

## 功能点 6.2：SQLite 跨进程持久化

### 本次目标

把功能点 6.1 的进程内线程记忆升级为 SQLite 文件持久化。关闭 saver、graph 和整个 Python 进程后，新的进程仍能通过相同数据库路径与 `thread_id` 恢复原消息状态。

### 为什么需要独立依赖

`InMemorySaver` 随基础 LangGraph 提供，但 SQLite saver 是独立扩展。`pyproject.toml` 新增：

```toml
"langgraph-checkpoint-sqlite>=3.1.1,<3.2"
```

项目源码直接导入：

```python
from langgraph.checkpoint.sqlite import SqliteSaver
```

所以必须把该扩展声明为直接运行依赖，不能假设它会被其他库间接安装。

更新依赖后重新执行可编辑安装，虚拟环境安装了 `langgraph-checkpoint-sqlite 3.1.1`，`pip check` 确认没有依赖冲突。

LangGraph 官方同样把 SQLite saver 列为适合本地工作流的独立 Checkpointer 包：[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。

### SQLite 资源管理函数

#### `src/mini_deer_agent/storage.py`

存储入口定义为：

```python
@contextmanager
def open_sqlite_checkpointer(
    database_path: str | Path,
) -> Iterator[SqliteSaver]:
```

调用方式：

```python
with open_sqlite_checkpointer(database_path) as checkpointer:
    graph = build_agent_graph(checkpointer=checkpointer)
    graph.invoke(...)
    graph.get_state(...)
```

这个 API 把 SQLite 连接生命周期表达在 `with` 结构中，让调用方明确知道 graph 的状态操作只能在连接打开期间进行。

### 创建数据库父目录

函数首先执行：

```python
path = Path(database_path)
path.parent.mkdir(parents=True, exist_ok=True)
```

如果传入：

```text
data/checkpoints.sqlite
```

而 `data/` 尚不存在，代码只创建数据库的父目录。`exist_ok=True` 让已有目录可以重复使用，不会清空或覆盖其中内容。

### 打开与初始化 Saver

核心代码是：

```python
with SqliteSaver.from_conn_string(str(path)) as checkpointer:
    checkpointer.setup()
    yield checkpointer
```

进入上下文时：

```text
数据库文件路径
    → 创建或打开 SQLite 连接
    → SqliteSaver 持有连接
    → setup() 初始化表结构
    → yield saver 给 graph
```

`setup()` 幂等创建 Checkpointer 所需表和索引。已有数据库再次执行 `setup()` 不会删除线程状态。

数据库表由 `SqliteSaver` 管理，Mini Deer 不需要手工设计 checkpoint schema。Saver 会序列化：

- `thread_id`
- `checkpoint_id`
- `MessagesState`
- 节点写入
- checkpoint 元数据

### `@contextmanager` 与 `yield`

调用方进入：

```python
with open_sqlite_checkpointer(path) as checkpointer:
```

时，`storage.py` 执行到 `yield`，把仍然打开的 saver 交给调用方。调用方退出 `with` 后，控制流回到函数内部，`SqliteSaver` 的上下文关闭 SQLite 连接。

生命周期是：

```text
进入 open_sqlite_checkpointer
    → 打开 SQLite 连接
    → setup()
    → yield checkpointer
    → 构建 graph
    → invoke/get_state
    → 退出调用方 with
    → 关闭 SQLite 连接
```

### 为什么 graph 操作必须在 `with` 内

正确：

```python
with open_sqlite_checkpointer(path) as checkpointer:
    graph = build_agent_graph(checkpointer=checkpointer)
    graph.invoke(...)
```

错误：

```python
with open_sqlite_checkpointer(path) as checkpointer:
    graph = build_agent_graph(checkpointer=checkpointer)

graph.invoke(...)  # saver 仍被引用，但底层连接已经关闭
```

编译后的 graph 保存对 saver 的引用，但引用存在不代表数据库连接仍然可用。离开 `with` 后调用可能产生“对已关闭数据库进行操作”的错误。

资源嵌套关系是：

```text
SQLite 连接生命周期
└── SqliteSaver 可用生命周期
    └── graph 的 invoke/get_state 生命周期
```

### 数据库文件为什么不能提交 Git

`.gitignore` 新增：

```gitignore
data/
*.sqlite
*.sqlite-shm
*.sqlite-wal
```

SQLite 除了主数据库，还可能创建 WAL 和 SHM 文件。Checkpoint 中可能包含用户输入、模型回答、工具参数和工具结果，因此这些运行数据不能提交到代码仓库。

实际生成的 `data/checkpoints.sqlite` 已验证被 Git 忽略。

### 跨重开测试

#### `tests/test_storage.py`

测试数据库位于 pytest 的 `tmp_path`：

```python
database_path = tmp_path / "nested" / "checkpoints.sqlite"
```

它不会读取或修改正式运行数据。

第一阶段创建 saver、graph 和假模型，写入第一轮消息：

```python
with open_sqlite_checkpointer(database_path) as checkpointer:
    first_graph = build_agent_graph(
        first_model,
        checkpointer=checkpointer,
    )
    first_graph.invoke(...)
```

退出 `with` 后，第一套资源全部不再使用：

```text
第一个模型对象结束使用
第一个 graph 结束使用
第一个 saver 关闭
第一个 SQLite 连接关闭
```

第二阶段重新打开同一文件，并创建全新的 saver、graph 和假模型：

```python
with open_sqlite_checkpointer(database_path) as checkpointer:
    second_graph = build_agent_graph(
        second_model,
        checkpointer=checkpointer,
    )
    second_result = second_graph.invoke(...)
```

新旧运行之间唯一共享的是：

```text
相同数据库文件
相同 thread_id
```

第二次结果仍包含：

```text
第一轮消息
第一轮回答
第二轮消息
第二轮回答
```

这证明恢复来源是磁盘中的 SQLite checkpoint，而不是旧 Python 对象残留。

存储专项测试为 `1 passed`，完整项目测试增加到 `26 passed`。

### DeepSeek 跨进程真实验证

真实验证使用两个完全独立的 Python 进程。

第一进程：

```text
打开 data/checkpoints.sqlite
    → 使用 thread_id=sqlite-demo-20260825-v2
    → 告诉 DeepSeek 持久化代号是“云杉”
    → 保存第一轮 checkpoint
    → 关闭 saver 和进程
```

第二进程：

```text
重新打开同一 SQLite 文件
    → 创建新的 saver 和 graph
    → 使用相同 thread_id
    → 只提交“我的持久化代号是什么？”
    → 恢复第一轮历史
    → DeepSeek 回答“云杉”
```

第二进程的快照包含四条消息，证明完整链路可用：

```text
第一进程写入 checkpoint
    → SQLite 文件保留状态
    → 第一进程退出
    → 第二进程打开新连接
    → 根据 thread_id 加载状态
    → 合并第二轮问题
    → DeepSeek 读取完整历史
    → 保存第二轮 checkpoint
```

### PowerShell 管道编码问题

第一次验证尝试把包含中文的 here-string 通过 PowerShell 管道传给：

```powershell
python.exe -
```

Windows PowerShell 在管道编码过程中把中文变成了问号，DeepSeek 实际看到的是：

```text
??????
```

因此模型返回了“没有理解具体问题”，但这不是 SQLite 或 Checkpointer 故障。第一次线程可能已经正常持久化，只是保存的消息内容本身已经在进入 Python 前损坏。

修复方法是：

1. 使用新的 `thread_id`，避免旧乱码历史影响验证。
2. 使用 `python -c`，并在 Python 字符串中使用 ASCII 形式的 `\uXXXX` Unicode 转义。
3. Python 解释字符串时再恢复中文，从而绕开 PowerShell 管道文本编码。

修正后两个独立进程成功恢复“云杉”。这个问题再次说明：

```text
用户实际运行反馈 > 测试输出 > 对运行环境的推测
```

### SQLite 实际表结构

当前项目安装的是 `langgraph-checkpoint-sqlite 3.1.1`。直接检查依赖源码和 `data/checkpoints.sqlite` 后可以确认，这个版本只有两张业务表：

```text
checkpoints：保存每个图步骤完成后的状态快照
writes：保存节点基于某个快照产生的中间增量写入
```

其他 Checkpointer 后端或不同版本可能使用 `blobs`、`migrations` 等表，但当前版本的 `SqliteSaver` 没有这些表，不能把其他教程中的表结构直接套到本项目。

#### `checkpoints` 表

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `thread_id` | `TEXT` | 标识一条对话线程 |
| `checkpoint_ns` | `TEXT` | checkpoint 命名空间，当前通常为空字符串 |
| `checkpoint_id` | `TEXT` | 当前状态快照的唯一 ID |
| `parent_checkpoint_id` | `TEXT` | 上一个快照 ID，用于形成状态历史链 |
| `type` | `TEXT` | checkpoint 的序列化类型，当前实际值为 `msgpack` |
| `checkpoint` | `BLOB` | 序列化后的完整 LangGraph 状态快照 |
| `metadata` | `BLOB` | JSON 格式的执行元数据 |

它的联合主键是：

```text
(thread_id, checkpoint_ns, checkpoint_id)
```

因此，一条线程不是只对应一行，而是可以沿着 `parent_checkpoint_id` 保存很多个历史快照。

#### `writes` 表

| 字段 | 类型 | 作用 |
| --- | --- | --- |
| `thread_id` | `TEXT` | 所属线程 |
| `checkpoint_ns` | `TEXT` | 所属命名空间 |
| `checkpoint_id` | `TEXT` | 节点执行所基于的 checkpoint |
| `task_id` | `TEXT` | 产生写入的节点任务 ID |
| `idx` | `INTEGER` | 同一个任务中的写入顺序 |
| `channel` | `TEXT` | 写入的状态通道名称 |
| `type` | `TEXT` | 写入值的序列化类型 |
| `value` | `BLOB` | 序列化后的增量值 |

它的联合主键是：

```text
(thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
```

可以把两张表的职责理解为：

```text
writes
    = 某个节点刚产生了哪些增量结果

checkpoints
    = 增量结果合并后形成的完整状态快照
```

`writes` 也让 Checkpointer 能识别尚未合并的 pending writes，在中断恢复时判断哪些节点工作已经完成。

### checkpoint BLOB 中保存的状态

`SqliteSaver.put()` 不会把每条消息拆成单独的数据库记录，而是调用 serializer，把整个 checkpoint 序列化后写入 `checkpoints.checkpoint`。

当前数据库的最新 BLOB 解码后具有以下结构：

```python
{
    "v": 4,  # checkpoint 数据结构版本。
    "ts": "2026-08-25T09:09:33.897374+00:00",  # 快照创建时间。
    "id": "...",  # 当前 checkpoint 的唯一 ID。
    "channel_values": {
        "messages": [...],  # 当前时刻的完整消息历史。
    },
    "channel_versions": {...},  # 每个状态通道当前的数据版本。
    "versions_seen": {...},  # 各节点已经读取过的通道版本。
    "updated_channels": ["messages"],  # 这一步更新过的通道。
}
```

其中最重要的是：

```python
checkpoint["channel_values"]["messages"]
```

反序列化以后，这里仍然是 LangChain 消息对象列表，而不是失去类型信息的普通文本。它可以包含：

```text
HumanMessage：用户消息
AIMessage：模型消息，也可能携带 tool_calls
ToolMessage：工具执行结果，并携带 tool_call_id
SystemMessage：如果应用把系统消息放入状态，也会一起保存
```

所以发生工具调用时，AI 的工具请求、工具返回值和最终模型回答都能保持原来的消息类型与关联 ID。

当前图使用 `StateGraph(MessagesState)`，业务状态目前只有 `messages`。LangGraph 还会保存以下内部通道或调度信息：

```text
__start__：本轮输入入口
branch:to:model：下一步调度到 model 节点
channel_versions：通道版本
versions_seen：节点已经消费过的版本
updated_channels：本步发生变化的通道
```

以后如果把状态扩展为 `plan`、`current_step`、`user_profile` 等字段，这些字段也会成为状态通道并进入 checkpoint。

### 为什么两轮对话产生六个 checkpoint

成功线程 `sqlite-demo-20260825-v2` 中，两次 `graph.invoke()` 实际产生了六个 checkpoint，而不是两行记录：

```text
第一轮
    checkpoint 1：接收本轮 HumanMessage，保存输入状态
        → checkpoint 2：合并 HumanMessage，调度 model
        → checkpoint 3：合并 AIMessage，第一轮结束

第二轮
    checkpoint 4：保留第一轮历史并接收新的 HumanMessage
        → checkpoint 5：合并新 HumanMessage，调度 model
        → checkpoint 6：合并新 AIMessage，第二轮结束
```

最新 checkpoint 中的完整消息历史是：

```text
1. HumanMessage：请记住：我的持久化代号是云杉。只回复已记住。
2. AIMessage：已记住。
3. HumanMessage：我的持久化代号是什么？
4. AIMessage：您的持久化代号是：云杉。
```

对应的 `writes` 增量是：

```text
第一轮输入
    messages        → [HumanMessage]
    branch:to:model → 调度 model

第一次 model
    messages        → [AIMessage]

第二轮输入
    messages        → [HumanMessage]
    branch:to:model → 调度 model

第二次 model
    messages        → [AIMessage]
```

当前数据库一共有两个线程：

```text
sqlite-demo-20260825：3 个 checkpoint，保存了第一次编码损坏的问号消息
sqlite-demo-20260825-v2：6 个 checkpoint，保存了成功的两轮“云杉”对话
```

它们使用不同 `thread_id`，所以即使存放在同一个 SQLite 文件中也不会互相污染。

### 从 SQLite 恢复消息的完整流程

```text
调用 graph.invoke(..., config)
    → 从 config 读取 thread_id
    → 查询该线程最新的 checkpoint_id
    → 反序列化 checkpoint BLOB
    → 恢复 channel_values["messages"]
    → 合并本轮新 HumanMessage
    → model_node 把完整 state["messages"] 交给 DeepSeek
    → 保存本轮新的 writes 和 checkpoints
```

因此，不是 SQLite 理解并记住了“云杉”，而是 SQLite 保存了完整消息对象，LangGraph 恢复消息后再把完整历史交给模型。

还要注意，checkpoint 结构适合恢复 Agent 执行，但不适合直接使用 SQL 按关键词搜索聊天内容，因为消息正文位于序列化 BLOB 中。如果将来需要聊天记录列表、全文搜索或统计分析，应额外设计业务消息表，而不是直接查询 checkpoint BLOB。

### `InMemorySaver` 与 `SqliteSaver` 对比

```text
InMemorySaver
    存储位置：当前 Python 内存
    进程退出：状态消失
    适合：测试和临时开发

SqliteSaver
    存储位置：本地 SQLite 文件
    进程退出：状态保留
    适合：单机应用和本地学习
```

两者都通过同一个接口注入：

```python
build_agent_graph(checkpointer=checkpointer)
```

两者都通过相同配置选择线程：

```python
{"configurable": {"thread_id": "..."}}
```

更换存储后端不需要修改模型节点、工具节点或路由结构。

### 与 DeerFlow 源码的对应关系

DeerFlow 同步 Checkpointer 工厂的核心分支是：

```python
if config.type == "memory":
    yield InMemorySaver()

if config.type == "sqlite":
    with SqliteSaver.from_conn_string(conn_str) as saver:
        saver.setup()
        yield saver
```

Mini Deer 的 `open_sqlite_checkpointer()` 与 SQLite 分支保持相同的核心生命周期：

```text
打开 saver
    → setup()
    → yield 给 graph
    → 退出时关闭
```

DeerFlow 在此基础上还处理配置选择、全局单例、并发锁、缓存、WAL 参数和 PostgreSQL 等生产边界；Mini Deer 只保留当前学习目标需要的最小实现。

### 第 6 课小结

完成第 6 课后，已经掌握：

- Checkpointer 如何保存 LangGraph 状态快照。
- `thread_id` 如何定位和隔离线程状态。
- 同线程多轮调用为什么只提交本轮新消息。
- `InMemorySaver` 的同进程状态恢复和生命周期限制。
- `SqliteSaver` 如何跨 graph、连接和 Python 进程恢复状态。
- `setup()` 如何初始化 checkpoint 数据库结构。
- context manager 如何管理 SQLite 连接生命周期。
- 为什么 graph 的状态操作必须发生在 saver 的 `with` 内。
- 如何用 `tmp_path` 测试数据库而不污染正式数据。
- 为什么 checkpoint 数据库及 sidecar 文件必须被 Git 忽略。
- Mini Deer 与 DeerFlow Checkpointer 工厂的对应关系。
- 如何根据真实运行反馈识别 PowerShell 管道编码问题。
- 当前 `SqliteSaver` 的 `checkpoints` 与 `writes` 表分别保存什么。
- 为什么消息对象位于 checkpoint BLOB，而不是一条消息对应一行。
- 一次图调用为什么会按执行步骤生成多个 checkpoint。
- `channel_values`、`channel_versions`、`versions_seen` 和 pending writes 的职责。
- LangGraph 如何恢复状态并把完整消息历史重新交给模型。

下一课将学习 LangGraph 流式执行，逐步输出模型消息、工具调用和工具结果，而不是等待整个 Agent 循环全部完成后一次性返回。

# 第 7 课：LangGraph 流式执行

设计文档：`docs/plans/2026-08-25-lesson-07-langgraph-streaming.md`

本课把现有工具 Agent 从“一次性等待完整结果”升级为“执行过程中逐步交付事件”。课程拆成两个原子功能点：

1. 使用 `updates` 模式观察节点级状态增量。
2. 使用 `messages` 模式观察模型 token 级消息增量。

两个模式解决的问题不同，不能把节点完成事件和模型生成 chunk 混为一谈。

## 功能点 7.1：节点级流式更新

### 本功能点目标

先不处理 token 拼接，只观察每个图节点完成后返回的状态增量。真实天气工具循环应该依次暴露：

```text
model → tools → model
```

直接回答不需要工具时则只有：

```text
model
```

### 最小流式入口

`src/mini_deer_agent/streaming.py` 新增：

```python
def stream_agent_updates(
    graph: CompiledStateGraph,
    messages: Sequence[BaseMessage],
    config: RunnableConfig | None = None,
) -> Iterator[dict[str, Any]]:
    """按节点完成顺序惰性返回 LangGraph 状态增量。"""
    # 只提交本轮消息；旧历史由 Checkpointer 根据 thread_id 恢复。
    input_state = {"messages": list(messages)}

    # 直接转交底层迭代器，不能先收集全部结果再逐条返回。
    yield from graph.stream(
        input_state,
        config=config,
        stream_mode="updates",
    )
```

这个函数只负责三件事：

```text
接收已编译的 graph
    → 把本轮消息组装成 MessagesState 输入
    → 逐项转交 graph.stream() 的 updates 事件
```

它不创建模型、不改变图结构，也不把消息转换为普通字符串，因此调用方仍能读取 `AIMessage.tool_calls` 和 `ToolMessage.tool_call_id`。

### 为什么必须使用生成器

函数包含 `yield from`，所以调用它时只会创建生成器对象：

```python
# 此时函数体还没有开始执行，模型和工具都未被调用。
updates = stream_agent_updates(graph, messages)
```

调用方第一次请求元素时，执行才真正开始：

```python
# 第一次 next() 才驱动底层 graph.stream()。
first_update = next(updates)
```

如果错误地写成：

```python
# 错误示例：先执行完整张图，再把结果交给调用方。
updates = list(graph.stream(...))
```

那么调用方必须等模型、工具和最终模型回答全部完成后才能得到 `updates`。之后逐条打印只是“延迟展示已收集结果”，不是真正的流式执行。

专项测试使用 `RecordingStreamGraph` 验证：

```text
只创建生成器 → started=False
第一次 next() → started=True
```

### `updates` 事件结构

LangGraph 对 `updates` 的定义是：节点或任务完成后，只返回它产生的状态增量。如果同一个图步骤中有多个节点更新，它们会分别交付。

Mini Deer 的 `model_node()` 原本返回：

```python
# 节点只返回本次新增的模型消息。
return {"messages": [response]}
```

LangGraph 会在外层增加节点名，因此调用方收到：

```python
{
    "model": {
        "messages": [AIMessage(...)],
    }
}
```

工具节点完成后收到：

```python
{
    "tools": {
        "messages": [ToolMessage(...)],
    }
}
```

最外层 key 说明哪个节点刚刚结束，内层字典是这个节点写入共享状态的增量，不是整张图的完整 `MessagesState`。

### 天气工具的完整流式调用链

```text
stream_agent_updates()
    → graph.stream(stream_mode="updates")
    → model_node 调用 DeepSeek
    → yield model + AIMessage(tool_calls=[get_weather])
    → tools_condition 路由到 tools
    → ToolNode 调用真实 get_weather
    → yield tools + ToolMessage(天气结果)
    → tools 边返回 model
    → model_node 再次调用 DeepSeek
    → yield model + AIMessage(最终回答)
    → 图结束
```

这里的第一个 `AIMessage` 虽然正文可能为空，但其中的 `tool_calls` 是结构化工具请求，不能因为 `message.text` 为空就忽略整条消息。

`ToolMessage.tool_call_id` 对应第一个 `AIMessage.tool_calls[*].id`，模型依靠这个关联知道工具结果属于哪次工具请求。

### `invoke()` 和 `stream()` 的关系

LangGraph 的 `invoke()` 并不是另一套图执行器。依赖源码显示，`invoke()` 内部同样迭代 `self.stream()`，只是把产生的 chunk 收集起来，最终只把完整结果交给调用方。

```text
stream()
    → 每产生一个事件就 yield

invoke()
    → 内部消费 stream()
    → 收集运行结果
    → 图结束后一次性 return
```

所以，从 `invoke()` 切换到 `stream()` 不会改变模型节点、工具节点、条件边或 MessagesState，只改变调用方观察执行过程的方式。

### 与 Checkpointer 的关系

`stream_agent_updates()` 把可选 `config` 原样传给 `graph.stream()`，因此已有的 `thread_id` 语义保持不变：

```python
# 相同 thread_id 会先恢复已有 checkpoint，再合并本轮新消息。
config = {"configurable": {"thread_id": "weather-thread"}}
updates = stream_agent_updates(graph, new_messages, config)
```

如果 graph 使用 SQLite Checkpointer，整个 `for` 迭代必须位于 saver 的 `with` 内。创建生成器后立即退出 `with` 仍然是错误的，因为生成器还没有真正执行数据库读取与 checkpoint 写入。

### 测试覆盖

`tests/test_streaming.py` 使用假模型和假天气函数完成三项离线验证：

1. 创建生成器不会提前运行图，第一次迭代才开始。
2. 模型直接回答时只产生一个 `model` 更新。
3. 天气工具请求依次产生 `model → tools → model`，并保留 `AIMessage`、`ToolMessage` 和关联 ID。

完成实现后的全量回归结果：

```text
29 passed
```

### DeepSeek 与真实天气工具验证

为了避免把大段 Python 源码通过 PowerShell 参数或管道传递，项目增加：

```text
examples/stream_updates_demo.py
```

脚本直接创建真实 DeepSeek 图，并提交必须使用 `get_weather` 的北京天气请求。用户实际运行后成功观察到预期节点序列：

```text
model
    → AIMessage，包含 get_weather 工具请求
tools
    → ToolMessage，包含 Open-Meteo 真实天气结果
model
    → AIMessage，包含最终中文回答
```

这证明节点事件是在 Agent 循环执行过程中逐步交付，而不是等 `graph.invoke()` 完成后一次性返回。

### PowerShell `python -c` 引号问题

第一次真实验证把多行 Python 代码保存在 PowerShell `$code` 变量中，再执行：

```powershell
# Windows PowerShell 可能重新解析变量中的原生命令参数引号。
python.exe -c $code
```

Python 最终看到：

```python
# 原来的字符串双引号被移除，You 被当成了变量名。
prompt = You
```

因此产生：

```text
NameError: name 'You' is not defined
```

这与之前的管道中文编码问题不同：

```text
python.exe -
    → 风险是 PowerShell 管道编码损坏中文

python.exe -c $code
    → 风险是 Windows PowerShell 原生命令参数重新处理引号
```

稳定方案是把示例保存为 `.py` 文件，让 PowerShell 只传递文件路径：

```powershell
# 文件内容由 Python 直接读取，不经过 PowerShell 源码转义。
.\.venv\Scripts\python.exe .\examples\stream_updates_demo.py
```

### 与 DeerFlow 源码的对应关系

DeerFlow 的同步客户端同样直接调用编译图的 `stream()`：

```python
# DeerFlow 同时订阅完整状态、模型消息增量和自定义事件。
for item in self._agent.stream(
    state,
    config=config,
    context=context,
    stream_mode=["values", "messages", "custom"],
):
    ...
```

DeerFlow 随后还会完成消息去重、token 用量累计、工具结果转换以及客户端事件封装。Mini Deer 当前只订阅 `updates`，直接观察 LangGraph 原始节点状态增量。

### 当前功能边界

`updates` 是节点级流式，不是 token 级流式：

```text
模型开始生成正文
    → updates 模式暂时没有事件
    → model 节点生成完整 AIMessage
    → updates 模式返回一次 model 更新
```

下一个功能点将使用 `stream_mode="messages"`，在模型生成过程中接收 `AIMessageChunk` 和 metadata，并把同一消息 ID 的文本增量累积成完整回答。

## 功能点 7.2：模型消息增量

### 本功能点目标

`updates` 只能在节点结束后返回完整状态增量。本功能点改用：

```python
# messages 模式在模型生成过程中返回消息 chunk。
graph.stream(input_state, stream_mode="messages")
```

目标是在工具 Agent 执行期间观察：

```text
模型逐步生成工具名和 JSON 参数
    → 工具返回完整 ToolMessage
    → 模型逐步生成最终正文
    → 消费端按消息 ID 拼回完整回答
```

### 消息流入口

`src/mini_deer_agent/streaming.py` 新增事件类型：

```python
# 单一 messages 模式的一个事件由消息对象和 LangGraph metadata 组成。
type AgentMessageEvent = tuple[BaseMessage, dict[str, Any]]
```

以及流式生成器：

```python
def stream_agent_messages(
    graph: CompiledStateGraph,
    messages: Sequence[BaseMessage],
    config: RunnableConfig | None = None,
) -> Iterator[AgentMessageEvent]:
    """惰性返回模型消息增量、工具消息及其 LangGraph 元数据。"""
    # Checkpointer 仍会根据 config 中的 thread_id 恢复旧历史。
    input_state = {"messages": list(messages)}

    # 单一 messages 模式固定返回 (消息, metadata)。
    events = cast(
        Iterator[AgentMessageEvent],
        graph.stream(
            input_state,
            config=config,
            stream_mode="messages",
        ),
    )
    # 不预先收集事件，保留每个 token 的抵达时机。
    yield from events
```

只有一个 stream mode 时，迭代元素直接是：

```python
# message 是 AIMessageChunk 或 ToolMessage，metadata 描述来源节点等运行信息。
message, metadata = event
```

如果同时订阅多个模式：

```python
# 多模式事件会再增加一层 mode 名称。
stream_mode=["updates", "messages"]
```

返回形状才会变成：

```python
# data 在 messages 模式下仍然是 (message, metadata)。
mode, data = event
```

### 为什么 `model.invoke()` 仍能逐 token 输出

Mini Deer 的 `model_node()` 没有改成 `model.stream()`，仍然调用：

```python
# 节点保持统一 invoke 写法。
response = model.invoke(state["messages"])
```

流式行为由调用图时安装的回调触发：

```text
graph.stream(stream_mode="messages")
    → LangGraph 安装 StreamMessagesHandler
    → model_node 调用 model.invoke()
    → BaseChatModel 检查当前 callback handlers
    → 发现 _StreamingCallbackHandler
    → 自动走聊天模型的 _stream() 实现
    → 每个模型 chunk 触发 on_llm_new_token
    → LangGraph 向外发送 (AIMessageChunk, metadata)
```

因此，节点内部可以继续使用统一的 `invoke()`，最外层调用方通过选择 `invoke()` 或 `stream()` 决定如何观察运行结果。

如果具体模型没有实现流式 API，或者显式关闭 streaming，就不能得到真正的 token 增量，只能在模型完成时收到完整消息。当前 DeepSeek 的 OpenAI-compatible 接口可以正常产生流式 chunk。

### `StreamMessagesHandler` 的两类消息来源

LangGraph 的消息处理器同时收集：

```text
来源 1：聊天模型流事件
    on_llm_new_token
        → AIMessageChunk

来源 2：图节点输出
    on_chain_end
        → 在节点返回值中查找 BaseMessage
        → 例如 ToolMessage
```

工具函数不是聊天模型，不会产生 token，也不会触发 `on_llm_new_token`。`ToolNode` 执行结束后返回完整 `ToolMessage`，处理器从节点输出中找到它并发送到同一个 messages 流。

所以 `stream_mode="messages"` 不是“只返回模型消息”，而是“返回图运行过程中产生的消息对象，其中模型消息可以细化为 chunk”。

### metadata 如何说明消息来源

每个事件的第二个元素是 metadata。当前学习最常用的字段是：

```python
# model 表示模型生成，tools 表示工具节点输出。
node_name = metadata["langgraph_node"]
```

真实运行因此可以显示：

```text
节点: model
    → 工具调用 AIMessageChunk

节点: tools
    → 完整 ToolMessage

节点: model
    → 最终正文 AIMessageChunk
```

metadata 还可能包含图步骤、触发条件、checkpoint namespace、模型提供方和模型名称等运行信息。它适合用于日志、UI 分组和事件过滤，不应混入模型正文。

### 按 `message.id` 累积正文

一条模型回答会被拆成许多增量：

```text
AIMessageChunk(id="answer-1", content="北京")
AIMessageChunk(id="answer-1", content="当前")
AIMessageChunk(id="answer-1", content="有")
AIMessageChunk(id="answer-1", content="雷暴")
```

消费端必须追加同一 ID 的正文：

```python
# 不能用赋值覆盖旧 chunk，必须按照到达顺序追加。
text_by_message_id[message.id] = (
    text_by_message_id.get(message.id, "") + message.text
)
```

最终恢复为：

```text
北京当前有雷暴
```

不能把一次运行的所有 chunk 不分 ID 地拼在一起，因为 Agent 可能多次调用模型。工具请求和最终回答通常属于不同模型消息，拥有不同 `message.id`。

### 工具调用为什么分成很多 chunk

真实 DeepSeek 输出首先返回：

```text
name=get_weather
args=""
id=call_00_...
index=0
```

后续 chunk 继续返回同一个工具调用的参数片段：

```text
{
"
city
"
:
"
北京
"
}
```

后续片段中的 `name` 和 `id` 可以是 `None`，因为它们已经在第一个 chunk 中发送。所有片段的 `index=0` 表示它们属于本次模型消息中的第零个工具调用。

不能把每个 `tool_call_chunk` 当成独立工具请求。正确聚合语义是：

```text
相同模型调用 + 相同 index
    → 保留最先出现的 name
    → 保留最先出现的 id
    → 按顺序拼接所有 args 字符串
    → 解析完整 JSON
    → 得到结构化 tool_calls
```

LangChain 完成聚合后，模型节点最终得到：

```python
# 聚合后的 AIMessage 才交给 tools_condition 和 ToolNode。
{
    "name": "get_weather",
    "args": {"city": "北京"},
    "id": "call_00_...",
    "type": "tool_call",
}
```

这证明流式展示和 Agent 内部执行使用的是同一批 chunk：调用方可以提前看到参数生成过程，同时 LangChain 仍会把它们聚合成 ToolNode 可执行的完整请求。

### 三类 ID 不能混淆

真实输出同时出现三种关联标识：

```text
AIMessageChunk.message.id
    示例：lc_run--01a03863-...
    作用：标识一条模型消息，用于累积正文 chunk

tool_call.id
    示例：call_00_YLXGpdp5...
    作用：标识一次具体工具请求

ToolMessage.tool_call_id
    示例：call_00_YLXGpdp5...
    作用：把工具结果关联回 tool_call.id
```

关系是：

```text
多个 AIMessageChunk
    └── 相同 message.id，拼成一条模型消息
          └── 内含 tool_call.id
                └── ToolMessage.tool_call_id 与它相等
```

`message.id` 与 `tool_call.id` 属于不同层级，不能用其中一个替代另一个。

### 测试模型如何模拟真实流

`tests/test_streaming.py` 增加 `ToolAwareStreamingFakeModel`：

```text
正文 AIMessage
    → 按字符产生多个 AIMessageChunk

工具请求 AIMessage
    → 转成带 tool_call_chunks 的 AIMessageChunk
```

专项测试验证：

1. 正文以多个 `AIMessageChunk` 抵达。
2. chunk metadata 中的 `langgraph_node` 是 `model`。
3. 相同模型消息的 chunk 使用稳定 ID。
4. 工具请求 chunk 能聚合成完整 `tool_calls` 并驱动 ToolNode。
5. `ToolMessage.tool_call_id` 与工具请求 ID 一致。
6. 最终正文可以按消息 ID 拼回原始回答。

完整项目回归结果增加到：

```text
31 passed
```

### DeepSeek 真实增量验证

项目新增：

```text
examples/stream_messages_demo.py
```

示例边迭代边执行：

```python
# end="" 避免每个 token 自动换行，flush=True 让增量立即出现在终端。
print(message.text, end="", flush=True)
```

用户实际运行成功观察到：

```text
model
    → get_weather 工具名和调用 ID
    → {"city": "北京"} 被拆成多个参数 chunk

tools
    → 一次性返回北京雷暴、温度、体感温度和风速

model
    → 最终中文回答逐步输出
```

最终正文的所有 chunk 使用稳定 ID：

```text
lc_run--01a03863-9f22-7832-b381-b45eeeab7563
```

示例按该 ID 累积出的完整文本与终端逐步显示的回答一致，证明这不是完整回答生成后再拆分打印，而是从 DeepSeek 流式响应中逐块接收。

### 与 DeerFlow 源码的对应关系

DeerFlow 同步客户端同时订阅：

```python
# 多模式订阅让 DeerFlow 同时获得完整状态、模型增量和自定义事件。
stream_mode=["values", "messages", "custom"]
```

当收到 `messages` 模式事件时，它会：

```text
解包 (message_chunk, metadata)
    → 提取 AI 文本增量
    → 使用稳定 message.id 标识逻辑消息
    → 转换为 messages-tuple 客户端事件
    → 累计 token usage_metadata
```

DeerFlow 还维护已经通过 messages 模式发送的消息 ID。当后续 `values` 模式返回包含完整历史的状态快照时，会跳过这些已发送消息，避免客户端收到重复正文。

工具请求和工具结果仍按逻辑消息发送一次；HTTP Gateway 则在这些 Python 事件外再增加异步队列、SSE 序列化、心跳和断线重放。

Mini Deer 本课没有复制网络层，只保留：

```text
CompiledStateGraph.stream(messages)
    → AIMessageChunk / ToolMessage
    → Python 生成器
    → 终端增量显示与按 ID 累积
```

### 第 7 课小结

完成第 7 课后，已经掌握：

- `graph.stream()` 为什么是真正的惰性执行。
- `invoke()` 如何在内部消费 stream 并最终返回完整状态。
- `updates` 如何返回节点级状态增量。
- 天气工具循环为什么产生 `model → tools → model`。
- `messages` 如何返回 `(BaseMessage, metadata)`。
- 为什么节点写 `model.invoke()` 仍能触发模型流式 API。
- `StreamMessagesHandler` 如何同时收集模型 chunk 和节点消息。
- 如何使用 `metadata["langgraph_node"]` 判断事件来源。
- 如何按稳定 `message.id` 累积模型正文。
- `tool_call_chunks` 如何逐步组成工具名和 JSON 参数。
- `message.id`、`tool_call.id` 与 `ToolMessage.tool_call_id` 的区别。
- 流式执行如何继续兼容 `thread_id` 和 Checkpointer。
- Mini Deer 原始事件流与 DeerFlow 客户端事件协议的对应关系。
- 为什么 Windows PowerShell 验证应优先运行 `.py` 示例文件。

下一课将把当前 Python 消息生成器接入 FastAPI，通过 SSE 向 HTTP 客户端持续发送 Agent 事件。

# 第 8 课：FastAPI 与 SSE 流式聊天接口

设计文档：`docs/plans/2026-08-25-lesson-08-fastapi-sse.md`

本课把第 7 课的 Python 消息生成器逐步接到 HTTP 边界，拆成三个原子功能点：

1. 把 Agent 消息编码成标准 SSE 文本帧。
2. 使用 FastAPI `StreamingResponse` 暴露 `/chat/stream`。
3. 使用 SQLite 和 `thread_id` 恢复跨 HTTP 请求的对话历史。

## 功能点 8.1：SSE 帧编码器

### 本功能点目标

本功能点只建立消息事件与网络协议文本之间的转换层：

```text
AgentMessageEvent
    → SSE 编码器
    → event/data 文本帧
```

它不启动 FastAPI、不创建 graph、不读取模型配置，也不访问 DeepSeek 或天气 API，因此可以完全离线测试。

### SSE 最小帧结构

一个 SSE 事件由字段行和结尾空行组成：

```text
event: ai_delta
data: {"id":"message-1","content":"北京"}

```

这里实际存在两个连续换行：

```text
event 行结尾 \n
data 行结尾  \n
空行结尾       \n
```

用 Python 字符串表达就是：

```python
# 最后的 \n\n 让 SSE 客户端知道当前事件已经完整结束。
frame = 'event: ai_delta\ndata: {"content":"北京"}\n\n'
```

如果没有最后的空行，SSE 客户端可能继续等待更多字段，不会立即把事件交给应用代码。

### `format_sse()` 的职责

`src/mini_deer_agent/sse.py` 新增：

```python
def format_sse(event: str, data: Mapping[str, Any]) -> str:
    """把事件名和 JSON 数据编码为一个以空行结尾的 SSE 帧。"""
    # event 会直接写入协议字段，不能允许换行注入其他字段。
    if "\n" in event or "\r" in event:
        raise ValueError("SSE 事件名不能包含换行")

    # 紧凑 JSON 让 data 保持一行，ensure_ascii=False 保留可读中文。
    payload = json.dumps(
        dict(data),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # 两个结尾换行构成 SSE 事件结束空行。
    return f"event: {event}\ndata: {payload}\n\n"
```

这个函数只负责一帧，不关心数据来自模型、工具还是其他业务模块。

### 为什么 `data:` 使用单行 JSON

SSE 允许一帧包含多个 `data:` 行，但 Mini Deer 选择每帧只发送一行 JSON：

```text
event: ai_delta
data: {"content":"第一行\n第二行"}

```

正文中的真实换行经过 `json.dumps()` 后会变成 JSON 字符串里的 `\n` 转义，不会变成新的 SSE 协议行。

这样做的好处是：

- 客户端对每个事件只需执行一次 `JSON.parse()`。
- 模型正文换行不会被误认为协议字段。
- 抓包时一帧事件与一行 JSON 一一对应。
- 中文通过 `ensure_ascii=False` 保持可读，不会全部显示成 `\uXXXX`。

`separators=(",", ":")` 会去掉 JSON 中不必要的空格，减少大量 token chunk 带来的传输开销。

### 为什么校验事件名换行

如果事件名允许包含用户可控换行：

```python
# 危险输入可能注入新的 SSE event 字段。
event = "ai_delta\nevent: injected"
```

拼接后会产生两个协议字段。当前事件名虽然都来自内部常量，但编码器在协议边界主动拒绝 `\n` 和 `\r`，避免未来调用方误把外部输入直接作为事件名。

JSON 数据不采用字符串手工拼接，所以正文中的引号、反斜杠和换行由 JSON 编码器安全处理。

### Agent 消息到事件名的映射

`iter_sse_frames()` 按消息抵达顺序完成以下映射：

```text
AIMessageChunk.text 非空
    → ai_delta

AIMessageChunk.tool_call_chunks 非空
    → tool_call_chunk

ToolMessage
    → tool_result

消息流正常结束
    → end
```

`ai_delta` 数据保留：

```json
{
  "id": "message-model-1",
  "content": "北京",
  "node": "model"
}
```

`tool_call_chunk` 保留 LangChain 的原始工具参数分片：

```json
{
  "id": "message-model-1",
  "chunks": [
    {
      "name": "get_weather",
      "args": "{\"city\":\"北京\"}",
      "id": "call-weather-1",
      "index": 0,
      "type": "tool_call_chunk"
    }
  ],
  "node": "model"
}
```

`tool_result` 保留消息和工具调用两层关联 ID：

```json
{
  "id": "message-tool-1",
  "tool_call_id": "call-weather-1",
  "name": "get_weather",
  "content": "北京当前天气：雷暴。",
  "node": "tools"
}
```

客户端可以根据 `event:` 选择处理分支，不需要先检查 JSON 中有哪些字段。

### 同一个 AI chunk 可以产生两个 SSE 事件

一个 `AIMessageChunk` 理论上可以同时包含正文和工具调用分片。因此实现使用两个独立判断：

```python
if message.text:
    # 正文事件立即交给客户端追加到回答区域。
    yield format_sse("ai_delta", ...)

if message.tool_call_chunks:
    # 工具事件独立发送，不能被上一个正文分支排除。
    yield format_sse("tool_call_chunk", ...)
```

不能写成：

```python
# 错误示例：正文存在时会跳过工具调用分片。
if message.text:
    ...
elif message.tool_call_chunks:
    ...
```

测试专门构造了同时携带两类数据的 `AIMessageChunk`，确认编码器连续产生 `ai_delta` 和 `tool_call_chunk`。

### 错误事件和结束事件

模型或工具异常可能发生在已经发送若干 SSE 帧以后。等 FastAPI 开始发送响应体时，HTTP 响应头已经确定，不能再把原来的成功状态修改成 `500`。

转换器捕获普通运行异常后：

```text
详细异常和 traceback
    → 写入服务端 logger

客户端响应
    → event: error
    → data: {"message":"Agent execution failed"}
    → event: end
```

实现不会把原始异常文本放进 SSE 数据，避免 API Key、内部 URL、请求参数或堆栈信息泄露给客户端。

无论正常完成还是已处理异常，都会发送：

```text
event: end
data: {}

```

`end` 是业务级结束标志。客户端收到后可以停止加载动画、启用输入框并完成本轮消息，不必依赖 TCP 连接何时关闭。

如果客户端主动断开并关闭生成器，Python 会使用 `GeneratorExit`，它不属于普通 `Exception`；当前转换器不会错误地把主动断开伪装成 Agent 执行失败。

### 离线演示脚本

项目新增：

```text
examples/sse_frames_demo.py
```

脚本构造固定 `AIMessageChunk` 和 `ToolMessage`，再直接打印转换后的帧。它完全不访问外部服务。

Windows 命令捕获器第一次显示中文时发生了代码页误判，但测试中的 JSON 解码结果仍是正确中文。示例随后显式设置：

```python
# 统一标准输出编码，避免 Windows 管道或捕获器误解中文字节。
sys.stdout.reconfigure(encoding="utf-8")
```

修正后离线输出依次是：

```text
ai_delta
    → 正在查询北京天气。
tool_call_chunk
    → get_weather + {"city":"北京"}
tool_result
    → 北京当前天气：雷暴，温度 24°C。
end
    → {}
```

### 测试覆盖

`tests/test_sse.py` 完成四项协议测试：

1. 中文保留原文，正文换行被编码在单行 JSON 中。
2. 事件名中的 `\n` 或 `\r` 被拒绝。
3. 正文、工具调用、工具结果和结束事件顺序正确，每帧以空行结束。
4. 上游异常不会泄露内部文本，并在 `error` 后继续发送 `end`。

本功能点完成后的全量回归结果：

```text
35 passed
```

### 与 DeerFlow 源码的对应关系

DeerFlow 的 `format_sse()` 使用相同核心结构：

```python
def format_sse(event: str, data: Any, *, event_id: str | None = None) -> str:
    """编码与 LangGraph Platform 客户端兼容的 SSE 帧。"""
    # JSON 保留中文，再按 event、data、可选 id 的顺序组成字段。
    payload = json.dumps(data, default=str, ensure_ascii=False)
    parts = [f"event: {event}", f"data: {payload}"]
    if event_id:
        parts.append(f"id: {event_id}")
    # 两个空字符串在 join 后产生结束空行。
    parts.extend(["", ""])
    return "\n".join(parts)
```

与 Mini Deer 相同的部分：

```text
event 字段
data JSON
ensure_ascii=False
结尾空行
```

DeerFlow 额外支持 `id:` 字段，并在 `sse_consumer()` 中处理：

- `Last-Event-ID` 断线续传。
- 心跳注释帧。
- 事件重放缺口。
- 结束哨兵。
- 客户端断开后的取消或继续策略。

Mini Deer 当前只建立单连接、无重放的最小协议编码层。下一功能点才会把这个生成器交给 FastAPI `StreamingResponse`。

### 当前功能边界

现在已经能产生合法 SSE 文本，但还没有 HTTP 接口：

```text
已完成
    Agent 消息 → SSE 字符串

尚未完成
    HTTP 请求 → FastAPI 路由
    SSE 字符串 → StreamingResponse → 客户端
```

## 功能点 8.2：FastAPI HTTP 流式端点

### 本功能点目标

把功能点 8.1 的 SSE 帧生成器交给 FastAPI：

```text
POST /chat/stream
    → 校验用户消息
    → 创建 Agent 消息生成器
    → 转成 SSE 帧生成器
    → StreamingResponse 逐块发送
```

当前先完成无状态 HTTP 流。请求之间恢复 SQLite 历史留到功能点 8.3。

### 请求模型与前置校验

`src/mini_deer_agent/api.py` 新增：

```python
class ChatStreamRequest(BaseModel):
    """校验流式聊天端点接收的本轮用户消息。"""

    # 先清理首尾空白，再检查清理后的消息是否为空。
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ]
```

输入：

```json
{"message":"  你好  "}
```

路由中得到：

```text
你好
```

输入纯空白时，Pydantic 在调用路由前返回 HTTP `422`。因此：

```text
请求体解析
    → strip_whitespace
    → min_length 检查失败
    → 返回 422
    → 不创建 graph
    → 不调用 DeepSeek
```

这个错误发生在响应开始前，可以使用正常 HTTP 状态表达；它与模型运行中途发生的 SSE `error` 事件属于不同错误阶段。

### 真实 Agent 消息流工厂

```python
def create_agent_message_stream(message: str) -> Iterator[AgentMessageEvent]:
    """为单次无状态 HTTP 请求创建真实 Agent 消息流。"""
    # 生成器第一次被响应体迭代时，才会创建模型并执行图。
    graph = build_agent_graph()
    # 本功能点没有 Checkpointer，每次 HTTP 请求都从空状态开始。
    yield from stream_agent_messages(
        graph,
        [HumanMessage(content=message)],
    )
```

因为函数包含 `yield from`，调用它只创建生成器对象：

```python
# 此时 create_agent_message_stream() 的函数体还没有运行。
message_events = create_agent_message_stream(message)
```

只有 `StreamingResponse` 第一次请求响应块时才会进入函数体并执行 `build_agent_graph()`。

如果工厂在返回生成器之前调用 `list(stream_agent_messages(...))`，就会先等待完整 Agent 结束，破坏 HTTP 流式语义。

### 为什么使用 FastAPI 依赖提供工厂

路由没有直接硬编码调用函数，而是定义：

```python
def get_agent_message_stream_factory() -> AgentMessageStreamFactory:
    """提供可被 FastAPI 测试覆盖的消息流工厂依赖。"""
    # 生产环境返回连接真实 DeepSeek 的实现。
    return create_agent_message_stream
```

测试可以覆盖这个依赖：

```python
# 只替换模型事件来源，路由和 SSE 编码仍使用真实实现。
app.dependency_overrides[get_agent_message_stream_factory] = (
    lambda: fake_stream_factory
)
```

这比在测试中直接替换整个 `/chat/stream` 路由更有价值，因为测试仍然覆盖：

- Pydantic 请求校验。
- FastAPI 依赖解析。
- `iter_sse_frames()` 转换。
- `StreamingResponse` 响应体。
- HTTP 响应头。

假工厂只隔离 DeepSeek 和 Open-Meteo，离线测试不会消耗额度或依赖网络。

### `/chat/stream` 路由

```python
@app.post("/chat/stream")
def chat_stream(
    request: ChatStreamRequest,
    stream_factory: Annotated[
        AgentMessageStreamFactory,
        Depends(get_agent_message_stream_factory),
    ],
) -> StreamingResponse:
    """把本轮 Agent 消息作为 SSE 事件流返回给 HTTP 客户端。"""
    # 这里创建两层生成器，但还没有执行模型。
    message_events = stream_factory(request.message)
    frames = iter_sse_frames(message_events)

    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={
            # 禁止客户端或代理缓存旧事件。
            "Cache-Control": "no-cache",
            # 当前通过 HTTP/1.1 长连接逐步发送响应体。
            "Connection": "keep-alive",
            # 提示 Nginx 不要缓冲完整响应。
            "X-Accel-Buffering": "no",
        },
    )
```

两层生成器的关系是：

```text
StreamingResponse
    → 请求下一条 SSE frame
    → iter_sse_frames 请求下一条 AgentMessageEvent
    → stream_agent_messages 请求下一条 LangGraph 消息
    → DeepSeek 或 ToolNode 继续执行
    → 消息向外层层返回
    → 字符串编码成 HTTP body chunk
```

这是一条拉取式链路。最外层 HTTP 消费者继续读取，才会驱动内层 Agent 继续执行。

### Starlette 如何消费同步生成器

FastAPI 底层使用 Starlette。`StreamingResponse` 收到同步 `Iterable` 后执行：

```python
# 同步生成器被包装到线程池迭代，避免直接阻塞异步事件循环。
self.body_iterator = iterate_in_threadpool(content)
```

发送过程可以简化为：

```text
发送 http.response.start
    → async for 读取 body_iterator
    → 取得一个 str chunk
    → 按 UTF-8 编码为 bytes
    → 发送 http.response.body，more_body=True
    → 继续下一块
    → 生成器结束
    → 发送空 body，more_body=False
```

因此当前同步 `graph.stream()` 和 `SqliteSaver` 可以先与 FastAPI 共存，不需要为了提供 HTTP 接口立即把整条链路改成异步。

线程池解决的是“不要阻塞 ASGI 事件循环”，不等于已经获得 DeerFlow 的后台任务、跨 Worker 队列或多订阅者能力。

### HTTP 响应头

`media_type="text/event-stream"` 最终生成：

```text
Content-Type: text/event-stream; charset=utf-8
```

`charset=utf-8` 保证中文 JSON 按正确编码解释。

三个显式响应头分别是：

```text
Cache-Control: no-cache
    → 不缓存旧聊天事件

Connection: keep-alive
    → 保持 HTTP/1.1 连接以持续传输响应体

X-Accel-Buffering: no
    → 提示 Nginx 等代理不要缓冲完整响应
```

需要注意，这些头只是协议和代理提示。真实部署还要确保反向代理、压缩中间件和托管平台没有重新积攒事件。

### 响应开始后的错误语义

Starlette 会先发送：

```text
http.response.start，status=200
```

然后才开始迭代 SSE 生成器。所以模型或工具错误发生时，HTTP `200` 可能已经在网络上，不能再发送第二个状态行改成 `500`。

功能点 8.1 的 `iter_sse_frames()` 正是在这个边界把异常转换为：

```text
event: error
data: {"message":"Agent execution failed"}

event: end
data: {}

```

客户端必须同时判断 HTTP 状态和 SSE 业务事件，不能认为收到 `200` 就代表整次 Agent 运行一定成功。

### 自动化测试与真实流式验证的边界

`tests/test_chat_stream.py` 使用 `TestClient.stream()` 完成两项测试：

1. 有效消息首尾空格被清理，假消息流转换为两个 `ai_delta` 和一个 `end`。
2. 纯空白消息返回 `422`，消息流工厂完全没有被调用。

测试同时确认：

```text
Content-Type 以 text/event-stream 开头
Cache-Control = no-cache
Connection = keep-alive
X-Accel-Buffering = no
```

但 ASGI `TestClient` 可能把完整响应体缓存在内存，因此它能证明协议内容和顺序，不能单独证明真实网络客户端会在不同时间收到每一帧。

本功能点完成后的全量回归结果：

```text
37 passed
```

### PowerShell 安全请求文件

此前 PowerShell 曾经破坏：

- 通过管道传给 Python 的中文源码。
- `python -c $code` 中的字符串双引号。

为避免在 curl 命令中再次处理内嵌 JSON 引号，项目新增：

```text
examples/chat_stream_request.json
```

内容使用 ASCII：

```json
{"message":"Use get_weather for Beijing current weather, then answer in Chinese."}
```

curl 使用：

```powershell
# @文件语法让 curl 直接读取 JSON，PowerShell 不再解析 JSON 内部双引号。
--data-binary '@examples/chat_stream_request.json'
```

### Uvicorn 与真实 DeepSeek 验证

用户在第一个终端启动：

```powershell
# --reload 便于学习阶段修改代码后自动重启服务。
.\.venv\Scripts\python.exe -m uvicorn mini_deer_agent.api:app --reload
```

第二个终端使用：

```powershell
# -N 关闭 curl 输出缓冲，-sS 隐藏进度条但保留错误。
curl.exe -N -sS `
  -X POST http://127.0.0.1:8000/chat/stream `
  -H "Content-Type: application/json" `
  --data-binary '@examples/chat_stream_request.json'
```

真实验证成功观察到：

```text
tool_call_chunk 逐步发送工具名和北京参数
    → tool_result 发送真实 Open-Meteo 结果
    → ai_delta 逐步发送 DeepSeek 中文正文
    → end 明确结束本轮流
```

这次验证经过了完整网络链路：

```text
curl.exe
    → HTTP POST
    → Uvicorn
    → FastAPI 路由
    → Starlette StreamingResponse
    → DeepSeek + ToolNode
    → SSE HTTP body chunks
    → curl.exe -N 实时显示
```

它补充了 TestClient 无法证明的“真实事件到达时机”。

### 与 DeerFlow 源码的对应关系

DeerFlow 路由层同样返回：

```python
# DeerFlow 把异步 sse_consumer 交给 StreamingResponse。
return StreamingResponse(
    sse_consumer(...),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    },
)
```

当前 Mini Deer：

```text
同步 graph.stream()
    → 同步 iter_sse_frames()
    → Starlette 线程池迭代
    → StreamingResponse
```

DeerFlow：

```text
异步 agent.astream()
    → 后台 run task
    → StreamBridge 异步队列
    → sse_consumer()
    → StreamingResponse
```

两者的 HTTP 路由边界和 SSE 响应头一致，但 DeerFlow 把 Agent 生产者与 HTTP 消费者解耦，所以能够处理心跳、重放、多个订阅者以及断开后继续运行。

### 当前功能边界

当前 HTTP 接口仍然无状态：

```text
第一请求
    → build_agent_graph(checkpointer=None)
    → 对话结束后状态只存在于本次返回值

第二请求
    → 新 graph + 空 MessagesState
    → 不知道第一请求内容
```

下一个功能点将让请求携带 `thread_id`，并保证 SQLite saver 的 `with` 生命周期覆盖整个 `StreamingResponse` 迭代，从而实现跨 HTTP 请求记忆。

## 功能点 8.3：HTTP 线程持久化

### 本功能点目标

前一个功能点已经让单次 Agent 执行跨过 HTTP 边界。本功能点继续连接第 6 课的 Checkpointer：

```text
第一次 HTTP 请求结束
    → graph 和 SQLite 连接都销毁
    → checkpoint 留在 data/checkpoints.sqlite

第二次 HTTP 请求到达
    → 创建新连接和新 graph
    → 使用相同 thread_id 恢复第一轮状态
    → 只追加第二轮 HumanMessage
```

### 请求模型加入 `thread_id`

```python
class ChatStreamRequest(BaseModel):
    """校验流式聊天端点接收的本轮消息和线程标识。"""

    # 清理消息首尾空白并拒绝空消息。
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
    ]
    # thread_id 同样拒绝空白，并限制无界主键长度。
    thread_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=128,
        ),
    ]
```

纯空白 `thread_id` 会在响应开始前返回 `422`，不会创建数据库连接或调用模型。

长度限制不是身份认证，只是防止任意大的字符串进入 checkpoint 主键和日志。当前没有限制字符集合，因为 SQLite 使用参数绑定保存 `thread_id`，它不是文件路径或手工拼接的 SQL。

### 流工厂接口增加线程参数

工厂类型从：

```python
# 功能点 8.2 只能接收本轮消息，无法选择 checkpoint 线程。
Callable[[str], Iterator[AgentMessageEvent]]
```

升级为：

```python
# message 是本轮输入，thread_id 是状态分区键。
type AgentMessageStreamFactory = Callable[
    [str, str],
    Iterator[AgentMessageEvent],
]
```

路由把两个经过 Pydantic 清理的字段传给工厂：

```python
# 创建生成器时还没有执行 SQLite 或 DeepSeek 操作。
message_events = stream_factory(
    request.message,
    request.thread_id,
)
```

依赖工厂接口仍然存在，所以测试可以固定临时数据库和假模型，同时让路由真实传入每次 HTTP 请求的消息与线程 ID。

### 默认 checkpoint 数据库

```python
# 从项目根目录启动 Uvicorn 时，数据库位于 data/checkpoints.sqlite。
DEFAULT_CHECKPOINT_DATABASE_PATH = Path("data/checkpoints.sqlite")
```

该路径相对于进程当前工作目录。因此学习命令都要求先进入项目根目录再启动 Uvicorn。

正式数据库及 SQLite sidecar 文件已经被 `.gitignore` 排除：

```text
data/
*.sqlite
*.sqlite-shm
*.sqlite-wal
```

测试不使用这个默认路径，而是通过 `tmp_path` 注入临时数据库，避免污染真实对话状态。

### 有状态消息生成器

```python
def create_agent_message_stream(
    message: str,
    thread_id: str,
    *,
    database_path: str | Path = DEFAULT_CHECKPOINT_DATABASE_PATH,
    model: BaseChatModel | None = None,
) -> Iterator[AgentMessageEvent]:
    """在 SQLite 生命周期内恢复线程并产生真实 Agent 消息流。"""
    # with 在生成器内部，连接覆盖完整 LangGraph 消息迭代。
    with open_sqlite_checkpointer(database_path) as checkpointer:
        # 测试注入假模型；生产请求默认从环境配置创建 DeepSeek。
        graph = build_agent_graph(
            model,
            checkpointer=checkpointer,
        )
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }
        # 旧消息由 checkpoint 恢复，调用方只提交本轮新消息。
        yield from stream_agent_messages(
            graph,
            [HumanMessage(content=message)],
            config,
        )
```

`database_path` 和 `model` 是 keyword-only 参数：

```text
生产调用
    create_agent_message_stream(message, thread_id)
    → 默认 data/checkpoints.sqlite + DeepSeek

测试调用
    partial(
        create_agent_message_stream,
        database_path=tmp_path,
        model=fake_model,
    )
    → 临时 SQLite + 假模型
```

这样生产和测试共用完全相同的状态恢复实现。

### `with` 生命周期为什么必须在生成器内部

错误结构是：

```python
# 错误：此处只创建惰性生成器，没有真正读取 SQLite。
with open_sqlite_checkpointer(path) as checkpointer:
    graph = build_agent_graph(checkpointer=checkpointer)
    events = stream_agent_messages(graph, messages, config)

# StreamingResponse 以后开始迭代时，连接已经关闭。
return StreamingResponse(events)
```

正确实现中的时间线是：

```text
FastAPI 路由调用工厂
    → 只创建 create_agent_message_stream 生成器
    → 返回 StreamingResponse
    → Starlette 开始消费响应体
    → 第一次进入生成器
    → 打开 SQLite
    → 恢复 thread_id 最新 checkpoint
    → 执行完整 LangGraph 消息流
    → 保存本轮最终 checkpoint
    → 内层 Agent 消息流结束
    → 退出 with 并关闭 SQLite
    → 外层 iter_sse_frames 发送 end
```

严格来说，SQLite 上下文覆盖的是完整 Agent/LangGraph 迭代；协议层最后的 `end` 帧在数据库工作完成并关闭连接后发送。这正好保证所有需要数据库的操作都位于有效连接内，同时发送 `end` 不再占用连接。

如果 Agent 迭代抛出异常：

```text
异常离开 yield from
    → context manager 关闭 SQLite
    → 异常传播给 iter_sse_frames
    → 转成 error + end
```

如果 HTTP 客户端断开并导致生成器关闭，退出生成器同样会触发 context manager 清理连接。

### 两次 HTTP 请求如何恢复状态

第一轮请求：

```json
{
  "message": "Remember that my persistence code name is Spruce.",
  "thread_id": "http-memory-demo-v1"
}
```

```text
打开 SQLite
    → 查询 http-memory-demo-v1
    → 线程尚不存在
    → 保存 HumanMessage + AIMessage
    → 关闭连接
```

第二轮是一个新的 HTTP 请求：

```json
{
  "message": "What is my persistence code name? Answer in Chinese.",
  "thread_id": "http-memory-demo-v1"
}
```

```text
重新打开 SQLite
    → 创建新 graph
    → 根据相同 thread_id 恢复第一轮两条消息
    → 追加第二轮 HumanMessage
    → 模型收到三条历史消息
    → 流式生成第二轮 AIMessage
    → 保存四条消息的新 checkpoint
```

HTTP 连接、graph 对象和 SQLite 连接都不需要跨请求常驻。真正跨请求保留的是数据库文件中的 checkpoint。

### SSE 测试为什么需要解析正文事件

持久化测试的假模型也按字符流式返回。例如“已记住。”在原始响应体中是：

```text
event: ai_delta
data: {"content":"已"}

event: ai_delta
data: {"content":"记"}

event: ai_delta
data: {"content":"住"}
```

因此错误断言：

```python
# 原始 body 中每个字符之间存在 SSE 协议字段，完整文本并不连续。
assert "已记住。" in body
```

测试增加 `collect_ai_text()`：

```text
按空行拆分 frame
    → 只选择 event: ai_delta
    → 解析 data JSON
    → 按到达顺序追加 content
    → 得到完整模型回答
```

这与未来浏览器客户端消费 SSE 的基本逻辑一致。

### HTTP + SQLite 集成测试

`tests/test_chat_stream.py` 使用一个临时数据库和同一个流式假模型连续执行：

```text
线程 A 第一轮
    模型收到：
    ["请记住我的代号是云杉。"]

线程 A 第二轮
    模型收到：
    [
        "请记住我的代号是云杉。",
        "已记住。",
        "我的代号是什么？",
    ]

线程 B 第一轮
    模型收到：
    ["线程 B 的第一轮。"]
```

这一个测试同时证明：

- 两次 HTTP 响应分别打开和关闭 SQLite。
- 相同 `thread_id` 可以恢复第一轮完整状态。
- 请求只需提交本轮新消息。
- 不同 `thread_id` 使用独立状态。
- AI 流式 chunk 最终能聚合为 checkpoint 中的 `AIMessage`。
- 测试数据库真实创建在 `tmp_path`，没有写入正式 `data/`。

本功能点完成后的全量回归结果：

```text
39 passed
```

### PowerShell 两轮验证文件

项目增加两个纯 ASCII 请求文件：

```text
examples/chat_memory_round_1.json
examples/chat_memory_round_2.json
```

它们使用相同：

```text
thread_id = http-memory-demo-v1
```

curl 通过 `--data-binary @文件` 直接读取 JSON，避免 PowerShell 重新处理字符串双引号。用户依次完成两个独立 HTTP 请求，并确认第二轮能够回答第一轮设置的 `Spruce` 持久化代号。

天气请求文件 `examples/chat_stream_request.json` 也加入了独立的：

```text
thread_id = weather-http-demo
```

不同演示不会混入同一消息历史。

### `thread_id` 不是安全凭证

当前 SQLite 查询确实使用 `thread_id` 隔离状态，但它只是一项数据分区键：

```text
thread_id 能做的事
    → 选择哪份 checkpoint

thread_id 不能做的事
    → 证明当前调用者是谁
    → 判断调用者是否有权读取该线程
```

当前 `/chat/stream` 没有身份认证和所有权校验。如果直接开放给多个不可信用户，知道或猜到其他人的 `thread_id` 就可能续接其对话。

因此当前接口只适合本地学习。生产系统至少需要：

```text
认证用户
    → 查询 thread 所有者
    → 验证访问权限
    → 再加载 checkpoint
```

此外，同一 `thread_id` 的两个请求如果同时写入，还涉及并发顺序和冲突处理；当前同步 SQLite 学习版本没有把它设计为生产级多用户并发服务。

### 与 DeerFlow 源码的对应关系

DeerFlow 无状态 runs 路由会从请求配置中读取线程 ID；未提供时生成新 ID：

```python
def _resolve_thread_id(body: RunCreateRequest) -> str:
    """从请求读取 thread_id，没有时生成新的线程标识。"""
    thread_id = (
        (body.config or {}).get("configurable") or {}
    ).get("thread_id")
    return resolve_thread_id(thread_id)
```

随后同样构造 checkpoint 配置：

```python
checkpoint_config = {
    "configurable": {
        "thread_id": thread_id,
        "checkpoint_ns": "",
    }
}
```

Mini Deer 当前要求调用方显式传 `thread_id`，结构更直接。DeerFlow 在此基础上还拥有：

- Thread 和 Run 资源模型。
- 用户身份、线程所有权和权限检查。
- 自动线程 ID 与 run ID。
- SQLite/PostgreSQL 等 Checkpointer 配置。
- 后台运行与 SSE 订阅分离。
- 跨 Worker 运行状态和取消语义。

两者最底层的状态定位原则相同：

```text
Checkpointer 决定状态存在哪里
thread_id 决定加载哪一条状态链
```

### 第 8 课小结

完成第 8 课后，已经掌握：

- SSE `event:`、`data:` 和结束空行的协议结构。
- 为什么 JSON 正文换行必须保持在单行 `data:` 中。
- 如何把 `AIMessageChunk` 和 `ToolMessage` 映射为 SSE 事件。
- 为什么同一 AI chunk 的正文和工具调用要分别判断。
- 响应开始后为什么用 `error` 事件而不是修改 HTTP 状态。
- `end` 业务事件与 TCP 连接关闭的区别。
- FastAPI 请求校验如何在模型调用前返回 `422`。
- 如何用依赖覆盖隔离外部模型并测试真实路由。
- `StreamingResponse` 如何在线程池中消费同步生成器。
- `Cache-Control`、`Connection` 和 `X-Accel-Buffering` 的作用。
- 为什么 TestClient 不能替代 `curl.exe -N` 的真实到达时机验证。
- SQLite context manager 如何覆盖完整 LangGraph 流式迭代。
- 如何通过 `thread_id` 跨 HTTP 请求恢复消息历史。
- 为什么 SSE 客户端必须解析并累积 `ai_delta`。
- `thread_id` 为什么不是用户身份或授权凭证。
- Mini Deer 同步 HTTP 流与 DeerFlow 异步 Gateway 架构的对应关系。

下一课将实现最小 Web 聊天页面，在浏览器中提交消息、读取 SSE 响应并逐步渲染 Agent 回答。

# 第 9 课：可演进的 Web Agent 基础架构

第 8 课已经建立了可工作的 Agent HTTP 接口，但当时所有 HTTP、模型、图、工具、SQLite 和 SSE 逻辑仍然平铺在少量模块中。这种结构适合逐项理解基础概念，却不适合继续加入生产 Agent 需要的会话、文件、工具审批、记忆、认证、可观测性和多 Agent 能力。

第 9 课不以当前代码量决定架构，而是先建立长期职责边界。以后增加能力时，应把实现放入已经确定的层级，而不是继续扩大 `api.py`，也不需要等项目变大后再进行全局搬迁。

本课设计文档：

```text
docs/plans/2026-08-25-lesson-09-web-chat-page.md
```

## 功能点 9.1：后端模块化与版本化 Run API

### 本功能点目标

- 把平铺模块迁入长期维护的功能包。
- 建立稳定包级公开入口，调用方不依赖内部文件位置。
- 使用 FastAPI 应用工厂集中注册生命周期和路由。
- 让 SQLite checkpointer 从“每个请求打开一次”升级为“应用生命周期共享”。
- 把 HTTP router 与 Agent run 编排分开。
- 建立 `/api/v1` 正式接口和版本化 SSE 事件 envelope。
- 保留旧 `/health`、`/chat/stream` 的运行兼容性。
- 保证内部异常不会通过 SSE 或日志泄露敏感正文。

### 为什么现在就拆分

旧结构的依赖集中在：

```text
api.py
├── 构建 FastAPI
├── 定义请求模型
├── 打开 SQLite
├── 构建 LangGraph
├── 运行 Agent
└── 编码 SSE
```

继续在这里加入线程列表、取消、身份和文件后，任何修改都可能同时影响 HTTP、数据库和 Agent。新的依赖方向是：

```text
core
  └── 后端配置

llms            tools
  └── 模型工厂    └── 工具实现与注册表
          \      /
           agents
              └── LangGraph 组装

persistence
  └── checkpointer 生命周期

streaming
  ├── LangGraph 原始消息流
  ├── 产品级 RunEvent 投影
  └── SSE wire format

application
  └── 一次 run 的用例编排

server
  ├── app factory / lifespan
  ├── dependencies
  ├── schemas
  └── routers
```

上层可以依赖下层，底层不能反向导入 HTTP。例如：

```text
允许
    server → application → agents

禁止
    agents → FastAPI
    persistence → HTTP router
    application → StreamingResponse
```

因此以后即使增加 CLI、定时任务或即时通信入口，也可以复用 `application` 中的 run 用例。

### 核心模块迁移

旧路径与新路径的对应关系：

| 旧文件 | 新实现 | 包级公开入口 |
| --- | --- | --- |
| `config.py` | `core/config.py` | `mini_deer_agent.core` |
| `models.py` | `llms/factory.py` | `mini_deer_agent.llms` |
| `agent.py` | `agents/main/graph.py` | `mini_deer_agent.agents` |
| `tools.py` | `tools/weather.py`、`tools/registry.py` | `mini_deer_agent.tools` |
| `storage.py` | `persistence/checkpoints.py` | `mini_deer_agent.persistence` |
| `streaming.py` | `streaming/langgraph.py` | `mini_deer_agent.streaming` |
| `sse.py` | `streaming/sse.py` | `mini_deer_agent.streaming` |

新的调用代码优先从包入口导入：

```python
# 调用方只依赖包公开的稳定名称，不依赖 graph.py 的内部位置。
from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.persistence import open_sqlite_checkpointer
from mini_deer_agent.streaming import stream_agent_messages
from mini_deer_agent.tools import get_weather
```

包内 `__init__.py` 使用 `__all__` 明确公开接口：

```python
from mini_deer_agent.agents.main import build_agent_graph, model_node

__all__ = ["build_agent_graph", "model_node"]
```

以后 `agents/main/` 内部可以增加 prompt、state、middleware 等文件，而调用方仍然使用 `mini_deer_agent.agents`。

第 8 课中的旧导入命令记录的是当时的真实源码。第 9 课之后运行示例，应使用上表中的新入口。

### 工具实现与注册表分开

天气实现位于：

```text
tools/weather.py
```

Agent 工具集合位于：

```python
def get_agent_tools() -> tuple[BaseTool, ...]:
    """返回同一轮 Agent 构建使用的不可变工具集合。"""
    # 模型绑定和 ToolNode 必须使用相同集合。
    return (get_weather,)
```

主 Agent 构图时只读取一次注册表：

```python
# 同一个 agent_tools 同时交给模型和执行节点。
agent_tools = get_agent_tools()
tool_model = chat_model.bind_tools(agent_tools)
builder.add_node("tools", ToolNode(agent_tools))
```

这条约束解决一种容易出现的生产错误：

```text
模型绑定工具集合 A
ToolNode 注册工具集合 B
    → 模型请求了 B 中不存在的工具
    → 运行时才失败
```

以后新增工具时，应新增独立实现文件，再在 registry 中按 Agent 能力、配置和权限组装，而不是把所有 HTTP 调用都写进 Agent 图。

### `api.py` 变成稳定 ASGI 入口

现在的 `api.py` 只包含：

```python
"""保留稳定 ASGI 导入路径，具体组装逻辑位于 server 包。"""

from mini_deer_agent.server import app, create_app

__all__ = ["app", "create_app"]
```

因此 Uvicorn 命令保持稳定：

```powershell
python -m uvicorn mini_deer_agent.api:app
```

内部 router、service 或数据库实现移动时，不需要修改部署入口。

### FastAPI 应用工厂

`server/app.py` 的 `create_app()` 只负责应用组合：

```text
创建 FastAPI
    → 安装 lifespan
    → 注册正式 health/run router
    → 注册 legacy health/chat router
    → 返回 application
```

应用工厂接收三类可替换依赖：

```python
def create_app(
    *,
    settings_factory=Settings,
    checkpointer_context_factory=open_async_sqlite_checkpointer,
    run_stream_service_factory=RunStreamService,
) -> FastAPI:
    ...
```

生产环境使用默认工厂；测试可以注入临时配置、假 checkpointer 或假 service。测试不需要 monkeypatch 路由内部函数，也不会访问真实 DeepSeek。

### Lifespan 管理共享资源

旧实现每个 HTTP 请求都执行：

```text
打开 SQLite
    → setup 表
    → 执行一轮 Agent
    → 关闭 SQLite
```

新实现使用 FastAPI lifespan：

```text
应用启动
    → 加载 Settings
    → 打开一个 SQLite saver
    → 创建 RunStreamService
    → 保存到 app.state

处理任意数量请求
    → dependency 从 app.state 取得共享 service

应用关闭
    → 先撤销 run service
    → 再关闭 SQLite
```

`SqliteSaver.from_conn_string()` 使用：

```python
sqlite3.connect(
    conn_string,
    check_same_thread=False,
)
```

其内部 cursor 操作还受 `threading.Lock` 保护。因此 saver 可以在 FastAPI 的工作线程中使用，同一个连接上的 checkpoint 写入会被锁保护。

这并不意味着 SQLite 已经适合无限并发。锁会串行化数据库操作；以后替换 PostgreSQL checkpointer 时，router 和前端契约不需要变化。

### 为什么需要异步 SQLite 上下文

SQLite saver 的 context manager 是同步实现。若直接在 FastAPI 异步 lifespan 中执行：

```python
# setup() 和连接关闭都可能阻塞 ASGI 事件循环。
with open_sqlite_checkpointer(path) as checkpointer:
    yield
```

项目增加 `open_async_sqlite_checkpointer()`：

```text
async lifespan
    → asyncio.to_thread(manager.__enter__)
    → 使用 checkpointer
    → asyncio.to_thread(manager.__exit__)
```

关闭阶段使用 `asyncio.shield()`，确保应用取消期间仍等待连接清理完成，避免遗留未提交事务。

### 存活探针与就绪探针

正式接口提供：

```http
GET /api/v1/health
GET /api/v1/ready
```

两者语义不同：

```text
health
    → HTTP 进程是否还能响应
    → 不访问数据库或模型

ready
    → lifespan 是否已完成
    → RunStreamService 是否已经放入 app.state
    → 未就绪时返回 503
```

部署平台可以用 health 判断是否需要重启进程，用 ready 判断是否应该把新请求发送给当前实例。

### FastAPI 依赖只获取已创建资源

`server/dependencies.py`：

```python
def get_run_stream_service(request: Request) -> RunStreamService:
    service = getattr(request.app.state, "run_stream_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "service_not_ready",
                "message": "Run stream service is not ready",
            },
        )
    return cast(RunStreamService, service)
```

依赖函数不能在缺失时偷偷创建一个临时数据库或 service。资源缺失代表应用未就绪，应明确失败，避免部分请求使用共享状态、部分请求使用临时状态。

### Application service 的职责

`RunStreamService` 保存：

```text
共享 checkpointer
可替换 graph_factory
```

原始消息流：

```python
def stream_messages(self, message: str, thread_id: str):
    # 每轮创建独立 graph，状态由共享 checkpointer 按 thread_id 恢复。
    graph = self._graph_factory(self._checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    yield from stream_agent_messages(
        graph,
        [HumanMessage(content=message)],
        config,
    )
```

正式 run 入口：

```python
def start_run(self, message: str, thread_id: str) -> StartedRun:
    # 在 HTTP 响应头产生前分配 run_id。
    run_id = str(uuid4())
    events = project_run_events(
        self.stream_messages(message, thread_id),
        run_id=run_id,
        thread_id=thread_id,
    )
    return StartedRun(run_id=run_id, events=events)
```

`StartedRun` 把 `run_id` 与惰性事件迭代器放在一起。router 可以先把 `run_id` 写入响应头，同时模型调用仍然等到 `StreamingResponse` 开始消费事件时才发生。

### 正式资源化 API

正式接口是：

```http
POST /api/v1/threads/{thread_id}/runs/stream
```

请求体：

```json
{
  "message": "请查询北京当前天气"
}
```

这里存在三个不同身份：

```text
thread_id
    → 一条长期对话状态链
    → 位于 URL 资源路径

run_id
    → 对话中的一次执行
    → 由服务端生成

message_id
    → 一次 run 内的某条模型或工具消息
    → 由 LangChain/LangGraph 产生
```

旧接口把 `thread_id` 与 `message` 都放在 body 中。正式接口把 thread 作为资源，未来可以自然增加：

```http
GET    /api/v1/threads/{thread_id}
DELETE /api/v1/threads/{thread_id}
POST   /api/v1/threads/{thread_id}/runs/{run_id}/cancel
GET    /api/v1/threads/{thread_id}/runs/{run_id}/events
```

v1 的 `thread_id` 必须是 UUID。`message` 会清理首尾空白、拒绝空字符串，并限制最大长度为 32768；未知请求字段也会被拒绝，防止拼写错误被静默忽略。

### 两层事件模型

内部事件仍是：

```python
# 只在运行层和投影层之间使用。
type AgentMessageEvent = tuple[BaseMessage, dict[str, Any]]
```

它包含 LangChain 消息，不能直接成为长期前端协议。公开事件改为：

```python
@dataclass(frozen=True, slots=True)
class RunEvent:
    event: RunEventName
    run_id: str
    thread_id: str
    sequence: int
    message_id: str | None
    payload: Mapping[str, Any]
    version: str = "1"
```

这样以后 LangChain 调整内部对象字段时，只需要修改 projector；浏览器仍消费稳定的 `RunEvent`。

第一版事件类型：

| 事件 | 作用 |
| --- | --- |
| `run_started` | 建立 run 身份和开始时间 |
| `ai_delta` | 按 message ID 追加模型正文 |
| `tool_call_delta` | 追加工具名和参数片段 |
| `tool_result` | 关联对应工具调用结果 |
| `run_error` | 以稳定 code 表示失败 |
| `run_completed` | 表示本轮正常完成 |

### `sequence` 和 SSE `id`

每条事件包含从 1 开始连续递增的 `sequence`：

```text
run_started          sequence=1
tool_call_delta      sequence=2
tool_call_delta      sequence=3
tool_result          sequence=4
ai_delta             sequence=5
run_completed        sequence=6
```

SSE ID 为：

```python
event_id = f"{run_id}:{sequence}"
```

实际帧：

```text
id: <run_id>:<sequence>
event: ai_delta
data: {"version":"1","run_id":"...","thread_id":"...","sequence":5,"message_id":"...","payload":{"text":"北京"}}
```

当前尚未实现事件存储和 `Last-Event-ID` 重放，但现在就建立稳定 ID 和序号，以后加入重连时不用推翻前端消息模型。

### 工具调用分片如何保持关联

真实 DeepSeek 工具参数会像之前观察到的那样分片：

```text
第一块
    name=get_weather
    id=call_xxx
    args=""

后续块
    name=None
    id=None
    args="{"

后续块
    name=None
    id=None
    args="city"
```

projector 不能把每一块当成新工具调用。它按：

```text
(message_id, chunk.index)
```

保存工具状态，并复用第一次看到的：

```text
logical tool_call_id
tool name
```

工具结果到达时，再把 provider 的 `tool_call_id` 映射回同一个逻辑 ID。前端因此可以一直更新同一张工具卡片，而不是为每个 JSON 字符创建一张卡片。

### 正常完成与失败完成

旧协议无论成功还是失败都会发送：

```text
end
```

客户端还要结合前一条事件猜测结果。v1 明确区分：

```text
正常
    → run_completed

失败
    → run_error
    → 不再发送 run_completed
```

`run_error.payload` 使用稳定字段：

```json
{
  "code": "agent_execution_failed",
  "message": "Agent execution failed",
  "retryable": true
}
```

内部异常正文、堆栈和密钥不会进入公开事件。

### 日志也不能泄露异常正文

仅仅保护 HTTP 响应还不够。原来的 `logger.exception()` 会把异常字符串写入日志；第三方 SDK 的异常可能包含请求片段或密钥。

在统一脱敏日志系统尚未实现前，当前只记录：

```text
run_id
异常类型，例如 RuntimeError
```

不记录异常正文。以后加入统一敏感字段过滤后，再恢复经过脱敏的堆栈追踪。

### 旧接口兼容策略

迁移期间仍然支持：

```http
GET  /health
POST /chat/stream
```

旧接口保持：

- 原请求体中的 `message + thread_id`。
- 原 `ai_delta/tool_call_chunk/tool_result/error/end` 事件。
- 原 SSE 字节格式。
- 原代理响应头。

但兼容路由使用 `include_in_schema=False`，不会出现在 OpenAPI 中。新客户端只会看到：

```text
/api/v1/health
/api/v1/ready
/api/v1/threads/{thread_id}/runs/stream
```

这是生产迁移常用策略：运行兼容与文档引导分开，先让调用方迁移，再在明确的大版本中删除旧入口。

### 自动化测试结构

HTTP 测试迁入：

```text
tests/server/test_app.py
tests/server/test_runs.py
```

测试保护的架构约束包括：

- `api:app` 仍然可导入。
- health 不依赖 lifespan，ready 必须依赖 lifespan。
- checkpointer 每次应用启动只打开一次，关闭只执行一次。
- router 使用 lifespan 创建的同一个 service。
- OpenAPI 只公开 `/api/v1`。
- 旧接口请求与 SSE 字节保持兼容。
- v1 返回 `X-Run-ID`、SSE ID 和统一 envelope。
- 空消息、非法 UUID 和未知字段在 service 前返回 `422`。
- 真实 SQLite saver 可以跨多个 HTTP 请求恢复同一线程并隔离其他线程。
- 工具参数分片保持同一 `tool_call_id`。
- 失败只产生 `run_error`，SSE 和日志都不包含测试密钥。

完整测试结果：

```text
44 passed
```

### 真实运行验证

正式请求示例：

```text
examples/chat_run_v1_request.json
```

用户实际启动 Uvicorn，确认：

- `/api/v1/ready` 返回 `ready`。
- 响应头包含 `X-Run-ID`。
- 第一条事件是 `run_started`。
- 天气调用产生若干 `tool_call_delta`。
- Open-Meteo 结果产生 `tool_result`。
- DeepSeek 最终回答逐步产生 `ai_delta`。
- 最后一条事件是 `run_completed`。
- 所有 `sequence` 连续递增。

验证时 Windows 的 `8000` 出现残留监听，因此改用空闲的 `8001`：

```powershell
python -m uvicorn mini_deer_agent.api:app --host 127.0.0.1 --port 8001
```

端口是运行参数，不属于应用协议。更换端口不需要修改项目源码。

### 与 DeerFlow 源码的对应关系

DeerFlow 使用 `app/gateway/app.py`：

```text
lifespan()
    → 创建和关闭长期资源

create_app()
    → 创建 FastAPI
    → 注册中间件
    → include_router(...)
```

DeerFlow 的 `app/gateway/deps.py` 使用 `_require()` 从 `app.state` 取得 checkpointer、run manager 等资源，缺失时返回 `503`。Mini Deer 的 `get_run_stream_service()` 使用相同原则。

DeerFlow 的 `app/gateway/routers/thread_runs.py` 使用：

```text
/api/threads/{thread_id}/runs/...
```

表达 thread 与 run 的资源关系。Mini Deer 的：

```text
/api/v1/threads/{thread_id}/runs/stream
```

采用相同资源语义，并额外明确当前协议版本。

DeerFlow 已经拥有 RunManager、事件存储、取消、重连、认证、跨 Worker 和更多事件类型。Mini Deer 当前并未假装已经实现这些能力，但通过 `run_id`、`sequence`、application service 和 router 边界为它们保留了正确位置。

### 功能点 9.1 小结

完成该功能点后，已经掌握：

- 为什么项目规模小也应该先固定长期职责边界。
- 包级公开入口与内部实现文件的区别。
- 为什么工具实现和工具注册表应该分开。
- 为什么模型绑定和 ToolNode 必须复用同一工具集合。
- `api.py` 为什么只保留稳定 ASGI 入口。
- FastAPI 应用工厂如何支持生产组装和测试注入。
- lifespan 如何创建并关闭共享 checkpointer。
- 为什么同步 SQLite 上下文要在线程池中进入和退出。
- health 与 ready 两种探针的语义差异。
- 为什么依赖缺失应返回 `503`，不能临时创建资源。
- application service 如何与 FastAPI 解耦。
- `thread_id`、`run_id`、`message_id` 的不同职责。
- 为什么内部 LangChain 消息不能直接作为长期前端协议。
- `RunEvent` 的 version、sequence 和 event ID 如何支持未来演进。
- 如何关联 DeepSeek 分片工具参数与最终工具结果。
- 为什么成功和失败需要不同终止事件。
- 为什么响应脱敏和日志脱敏必须同时考虑。
- 如何在保留旧接口运行兼容的同时引导新客户端使用 v1。
- Mini Deer 的 app factory、lifespan、dependency 和 run router 与 DeerFlow 的对应关系。

下一功能点将建立独立 React + TypeScript 前端工程和可识别的聊天页面骨架。页面只验证结构、视觉方向和响应式布局，暂时不连接真实 SSE。

## 功能点 9.2：前端工程与可识别聊天页面

本功能点已经由用户在浏览器中完成实际验证。目标不是先做一个能够“假装聊天”的页面，而是建立未来生产级 Agent 前端可以持续扩展的工程边界，并用静态数据验证页面结构、视觉方向、响应式行为和可访问语义。

本阶段明确不做两件事：

- 不调用真实后端，避免 UI、SSE parser、run 状态机同时出现问题时难以定位。
- 不伪造已经可用的会话管理能力；新会话、输入和发送按钮在接入对应功能前保持禁用或只读。

#### 独立前端工程

项目新增独立目录：

```text
frontend/
├── package.json
├── pnpm-lock.yaml
├── vite.config.ts
├── eslint.config.js
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── index.html
├── src/
│   ├── app/
│   ├── entities/message/
│   ├── features/chat/
│   └── shared/ui/
└── tests/
```

前后端独立的含义是：

```text
Python / FastAPI
    → 负责 Agent、模型、工具、持久化、权限和 API

React / TypeScript
    → 负责浏览器状态、交互和展示

HTTP + SSE 契约
    → 两者之间唯一允许长期依赖的边界
```

前端不能直接导入 Python 类型，也不能理解 LangChain 的 `AIMessage`、`ToolMessage` 或 SQLite checkpoint。后端以后更换模型、图结构或数据库，只要公开协议保持兼容，页面就不需要跟着重写。

#### 为什么保留完整的工程质量入口

`frontend/package.json` 从一开始就提供：

```text
dev        → 本地开发服务器
build      → TypeScript 项目构建 + Vite 生产构建
typecheck  → 独立严格类型检查
lint       → ESLint 静态规则
format     → Prettier 格式检查
test       → Vitest 一次性测试
test:watch → 学习和开发阶段的持续测试
```

项目现在很小，但这些命令不是为了增加仪式感。以后每加入 SSE parser、reducer、线程仓储、工具审批或文件上传，都需要复用同一质量入口。若等项目变大后再补，旧代码往往会一次暴露大量类型和规则问题。

依赖使用精确版本并提交 `pnpm-lock.yaml`，使不同机器和后续课程安装到相同依赖图。`engines.node` 同时声明最低 Node 版本，避免包能够安装但构建工具运行失败。

#### Vite 开发代理与密钥边界

`vite.config.ts` 预留了开发期同源代理：

```text
浏览器请求 /api/...
    → Vite 127.0.0.1:5173
    → 代理到 MINI_DEER_BACKEND_ORIGIN
    → FastAPI
```

默认后端地址是：

```text
http://127.0.0.1:8000
```

如果本地端口被占用，可以在 `frontend/.env` 中配置：

```text
MINI_DEER_BACKEND_ORIGIN=http://127.0.0.1:8001
```

这个变量只给 Vite 的本地代理进程读取。代码刻意没有使用 `VITE_` 前缀，因为带该前缀的变量会被打入浏览器构建产物。

重要安全边界：

```text
可以放入前端或代理配置
    → 后端公开 origin、无敏感功能开关

绝不能放入前端构建变量
    → DeepSeek API Key、数据库口令、服务端访问令牌
```

浏览器以后只调用 Mini Deer 后端；DeepSeek 密钥始终停留在 Python 服务端。

#### 从领域类型开始，而不是从 JSX 字符串开始

`entities/message/model/types.ts` 定义两类时间线项目：

```typescript
type ChatTimelineItem = MessageTimelineItem | ToolTimelineItem;
```

两者用 `kind` 形成判别联合：

```text
kind = message
    → id、role、content

kind = tool
    → id、toolCallId、name、input、result、status
```

`MessageList` 可以先检查：

```typescript
if (item.kind === "tool")
```

TypeScript 随后会自动把 `item` 缩窄为 `ToolTimelineItem`。这比给一个对象塞入大量可选字段更安全：工具卡一定有 `toolCallId`，普通消息一定有 `role`。

当前工具状态只有：

```typescript
status: "completed"
```

这是刻意反映当前静态页面真正实现的能力。下一功能点接入流式状态机时，再根据真实事件扩展为请求中、已完成和失败状态，而不是提前声称不存在的行为。

#### 页面组合关系

当前组件树是：

```text
App
└── ChatPage
    ├── ConversationRail
    └── workspace
        ├── ThreadHeader
        │   └── StatusIndicator
        ├── MessageList
        │   ├── 普通消息 article
        │   └── ToolActivity
        └── Composer
```

每层职责如下：

- `App`：应用组合入口，不放聊天业务逻辑。
- `ChatPage`：组合聊天工作区，并在本功能点提供经过明确标注的预览数据。
- `ConversationRail`：未来线程列表的稳定容器，当前不读取或伪造后端历史。
- `ThreadHeader`：显示当前线程标题、连接阶段和线程 ID 位置。
- `MessageList`：只按有序时间线渲染，不发请求、不持有 run 状态。
- `ToolActivity`：通过 `toolCallId` 表达工具请求和结果的关联。
- `Composer`：输入表单边界；当前阻止提交并保持控件不可用。
- `StatusIndicator`：无聊天业务语义的共享展示原件。

这个拆分不是“一组件一个文件”的形式主义。未来真实数据接入后：

```text
useChatRun / reducer
    → 生成 ChatTimelineItem[] 和运行状态
    → ChatPage 把 props 传给展示组件
    → 展示组件仍然不需要知道 fetch、SSE 或 AbortController
```

因此协议解析、状态迁移和 UI 渲染可以分别测试。

#### 为什么静态预览必须明确标注

`ChatPage` 使用 `PREVIEW_TIMELINE` 展示：

1. Agent 欢迎消息。
2. 用户天气问题。
3. `get_weather` 工具活动。
4. Agent 最终回答位置。

但页面同时显示：

```text
页面骨架预览 · 下一功能点连接真实 Agent SSE
```

`Composer` 还使用：

```text
textarea readOnly
button disabled
onSubmit → preventDefault()
```

原因是产品界面不能让用户误以为按钮已经连接后端。即使当前按钮因为某次 CSS 或属性修改变得可点击，`preventDefault()` 仍能避免表单导航；自动化测试则保护只读与禁用状态。

#### 可访问语义

页面不只依靠颜色和 class 表达结构，还使用语义化元素和 ARIA：

```text
aside aria-label="会话导航"
nav aria-label="最近会话"
main
header
ol role="log" aria-live="polite"
article aria-label="Mini Deer的消息"
article role="status" aria-label="工具 ..."
form aria-label="发送消息"
label htmlFor="chat-message"
```

其中消息列表使用：

```text
role="log"
aria-live="polite"
```

下一功能点追加模型增量时，辅助技术可以把它识别为持续更新的消息区域，同时不会像强制警报那样频繁打断用户。

工具 ID 显示在工具卡片中，但它不是人类标题。代码注释明确它是：

```text
工具调用请求 ↔ 工具结果
```

之间的关联键。后续 reducer 不能只依靠工具名称关联，因为同一次 run 可能并行或连续调用两次同名工具。

#### 响应式布局

桌面布局使用：

```css
.app-shell {
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr);
}
```

`minmax(0, 1fr)` 很重要：Grid 子项默认最小宽度可能由长内容撑开，显式允许收缩才能避免工具参数或长文本制造横向滚动。

工作区使用三行结构：

```text
顶部 thread header
中部可滚动 chat stage
底部 composer
```

```css
grid-template-rows: auto minmax(0, 1fr) auto;
```

只有中部消息区滚动，标题和输入区保持在可见区域。

在 `800px` 以下：

- 双列页面变为上下布局。
- 左侧会话栏收缩为顶部品牌栏。
- 尚不可用的最近会话与环境说明隐藏。
- workspace 高度扣除顶部栏。

在 `520px` 以下继续收紧头像、消息间距、工具详情和发送区，使 320px 最小宽度仍保持可读。样式还响应 `prefers-reduced-motion`，为未来动画统一保留无障碍降级入口。

#### 设计变量与未来主题

颜色、边框、阴影和语义色集中为 CSS 自定义属性：

```text
--forest-*  → 品牌与主操作
--paper     → 工作区表面
--canvas    → 页面背景
--ink       → 正文
--muted     → 次要信息
--tool      → 工具活动语义
--danger    → 错误语义预留
```

组件只引用语义变量。以后增加暗色主题或品牌主题时，可以替换 token，而不用逐个修改聊天组件。

#### ESLint 的类型感知配置边界

TypeScript ESLint 的 `recommendedTypeChecked` 需要类型信息。最初若把它无条件应用到：

```text
eslint.config.js
```

ESLint 会尝试从 TypeScript 项目服务读取这个 JavaScript 配置文件，但它不属于 `tsconfig`，因此报错。

当前做法是把类型感知规则映射到：

```text
**/*.ts
**/*.tsx
```

普通 JavaScript 使用自己的推荐规则，配置文件本身从项目 lint 输入中排除。这里体现一个通用原则：规则能力越强，适用文件边界越要准确，不能为了“严格”把错误的解析环境套到所有文件。

#### 测试隔离问题

页面测试使用 Vitest、jsdom 和 Testing Library，验证两类约束：

1. 聊天标题、消息 log、天气工具卡等关键产品表面存在。
2. 静态阶段输入框只读、发送按钮禁用，而且页面明确说明没有发送网络请求。

测试曾出现一个很有学习价值的问题：第二个测试查询输入框时，辅助名称变成两份“向 Agent 提问”。根因不是页面渲染两次，而是：

```text
Vitest 未启用 globals
    → Testing Library 无法自动找到全局 afterEach
    → 第一个测试挂载的 DOM 没有清理
    → 第二个测试再次 render
    → 页面出现重复 id 和重复 label
```

最终在 `tests/setup.ts` 中显式注册：

```typescript
afterEach(() => {
  cleanup();
});
```

这比依赖测试框架的隐式全局更明确，也保证测试相互隔离。测试失败在这里帮助发现的是测试基础设施配置问题，而不是通过放宽查询条件掩盖重复 DOM。

#### 自动化验证结果

本功能点完整执行：

```text
pnpm build      → 通过
pnpm typecheck  → 通过
pnpm lint       → 通过
pnpm test       → 1 个测试文件、2 个测试通过
pnpm format     → 通过
git diff --check → 通过
```

生产构建成功生成 `frontend/dist`，但构建产物和 `node_modules` 已加入 `.gitignore`，源码仓库只保留可重复生成它们所需的源码与 lockfile。

开发服务器启动于：

```text
http://127.0.0.1:5173/
```

轻量 HTTP 检查返回 `200 OK`。用户随后在真实浏览器中确认页面正常并继续课程，完成本原子功能点的最终验收。

#### 与 DeerFlow 前端源码的对应关系

DeerFlow 的 `frontend/src/components/workspace/chats/chat-page.tsx` 是工作台聊天页面的组合层，负责把线程聊天状态交给消息区、输入区和其他工作台组件。Mini Deer 的 `ChatPage.tsx` 目前承担相同的“组合而非底层协议解析”职责，但只注入静态预览数据。

DeerFlow 的 `frontend/src/components/workspace/chats/use-thread-chat.ts` 把聊天页面使用的 thread、run 和 stream 行为组织成 hook。Mini Deer 没有把请求先塞进组件，而是在目录中为下一步保留：

```text
features/chat/api
features/chat/model
shared/api
```

DeerFlow 的消息展示结构能够承载普通消息、工具、任务和其他事件。Mini Deer 先用 `ChatTimelineItem` 判别联合建立最小领域模型，后续会由 reducer 把公开 SSE 事件投影为同一个时间线，而不会让 `MessageList` 直接读取网络 frame。

两者的共同原则是：

```text
页面组件
    ≠ 网络客户端
    ≠ SSE parser
    ≠ run 状态机
```

Mini Deer 当前规模较小，但已经把这些职责放入未来应存在的位置，不需要在接入真实流以后把一个巨大组件重新拆开。

### 功能点 9.2 小结

完成该功能点后，已经掌握：

- 为什么生产级 Agent 前端应该与 Python 后端独立构建。
- 为什么浏览器只能依赖 HTTP/SSE 契约，不能依赖 LangChain 或数据库内部对象。
- 为什么小项目也要从第一天保留 build、typecheck、lint、format 和 test 入口。
- Vite 开发代理如何保持浏览器同源请求。
- 为什么 DeepSeek API Key 绝不能放进 Vite 环境变量。
- 判别联合如何安全表达消息和工具活动。
- `toolCallId` 为什么是工具请求与结果的关联键。
- ChatPage、MessageList、ToolActivity、Composer 的职责边界。
- 为什么未完成的交互必须明确禁用，不能伪装成可用功能。
- `role="log"`、`aria-live`、label 和语义元素如何建立可访问结构。
- Grid 中 `minmax(0, 1fr)` 和三行 workspace 如何控制滚动与收缩。
- 响应式断点如何在不创建另一套页面的情况下重组工作台。
- CSS 设计变量如何为未来主题保留稳定入口。
- 类型感知 ESLint 规则为什么必须限制到正确文件集合。
- 为什么测试用例之间必须显式清理 DOM。
- Mini Deer 的静态组合层与 DeerFlow `chat-page + use-thread-chat` 分层如何对应。

下一功能点将实现类型化流式客户端。重点不是调用一次 `fetch()`，而是把网络字节流安全地转换为 SSE frame，再校验为公开 `RunEvent`，最后通过 reducer 合并为页面时间线和明确的 run 状态。

## 功能点 9.3：与聊天业务无关的增量 SSE parser

本原子功能点已经由用户通过定向测试确认。它只完成：

```text
ReadableStream<Uint8Array>
    → UTF-8 增量解码
    → SSE 行与 frame 解析
    → SseFrame
```

它还不知道 `run_started`、`ai_delta`、工具调用或 React。把传输格式与聊天协议分开后，parser 可以复用于未来日志流、任务进度流或其他 SSE 接口。

#### 两层解析入口

`shared/api/sse-parser.ts` 提供两个层次：

```text
IncrementalSseParser
    → 输入已经正确解码的 string chunk
    → 输出刚闭合的 SseFrame[]

parseSseStream
    → 输入浏览器 ReadableStream<Uint8Array>
    → 使用 TextDecoder
    → 通过 AsyncGenerator<SseFrame> 逐帧产出
```

测试可以直接构造字节流；未来聊天 API client 可以直接把 `response.body` 交给 `parseSseStream()`。React 组件不接触 reader、decoder 或文本 buffer。

#### 网络 chunk、字符和 frame 是三种边界

网络可能这样分片：

```text
chunk 1: event: ai_del
chunk 2: ta\ndata: {"text":"北
chunk 3: 京"}\n\n
```

不能对每个 chunk 分别调用普通字符串转换，因为中文 UTF-8 字符由多个字节组成，分片可能恰好发生在字符中间。

实现使用：

```typescript
decoder.decode(value, { stream: true })
```

`stream: true` 会把未完成的多字节字符留在 decoder 内部，等待下一块补齐。网络结束后再调用一次无输入 `decode()`，完成解码器刷新。

同时必须保留文本尾部：一个网络 chunk 可能只包含半条 SSE 行或半个 frame；一个 chunk 也可能包含两个完整 frame 加第三个 frame 的开头。因此 parser 每次只交付由空行明确闭合的 frame。

#### SSE 行结束符

实现同时接受：

```text
LF      \n
CRLF    \r\n
CR      \r
```

尤其要处理：

```text
chunk 1 以 \r 结尾
chunk 2 以 \n 开头
```

非最终状态下，`extractLine()` 不会立即消费 buffer 末尾的 `\r`，因为它还无法判断下一块是否以 `\n` 开头。下一块抵达后，二者作为一个 CRLF 消费，避免产生一条虚假的空行并提前结束 frame。

#### SSE 字段处理

parser 识别：

| 字段 | 行为 |
| --- | --- |
| `event` | 设置事件名；缺失时使用标准默认值 `message` |
| `data` | 支持多行，交付时使用 `\n` 连接 |
| `id` | 保存当前 frame ID；包含 NUL 时忽略 |
| `retry` | 只有非负十进制安全整数才接受 |
| `:` 开头 | 作为注释或心跳忽略 |
| 未知字段 | 为协议向前兼容而忽略 |

冒号后的处理也有明确规则：

```text
data: value
```

只移除冒号后的第一个可选空格；后续空格属于真正字段值。

纯注释、空行或只有 `event/id/retry` 而没有 `data` 的块不会产生业务 frame。这样服务端心跳不会进入聊天 reducer。

#### 为什么结束时拒绝未闭合 frame

Mini Deer 后端总是使用：

```text
id: ...
event: ...
data: ...

```

最后的空行是协议边界。如果网络结束时仍存在已经识别的字段但没有空行，parser 抛出：

```text
SseParseError(code="truncated_frame")
```

不能把它当成完整事件，因为截断位置可能位于 JSON、工具结果或模型正文中。静默交付会使前端产生看似成功但内容不完整的状态。

#### 资源上限

生产客户端不能无限相信服务端。parser 设置默认上限：

```text
单行最大字符数   1 MiB 对应的字符计数
单事件 data 上限 4 MiB 对应的字符计数
```

这里使用“字符数”而不是声称精确字节数，因为大小限制发生在 UTF-8 已解码之后。

限制覆盖两类风险：

- 一直不发送换行，使未闭合 line buffer 无限增长。
- 连续发送大量 `data:` 行，使一个未结束事件无限增长。

上限可以通过 `SseParserOptions` 调整，但必须是大于 0 的安全整数。

#### 错误类型

parser 使用稳定错误码：

```text
invalid_limit
invalid_utf8
line_too_large
event_too_large
truncated_frame
parser_closed
```

错误信息不包含原始响应正文，避免未来服务端错误 payload 中的用户内容或敏感字段被复制到不受控日志。

#### 提前退出与底层连接

`parseSseStream()` 是异步生成器。消费方可能因为协议错误、组件卸载或用户停止而提前结束迭代。

`finally` 中会：

```text
未正常读到 EOF
    → reader.cancel()

所有情况
    → reader.releaseLock()
```

这可以避免调用方已经不再消费事件，但 HTTP 流仍持续占用连接和浏览器资源。真正的用户取消还会在 API client 层结合 `AbortController`，两者职责不同。

#### 自动化测试覆盖

`tests/sse-parser.test.ts` 使用真实 `TextEncoder` 和 `ReadableStream` 构造以下情况：

1. 一个 frame 横跨两个网络 chunk。
2. 一个 chunk 中包含两个 frame。
3. CRLF、注释、多行 data、默认事件名和 retry。
4. CRLF 自身横跨两个 chunk。
5. 在一个中文字符的三个 UTF-8 字节内部切开。
6. 网络结束时 frame 没有空行。
7. 未闭合单行超过配置上限。

验证结果：

```text
parser 定向测试：7 passed
前端全部测试：9 passed
typecheck：通过
lint：通过
build：通过
format：通过
git diff --check：通过
```

### 功能点 9.3 小结

完成该功能点后，已经掌握：

- 为什么网络 chunk、UTF-8 字符和 SSE frame 是三个独立边界。
- `TextDecoder(..., { stream: true })` 如何保护跨 chunk 中文。
- 为什么必须保留未完成的文本尾部。
- 如何兼容 LF、CRLF、CR 以及跨 chunk 的 CRLF。
- SSE 注释、event、data、id、retry 和未知字段的处理规则。
- 为什么多行 `data` 要用换行重新连接。
- 为什么没有 `data` 的心跳不应进入业务状态。
- 为什么响应结束时不能交付未由空行闭合的 frame。
- 为什么 parser 需要单行和单事件资源上限。
- 为什么异步生成器提前退出时要取消 reader 并释放锁。
- 为什么传输 parser 必须放在 `shared/api`，不能依赖聊天或 React。

下一小步只处理：

```text
SseFrame.data
    → JSON.parse 得到 unknown
    → 运行时校验 version、ID、sequence 和事件 payload
    → 可信的 ChatRunEvent 判别联合
```

reducer 仍然不会在该小步中实现，避免把协议校验错误与状态合并错误混在一起。

## 功能点 9.4：把不可信 SSE JSON 校验为 ChatRunEvent

本原子功能点已经由用户通过定向测试确认。输入是 parser 产生的：

```typescript
interface SseFrame {
  event: string;
  data: string;
  id?: string;
  retry?: number;
}
```

此时只知道 frame 符合 SSE 文本结构，不能认为 `data` 中的 JSON 符合 Mini Deer 协议。

#### TypeScript 类型不会验证网络数据

下面的代码虽然能通过编译，但没有任何运行时保护：

```typescript
const event = JSON.parse(frame.data) as ChatRunEvent;
```

`as ChatRunEvent` 只是在告诉编译器“相信我”，不会检查：

- JSON 是否能解析。
- `version` 是否受支持。
- `run_id` 和 `thread_id` 是否为 UUID。
- `sequence` 是否为正整数。
- `payload` 是否与事件类型匹配。
- `retryable` 是否真的是 boolean。

生产边界应使用：

```text
JSON.parse()
    → unknown
    → 显式运行时校验
    → ChatRunEvent
```

只有校验器返回之后，reducer 才能信任字段类型。

#### wire 类型与前端领域类型

后端 wire format 使用 Python/API 常见的 snake_case：

```text
run_id
thread_id
message_id
tool_call_id
arguments_delta
finish_reason
```

校验器在边界一次性规范化为前端 camelCase：

```text
runId
threadId
messageId
toolCallId
argumentsDelta
finishReason
```

因此 reducer 和组件不会到处混用两种命名，也不会重复访问不可信的 `Record<string, unknown>`。

#### 判别联合

`ChatRunEvent` 由六种事件组成：

```text
RunStartedEvent
AiDeltaEvent
ToolCallDeltaEvent
ToolResultEvent
RunErrorEvent
RunCompletedEvent
```

每个事件都包含相同 envelope：

```text
event
eventId
version
runId
threadId
sequence
messageId
payload
```

但 `payload` 由 `event` 决定。reducer 以后执行：

```typescript
switch (event.event) {
  case "ai_delta":
    event.payload.text;
}
```

TypeScript 会自动把 payload 缩窄为 `AiDeltaPayload`，不需要可选链或类型断言。

#### envelope 校验

`decodeChatRunEvent()` 会检查：

```text
frame.event
    → 必须是六种已知事件之一

frame.id
    → v1 必须存在

data.version
    → 必须严格等于 "1"

run_id / thread_id
    → 必须符合规范 UUID 形式

sequence
    → 必须是从 1 开始的安全整数

message_id
    → 必须是 null 或非空字符串

payload
    → 必须是 JSON object
```

它还会验证：

```text
frame.id === `${run_id}:${sequence}`
```

这防止 SSE 字段和 JSON envelope 对同一个事件给出两套互相矛盾的身份。真正的重复、缺口和乱序仍由有状态 reducer 处理。

#### 事件 payload 校验

| 事件 | 必需字段 |
| --- | --- |
| `run_started` | `created_at` 为有效日期时间 |
| `ai_delta` | `text` 为非空字符串 |
| `tool_call_delta` | `tool_call_id`、可空 `name`、字符串 `arguments_delta`、非负 `index` |
| `tool_result` | `tool_call_id`、可空 `name`、字符串 `content` |
| `run_error` | 非空 `code`、非空 `message`、boolean `retryable` |
| `run_completed` | 非空 `finish_reason` |

工具调用第一块可能只有工具身份，参数正文为空，所以 `arguments_delta` 允许空字符串。工具本身也可能合法返回空正文，所以 `content` 允许空字符串。

`run_started`、`run_error` 和 `run_completed` 不是某一条 LangChain 消息的增量，因此要求 `message_id` 为 `null`。

#### 严格核心、宽容扩展

校验器严格验证已知必需字段，但忽略 envelope 和 payload 中未知的附加字段。

原因是：

```text
字段缺失或类型错误
    → 当前客户端无法正确解释，必须拒绝

服务端增加客户端暂时不使用的新字段
    → 不应破坏同一 v1 的旧客户端
```

新增事件名或改变现有字段语义则不是普通附加字段，必须通过新客户端支持或协议版本演进处理。

#### 脱敏错误

错误使用稳定 code：

```text
invalid_json
unknown_event
unsupported_version
invalid_envelope
event_id_mismatch
invalid_payload
```

错误只说明哪个字段或哪类契约失败，不复制：

- 原始 SSE data。
- JSON parser 的详细异常正文。
- 模型回答。
- 工具结果。
- 可能出现在 payload 中的密钥或用户敏感内容。

这使后续 hook 可以安全地把协议错误展示给用户或写入经过控制的前端日志。

#### 自动化测试覆盖

`tests/events.test.ts` 覆盖：

1. `run_started` envelope 校验与 camelCase 规范化。
2. 模型、工具、失败和完成事件 payload。
3. 非法 JSON 以及错误脱敏。
4. 未知事件名和不支持的版本。
5. SSE ID 与 run/sequence 不一致。
6. 非法 sequence、UUID 和终止事件 message ID。
7. payload 字段类型错误及敏感正文不进入错误。
8. 未知附加字段的向前兼容。

验证结果：

```text
校验器定向测试：8 passed
前端全部测试：17 passed
typecheck、lint、build、format、git diff --check：全部通过
```

### 功能点 9.4 小结

完成该功能点后，已经掌握：

- 为什么 `as SomeType` 不能验证网络响应。
- 为什么 `JSON.parse()` 的结果必须先视为 `unknown`。
- wire snake_case 与前端 camelCase 应该在哪里转换。
- 判别联合如何让事件名决定 payload 类型。
- SSE ID 为什么要与 `run_id + sequence` 相互校验。
- 哪些字段需要严格拒绝，哪些未知附加字段可以忽略。
- 为什么工具名可以暂时为 null、工具参数增量可以为空。
- 为什么终止事件不能携带 message ID。
- 为什么协议错误不能复制原始模型、工具或密钥内容。
- 无状态校验器与下一步有状态 reducer 的职责差异。

下一小步将让 reducer 消费可信 `ChatRunEvent`，用 `sequence` 检测重复和缺口，用 `messageId` 累积模型正文，用 `toolCallId` 合并工具参数与结果，并显式维护 connecting、streaming、completed、failed 和 cancelled 状态。

## 功能点 9.5：Chat run 纯状态机与时间线合并

本原子功能点已经由用户通过定向测试和静态页面确认。reducer 不读取网络、不调用 React hook，也不访问浏览器存储。它只执行：

```text
ChatRunState + ChatRunAction
    → 新的 ChatRunState
```

因此同一组输入一定产生同一结果，测试不需要启动后端或浏览器。

#### 为什么用 reducer 而不是多个 useState

流式 run 的字段存在强关联：

```text
phase
runId
lastSequence
timeline
pending tools
error
finishReason
```

如果把它们拆成多个独立 `setState()`，一次事件可能只更新部分字段，产生不可能状态，例如：

```text
phase = completed
但仍有 pending 工具

phase = streaming
但 runId = null

lastSequence 已前进
但正文没有追加
```

reducer 在一次纯函数调用中返回完整新状态，使一次事件的所有变化原子完成。

#### 状态阶段

```text
idle
  └── run/requested → connecting
                          └── run_started → streaming
                                                  ├── run_completed → completed
                                                  ├── run_error → failed
                                                  ├── client failure → failed
                                                  └── cancel → cancelled
```

各阶段含义：

- `idle`：当前没有请求。
- `connecting`：本地用户消息已经加入时间线，等待服务端第一条 `run_started`。
- `streaming`：已经确认服务端 run 身份，正在接收模型或工具事件。
- `completed`：收到正常终止事件。
- `failed`：服务端、客户端或协议失败。
- `cancelled`：用户或组件生命周期取消读取。

终止状态不会自动改回 `idle`。下一次 `run/requested` 会开始新一轮并清理上一轮 run 字段，同时按线程决定是否保留历史时间线。

#### action 边界

reducer 接收：

```text
run/requested
run/event-received
run/client-failed
run/cancelled
thread/reset
```

`run/requested` 立即加入用户消息，这是乐观 UI 的最小形式。后端副本以后通过线程历史处理；当前不能等到模型第一块到达后才显示用户刚刚发送的内容。

活跃 run 中的重复提交保持幂等并返回原 state。真正的并发请求阻止会由 hook 的 in-flight guard 负责；reducer 的防线避免双击动作破坏正在进行的状态。

#### sequence 规则

后端每轮从 1 开始连续递增：

```text
lastSequence = 4

收到 5
    → 正常处理

收到 4 或更小
    → 视为已经处理的重放，原样返回 state

收到 6 或更大
    → sequence_gap，进入协议失败
```

忽略旧 sequence 很重要：未来重连可能从稍早事件开始重放。如果重复 `ai_delta` 再追加一次，用户会看到重复文字；重复工具参数则会破坏 JSON。

出现缺口时不能继续，因为缺失事件可能是正文、工具参数或终止状态。当前还没有事件重取能力，因此进入明确协议失败。

#### run_started 与身份隔离

第一条事件必须满足：

```text
phase = connecting
event = run_started
sequence = 1
event.threadId = 当前 threadId
```

`run_started` 建立服务端生成的 `runId`。后续每条事件必须同时匹配：

```text
threadId
runId
```

否则一个延迟响应或错误连接可能把其他线程、其他 run 的文字写进当前时间线。这里的检查是状态层隔离，不是权限校验；真正线程授权必须由后端完成。

#### 按 messageId 合并 AI delta

模型可能发送：

```text
messageId = assistant-1, text = "北"
messageId = assistant-1, text = "京"
messageId = assistant-1, text = "天气"
```

reducer 第一次创建 assistant 消息，之后查找同 ID 项目并追加：

```text
北京天气
```

不能为每个 delta 创建气泡。若同一 ID 已被用户消息或工具项目占用，则进入 `message_id_collision`，不能覆盖已有领域对象。

少数 provider 可能不给 message ID。当前使用：

```text
${runId}:assistant
```

作为本轮稳定回退键，使正文仍能合并。这是一种兼容降级；服务端提供真实 message ID 时始终优先使用真实值。

#### 按 toolCallId 合并工具活动

工具参数经常分片：

```text
toolCallId = call-1, name = null, argumentsDelta = "{"
toolCallId = call-1, name = get_weather, argumentsDelta = "\"city\""
toolCallId = call-1, argumentsDelta = ":\"北京\"}"
```

第一块创建 pending 工具卡，后续块按 `toolCallId` 追加参数并补全工具名。`toolCallId` 而不是工具名才是关联键，因为同一 run 可以多次调用 `get_weather`。

`tool_result` 到达时，用相同 `toolCallId` 把卡片更新为：

```text
status = completed
result = 工具正文
```

如果上游直接发送结果而没有可见参数分片，reducer 仍创建结果卡，避免丢失真实执行事实。若同一工具调用出现冲突名称、结束后继续收到参数或收到第二个不同 sequence 的结果，则进入协议失败。

#### 工具状态

工具时间线类型扩展为：

```text
pending
completed
failed
cancelled
```

`run_error` 或客户端失败会把所有 pending 工具标为 `failed`；用户取消会标为 `cancelled`。正常 `run_completed` 时若仍有 pending 工具，说明工具结果丢失，reducer 使用 `unsettled_tool_call` 拒绝伪装成成功。

`ToolActivity` 已能根据状态显示“调用中、已完成、失败、已取消”，工具名和结果尚未抵达时显示明确等待文案。静态预览仍使用 completed 状态，因此页面结构没有改变。

#### 三类失败来源

`ChatRunFailure.source` 区分：

```text
server
    → 后端 run_error

protocol
    → sequence、身份、生命周期或 ID 关联错误

client
    → HTTP、网络、解析或本地调用失败
```

这会影响后续重试和用户提示。不能只保存一个 `error: true`，否则无法判断是否应该重新请求、修复客户端、还是向用户展示后端业务错误。

#### 不可变更新

reducer 不修改原数组和原对象，而是使用：

```text
slice
spread
map
```

产生新引用。React 依靠引用变化决定是否渲染；原地执行 `item.content += text` 可能导致视图不更新，也会破坏历史 state 的测试与调试价值。

重复旧 sequence 则刻意返回完全相同的 state 引用，表示没有任何领域变化。

#### 线程切换规则

下一轮请求：

```text
threadId 相同
    → 保留已有 timeline，追加新用户消息

threadId 不同
    → 清空旧 timeline，只保留新线程用户消息
```

当前还没有 localStorage 和线程列表；这里只先把 reducer 的线程隔离行为固定。设备本地线程连续性将在后续原子功能点接入。

#### 自动化测试覆盖

`tests/reducer.test.ts` 覆盖 10 组行为：

1. 提交用户消息和 `run_started` 转移。
2. 按 message ID 合并多个 AI delta。
3. message ID 缺失时使用 run 内回退 ID。
4. 按 tool call ID 合并参数与结果。
5. 忽略重复 sequence、拒绝 sequence 缺口。
6. 拒绝错误 thread、错误 run 和缺失 `run_started`。
7. `run_error` 收束 pending 工具。
8. 未结束工具不能正常完成，终止后不能接收新事件。
9. 取消、客户端失败和重复提交。
10. 同线程保留时间线、跨线程清空时间线。

验证结果：

```text
reducer 定向测试：10 passed
前端全部测试：27 passed
typecheck、lint、build、format、git diff --check：全部通过
静态页面：HTTP 200，工具卡正常显示“已完成”
```

### 功能点 9.5 小结

完成该功能点后，已经掌握：

- 为什么强关联流式状态应该由一个 reducer 原子更新。
- connecting、streaming 与三种终止状态的区别。
- 为什么用户消息需要乐观加入时间线。
- sequence 如何实现重复保护与缺口检测。
- 为什么 thread ID 和 run ID 都必须匹配。
- message ID 如何把 token/delta 合并为一条消息。
- provider 不给 message ID 时如何有限降级。
- tool call ID 如何关联参数增量与最终结果。
- 为什么工具名不能作为工具调用身份。
- 工具 pending 状态如何在成功、失败和取消时收束。
- 服务端、协议和客户端失败为什么要分开。
- reducer 为什么必须使用不可变更新。
- 同线程继续与跨线程切换的时间线边界。

下一小步将实现 POST SSE API client：构造同源版本化 URL、校验请求、处理 HTTP 状态与 Content-Type、关联 `X-Run-ID`、组合 SSE parser 和事件校验器，并用统一脱敏客户端错误表达网络与协议失败。

## 功能点 9.6：POST SSE API client

本原子功能点已经由用户通过定向测试确认。它把前面三个纯模块组合起来：

```text
HTTP Response.body
    → parseSseStream()
    → SseFrame
    → decodeChatRunEvent()
    → ChatRunEvent
```

API client 不保存消息、不调用 reducer，也不依赖 React。它只负责一次 HTTP/SSE 请求的边界。

#### 为什么不能使用 EventSource

浏览器 `EventSource` 面向 GET 事件流，而 Mini Deer 需要：

```http
POST /api/v1/threads/{thread_id}/runs/stream
Content-Type: application/json

{"message":"查询北京天气"}
```

还需要 `AbortSignal`、HTTP 状态检查和请求正文，因此使用 `fetch()` 获取 `ReadableStream`，再交给已经测试过的 parser。

#### 请求前校验

`streamChatRun()` 在发起 fetch 前校验：

```text
threadId
    → 去除首尾空格
    → 转为小写
    → 必须是规范 UUID

message
    → 去除首尾空格
    → 长度 1..32768
```

后端仍然是最终权威校验方；前端校验用于提前阻止明显无效请求并提供稳定错误。不能因为前端已经验证就删除后端 Pydantic 约束。

#### 同源 URL 与开发代理

浏览器只请求：

```text
/api/v1/threads/{threadId}/runs/stream
```

开发期：

```text
浏览器
    → Vite 5173
    → /api 代理
    → FastAPI 8000 或配置的 8001
```

生产期可以由同一反向代理把 `/api` 转给 FastAPI。React 代码不硬编码后端 origin，也不需要开放宽泛 CORS。

请求明确设置：

```text
method: POST
Accept: text/event-stream
Content-Type: application/json
credentials: same-origin
cache: no-store
signal: AbortSignal（如果调用方提供）
```

#### HTTP 响应契约

client 不会只检查 `response.ok`。成功响应还必须满足：

```text
Content-Type 主类型 = text/event-stream
response.body != null
X-Run-ID 存在且为 UUID
```

Content-Type 允许标准参数：

```text
text/event-stream; charset=utf-8
```

因此先按分号提取主类型并转为小写比较。

`X-Run-ID` 是本轮 run 的响应级身份。每条事件解码后还要检查：

```text
event.runId == X-Run-ID
event.threadId == 请求 threadId
```

这样 HTTP 响应头、事件 envelope 和原请求形成三方关联，错误连接或服务端路由错误不能把其他 run 的内容交给 reducer。

#### HTTP 错误映射

client 把状态码映射为稳定错误：

| HTTP | code | retryable |
| --- | --- | --- |
| 400 / 422 | `invalid_request` | false |
| 401 | `unauthorized` | false |
| 403 | `forbidden` | false |
| 404 | `thread_not_found` | false |
| 409 | `run_conflict` | true |
| 429 | `rate_limited` | true |
| 5xx | `server_unavailable` | true |
| 其他 | `http_error` | 仅部分临时状态可重试 |

当前不会把错误响应正文直接显示给用户。FastAPI/Pydantic、代理或第三方组件的错误体可能包含用户内容、内部路径或其他敏感上下文。未来若建立正式公开错误 schema，只解析经过版本化和脱敏的字段。

错误响应不再消费时会尝试取消 body；清理失败不能覆盖原本的 HTTP 错误。

#### 终止事件规则

成功建立连接不代表业务成功。事件流必须最终出现：

```text
run_completed
或
run_error
```

若 TCP/HTTP 正常结束但没有终止事件，client 抛出：

```text
incomplete_stream
retryable = true
```

因为模型、工具或代理可能在中途断开，不能把“连接关闭”误认为“Agent 完成”。

终止事件之后若又出现 frame，则是 `stream_protocol_error`。不能把后续正文继续写进已经结束的 run。

#### Abort 与普通网络错误

client 分开表达：

```text
AbortSignal / AbortError
    → code = aborted
    → retryable = false
    → 用户主动结束，不显示网络故障

其他 fetch/network 异常
    → code = network_error
    → retryable = true
```

异常正文不会直接展示。浏览器的 TypeError、代理错误或 SDK 错误可能包含不适合用户界面的技术细节。

#### 依赖注入

生产默认使用：

```typescript
globalThis.fetch
```

测试可注入 `FetchLike`：

```typescript
streamChatRun(request, { fetcher: fakeFetch })
```

这不是为了在生产中随意替换 fetch，而是让 HTTP 契约测试能够：

- 捕获 URL、method、headers 和 body。
- 返回人工构造的分片 ReadableStream。
- 模拟 422、错误 Content-Type、缺失响应头和网络中止。
- 完全避免 DeepSeek 调用和测试费用。

#### 自动化测试覆盖

`tests/chat-stream.test.ts` 覆盖 9 组行为：

1. 同源版本化 POST 与逐条事件输出。
2. fetch 前拒绝非法 UUID 与空消息。
3. HTTP 状态到脱敏客户端错误的映射。
4. 非 SSE Content-Type、空 body、缺失 X-Run-ID。
5. 响应头 run ID 与事件 run ID 不一致。
6. 事件 JSON 校验失败的脱敏包装。
7. 缺少终止事件的不完整流。
8. 终止后出现新 frame。
9. AbortSignal 与网络失败语义区分。

验证结果：

```text
API client 定向测试：9 passed
前端全部测试：36 passed
typecheck、lint、build、format、git diff --check：全部通过
```

### 功能点 9.6 小结

完成该功能点后，已经掌握：

- 为什么 POST SSE 需要 fetch + ReadableStream，不能直接使用 EventSource。
- 为什么请求校验不能替代后端校验。
- 同源 `/api` 与 Vite 开发代理如何隔离部署差异。
- 成功 HTTP 状态之外还要验证 Content-Type、body 和 X-Run-ID。
- 为什么响应头 run ID、事件 run ID 和请求 thread ID 要交叉关联。
- HTTP 状态如何映射为稳定、可重试性明确的错误。
- 为什么错误响应正文不能未经契约直接显示。
- TCP 关闭与业务终止事件的区别。
- 为什么终止后事件属于协议错误。
- Abort 与网络故障为什么必须分开。
- 如何通过 FetchLike 注入对 HTTP client 做无网络测试。

下一小步将实现 `useChatRun`：创建 reducer、启动 client 异步迭代、派发每条事件、用 AbortController 停止读取、阻止同一线程并发提交，并确保组件卸载或线程切换后旧异步任务不能继续更新新页面。

## 功能点 9.7：useChatRun 异步生命周期编排

本原子功能点已经由用户通过定向测试确认。`useChatRun` 是 React 页面与前面纯模块之间的编排层：

```text
React 页面
    → submit / cancel
    → useChatRun
        ├── streamChatRun
        └── chatRunReducer
    → state
    → React 页面
```

页面不再接触 fetch、reader、SSE frame、JSON 校验或 AbortController。

#### submit 调用链

```text
submit(rawMessage)
    → 检查是否已有 active operation
    → trim 并拒绝空消息
    → 创建本地 userMessageId
    → 创建 AbortController
    → dispatch run/requested
    → for await streamChatRun(...)
    → 每条事件 dispatch run/event-received
    → 正常终止或捕获失败
    → finally 清理 active operation
```

本地用户消息 ID 默认由：

```typescript
crypto.randomUUID()
```

创建。测试可以注入稳定 ID，使断言不依赖随机值。

#### 为什么除了 phase 还需要 active operation ref

React state 更新不是同步赋值。用户快速双击时，第二次事件可能发生在 `phase` 从 idle 渲染为 connecting 之前。

hook 使用同步 ref 保存：

```text
operation id
threadId
AbortController
```

第一次 submit 立刻设置 ref；第二次 submit 看见 ref 非空便返回 false。reducer 也有幂等保护，但 ref 能在 React 下一次 render 前阻止真实第二个网络请求。

ref 不用于直接渲染；UI 的活动状态仍来自 reducer phase。

#### operation 身份

每次请求获得递增 operation ID。异步循环在派发事件前检查：

```text
activeOperation.id == 当前 operation.id
currentThreadId == operation.threadId
```

如果不匹配，说明请求已经被替换、线程已切换或组件已卸载。即使旧 Promise 稍后恢复，也直接返回，不把旧事件写入新页面。

仅依赖 AbortSignal 不够，因为某些测试替身、SDK 或已经排入微任务队列的回调可能不会立刻响应 abort。operation 身份是第二道竞态保护。

#### cancel 行为

```text
cancel()
    → 若无 active operation，返回 false
    → dispatch run/cancelled
    → controller.abort()
    → 返回 true
```

先更新 reducer，再中止底层流，使 UI 能立即显示取消，而不必等待 fetch/reader 抛出 AbortError。

catch 再次收到 aborted 时会重复派发 cancelled；reducer 对终止状态保持幂等，不会把取消误报成网络失败。

active operation 直到异步循环真正退出才在 finally 中清除。这样用户取消后不会在旧连接尚未收束时立刻启动重叠 run。

#### 客户端错误派发

`ChatStreamClientError` 转为：

```text
run/client-failed
    → code
    → message
    → retryable
```

`aborted` 不进入 failed，而进入 cancelled。

未知异常使用固定公开错误：

```text
code = unexpected_client_error
message = 聊天客户端发生未知错误
```

不能把未知 Error.message 直接送入 UI，因为第三方库或浏览器错误可能包含 URL、内部配置或用户正文。

#### 线程切换

hook 的 `threadId` prop 改变时：

```text
abort 旧 controller
    → 清空 active operation
    → 更新当前 thread ref
    → dispatch thread/reset
```

线程身份 ref 在 `useLayoutEffect` 中更新。严格 React Hooks 规则禁止在 render 阶段直接写 ref；layout effect 在 DOM 提交阶段完成同步，并在下一批异步事件派发前建立新身份边界。

切换后 state 回到：

```text
phase = idle
threadId = 新线程
timeline = []
```

旧流即使不响应 abort 并继续产生事件，也因 operation/thread 身份不匹配而被忽略。

#### 组件卸载

effect cleanup 会：

```text
abort active controller
activeOperation = null
```

旧异步 catch 看见 operation 已不再当前，直接返回，不在卸载组件上继续 dispatch。这防止后台连接泄漏和“卸载后更新状态”竞态。

#### hook 依赖注入

生产默认组合：

```text
streamRunner = streamChatRun
createMessageId = crypto.randomUUID
```

测试可注入：

```text
可控 AsyncGenerator<ChatRunEvent>
固定 message ID factory
```

这样可以精确暂停流、制造并发提交、触发 abort、切换线程并验证迟到事件，而不调用真实后端。

#### 自动化测试覆盖

`tests/use-chat-run.test.tsx` 覆盖 6 组生命周期：

1. runner 事件通过 reducer 合并为最终时间线。
2. active operation guard 阻止并发提交。
3. cancel 立即进入 cancelled 并中止 signal。
4. client error 转为 client failure。
5. 线程切换中止旧操作、重置并忽略迟到事件。
6. 组件卸载中止活动请求。

验证结果：

```text
hook 定向测试：6 passed
前端全部测试：42 passed
typecheck、lint、build、format、git diff --check：全部通过
```

### 功能点 9.7 小结

完成该功能点后，已经掌握：

- hook 作为 React 与纯 API/reducer 之间的编排层。
- 为什么 phase 不能替代同步 in-flight ref。
- operation ID 如何阻止迟到异步结果污染新状态。
- AbortController 如何贯穿 fetch、reader 和 UI 取消。
- 为什么取消要先更新 UI 再 abort。
- aborted 与 client failure 的不同语义。
- 为什么未知异常要转换为固定脱敏错误。
- 线程切换为什么同时需要 abort、reset 和身份检查。
- 为什么不能在 render 阶段写 ref。
- useLayoutEffect 如何建立提交阶段线程边界。
- effect cleanup 如何阻止卸载后的连接与状态泄漏。
- 如何用可控 AsyncGenerator 对异步 hook 做无网络测试。

下一功能点将把该 hook 接入真实页面：Composer 发送或停止，ThreadHeader 显示 run phase，MessageList 渲染 reducer timeline，ToolActivity 展示 pending/completed/failed/cancelled，并通过 Vite 同源代理连接本地 FastAPI。

## 功能点 9.8：实时页面组合与端到端调用链

#### 本功能点目标

前面的 parser、事件校验、reducer、API client 和 hook 都已经独立完成，本功能点把它们接入真实页面，使用户可以直接在浏览器中：

1. 输入并发送问题。
2. 立即看到自己的消息。
3. 观察 Run 从连接到流式生成的状态变化。
4. 观察工具名和参数逐步抵达。
5. 看到工具结果和模型最终回答。
6. 主动停止当前浏览器请求。
7. 在失败时看到稳定、脱敏的错误信息。

页面不再使用静态预览数据，所有消息和工具卡片都由真实 `ChatRunState.timeline` 驱动。

#### 页面组件的职责组合

`frontend/src/features/chat/ui/ChatPage.tsx` 是页面组合层：

```text
ChatPage
├── ConversationRail   ← 当前线程摘要和阶段
├── ThreadHeader       ← thread ID、run ID 和运行状态
├── MessageList        ← reducer 产生的时间线
│   └── ToolActivity   ← 工具参数、结果和状态
└── Composer           ← 输入、发送和停止
```

`ChatPage` 自己不发送 HTTP 请求，也不解析 SSE。它只创建本次页面生命周期内稳定的 `threadId`，调用 `useChatRun()`，再把状态和动作通过 props 交给子组件：

```tsx
const { state, isActive, submit, cancel } = useChatRun({
  threadId,
});

<MessageList items={state.timeline} />
<Composer isActive={isActive} onSubmit={submit} onCancel={cancel} />
```

这种边界保证以后接入线程仓储时，只需要改变 thread 来源，不需要把网络逻辑搬进页面组件。

#### Composer 的输入边界

`frontend/src/features/chat/ui/Composer.tsx` 使用本地 `draft` 保存尚未提交的草稿：

```text
用户输入
    → draft
    → trim
    → 非空并且当前无 active run
    → onSubmit(normalizedDraft)
```

键盘规则：

- `Enter`：发送。
- `Shift + Enter`：换行。
- 输入法仍在组合中文时：不触发发送。
- Run 活动期间：禁止再次提交，显示停止按钮。

`Composer` 不知道 `fetch`、SSE、DeepSeek 或 LangGraph。它只表达用户输入行为，这是 UI 与运行逻辑分离的第一层。

#### useChatRun 如何连接页面和流

提交后的前端流程为：

```text
Composer.onSubmit
    → useChatRun.submit
    → 建立 operation 与 AbortController
    → dispatch run/requested
    → 用户消息立即进入 timeline
    → streamChatRun
    → for await ChatRunEvent
    → dispatch run/event-received
    → chatRunReducer
    → React 重新渲染
```

`run/requested` 是乐观更新。浏览器不必等服务器返回 `run_started` 才显示用户消息，因此提交后的视觉反馈是立即的。

`useChatRun` 同时持有同步 in-flight guard。用户连续点击时，第二次提交会在 React 下一次 render 前被拒绝，避免同一线程产生两个重叠 Run。

#### POST SSE 客户端

`frontend/src/features/chat/api/chat-stream.ts` 请求正式接口：

```http
POST /api/v1/threads/{thread_id}/runs/stream
Content-Type: application/json

{"message":"请查询成都天气"}
```

浏览器原生 `EventSource` 主要用于 GET，不能直接满足 POST JSON、AbortSignal 和自定义错误处理，因此客户端使用：

```text
fetch
    → Response.body
    → ReadableStream<Uint8Array>
    → parseSseStream
    → decodeChatRunEvent
    → AsyncGenerator<ChatRunEvent>
```

API client 还校验：

- HTTP 状态。
- `Content-Type: text/event-stream`。
- `X-Run-ID` 与事件中的 Run ID。
- 事件所属 Thread。
- 流是否出现明确终止事件。
- Abort 和普通网络错误的不同语义。

#### 网络 chunk、SSE frame 与模型 token

这三者属于不同层级：

```text
模型 token
    → 模型 SDK 产生文本增量
    → 后端组成 SSE frame
    → 网络把 UTF-8 字节分成 chunk
```

网络 chunk 没有业务语义边界。一个 chunk 可能包含：

- 半个 SSE frame。
- 一个完整 SSE frame。
- 多个 SSE frame。
- 一个 UTF-8 中文字符的部分字节。

分块会受到运行时缓冲、TCP、代理和读取时机影响，不能假设与网速、模型 token 或事件一一对应。

模型 token 也不是字符数。Token 是模型 tokenizer 的切分单位：一个中文字符可能对应一个或多个 token，一个英文单词也可能被拆成多个 token。

因此 `sse-parser.ts` 必须使用流式 `TextDecoder`，把文本追加到 buffer，只按 SSE 空行分隔符提取完整 frame，并保留不完整尾部。

#### 从不可信 JSON 到 ChatRunEvent

浏览器收到的是 UTF-8 文本和 JSON，不是 Python 对象。完整类型转换为：

```text
AIMessageChunk / ToolMessage
    Python、LangChain 内部对象
        ↓ projector
RunEvent
    后端内部领域对象
        ↓ SSE encoder
UTF-8 SSE 文本 + JSON
        ↓ 网络
SseFrame
    浏览器协议解析结果
        ↓ decodeChatRunEvent
ChatRunEvent
    TypeScript 类型化事件
```

`frontend/src/features/chat/model/events.ts` 校验协议版本、UUID、sequence、SSE ID、message ID 和每种 payload。只有通过校验的判别联合才能进入 reducer。

这意味着服务端即使返回格式错误或互相矛盾的 JSON，页面也不会把它当成合法业务状态。

#### reducer 为什么必须区分五种身份

流式页面不能只依赖数组位置或工具名称，需要明确身份：

| 字段 | 负责的范围 |
| --- | --- |
| `thread_id` | 连续多轮对话 |
| `run_id` | Thread 上的一次 Agent 执行 |
| `message_id` | 同一条模型消息的文本增量 |
| `tool_call_id` | 工具参数分片、调用和结果 |
| `sequence` | 同一 Run 内事件的严格顺序 |

例如工具参数可能分片抵达：

```text
"{"
"\"city\""
":"
"\"成都\""
"}"
```

Reducer 通过 `tool_call_id` 找到同一张工具卡片，依次追加 `arguments_delta`。收到 `tool_result` 后，仍通过相同 ID 更新该卡片的结果和完成状态。

`sequence` 防止事件缺失或乱序。旧 sequence 可以在未来重连重放时被安全忽略；出现 sequence 缺口时，当前实现进入协议失败，而不是展示可能错误的状态。

#### 后端 Run 调用链

正式请求进入：

```text
server/routers/runs.py
    → RunStreamService.start_run
    → 分配 run_id
    → project_run_events
    → iter_run_sse_frames
    → StreamingResponse
```

`RunStreamService` 使用 `thread_id` 恢复 Checkpointer，只把本轮新的 `HumanMessage` 交给 LangGraph：

```text
START
    → model
    → tools_condition
        ├── 没有工具调用 → END
        └── 有工具调用 → ToolNode
                           → model
                           → END 或继续循环
```

天气查询的实际图执行为：

```text
第一次 DeepSeek 调用
    → 产生 get_weather(city="成都")

ToolNode
    → 执行真实 Open-Meteo 请求
    → 追加 ToolMessage

第二次 DeepSeek 调用
    → 读取 ToolMessage
    → 组织最终中文回答
```

#### Projector 为什么存在

LangGraph 产生的是 `AIMessageChunk`、`ToolMessage` 和 metadata。这些类型属于后端实现细节，不能直接成为公开浏览器协议。

`streaming/projector.py` 负责：

```text
AIMessageChunk.text
    → ai_delta

AIMessageChunk.tool_call_chunks
    → tool_call_delta

ToolMessage
    → tool_result

执行失败
    → run_error

正常结束
    → run_completed
```

投影层让 LangChain/LangGraph 与 Web API 解耦。以后更换模型 SDK 或调整 Agent 图，只要继续产生相同的 RunEvent，前端不需要认识新的 Python 类型。

#### 与 DeerFlow 前端的对应关系

DeerFlow 在 `frontend/src/core/threads/hooks.ts` 使用 LangGraph SDK 的：

```tsx
const thread = useStream<AgentThreadState>({
  client: getAPIClient(isMock),
  assistantId: "lead_agent",
  threadId: onStreamThreadId,
  reconnectOnMount: true,
  fetchStateHistory: { limit: 1 },
  throttle: true,
});
```

对应关系为：

| DeerFlow | Mini Deer |
| --- | --- |
| `useThreadChat` | 当前 `ChatPage` 的页面级 thread ID；下一功能点升级为 Thread Repository |
| SDK `useStream` | `useChatRun + streamChatRun + parseSseStream` |
| SDK 和 hooks 的消息合并 | `chatRunReducer` |
| `thread.submit()` | `useChatRun.submit()` |
| DeerFlow Workspace MessageList | `MessageList + ToolActivity` |
| `reconnectOnMount` | 尚未实现，属于后续 Run 可靠性阶段 |

DeerFlow 已经需要合并持久历史、实时消息、乐观消息和重连消息，并修复 `messages-tuple` 先于用户 `values` 消息到达造成的顺序竞态。

Mini Deer 先手工实现稳定 RunEvent、parser 和 reducer，一方面理解 SDK 隐藏的行为，另一方面避免页面直接绑定 LangGraph 内部协议。未来如果换用 SDK，也必须保持现有产品协议和测试边界。

#### UI 渲染边界

`MessageList` 只根据 `ChatTimelineItem.kind` 渲染：

```text
kind = message
    → 用户或 Mini Deer 消息

kind = tool
    → ToolActivity
```

工具状态映射为：

```text
pending   → 调用中
completed → 已完成
failed    → 失败
cancelled → 已取消
```

React 默认把模型文本和工具结果作为文本转义，不使用 `dangerouslySetInnerHTML`。未来增加 Markdown 和引用时，需要单独建立安全渲染策略。

#### 自动化检查发现的无障碍问题

第一次页面组件测试失败，不是聊天逻辑错误，而是顶部状态虽然视觉显示“就绪”或“已完成”，`role="status"` 却没有可访问名称。

修复方式是在 `StatusIndicator` 上显式提供：

```tsx
<span role="status" aria-label={label}>
```

这使 Testing Library 和读屏器都能准确识别状态。自动化测试不仅检查数据，也保护真实用户可访问性。

最终自动化结果：

```text
前端测试文件：6 passed
前端测试用例：43 passed
TypeScript typecheck：通过
ESLint：通过
生产 build：通过
Prettier：通过
```

#### 真实运行验证

本地运行结构为：

```text
浏览器 127.0.0.1:5173
    → Vite 同源 /api 代理
    → FastAPI 127.0.0.1:8001
    → DeepSeek V4 Flash
    → get_weather
    → Open-Meteo
```

用户在浏览器提交成都天气查询后实际观察到：

1. 用户消息立即显示。
2. `get_weather` 工具卡片出现。
3. 参数显示 `{"city":"成都"}`。
4. Open-Meteo 的真实天气结果写入工具卡片。
5. DeepSeek 根据工具结果生成最终中文回答。
6. Run 最终进入“已完成”。

这验证了从 React 输入、POST SSE、LangGraph、真实工具、第二次模型调用到页面 reducer 渲染的完整闭环。

#### 模型身份幻觉排查

在同一线程追问“你是什么模型”时，模型文本声称自己是 Claude。该回复不是运行配置，而是 DeepSeek 生成的普通 LLM 文本。

排查证据：

- 运行时 `model_provider = openai-compatible`。
- `model_name = deepseek-v4-flash`。
- API Base URL 是 DeepSeek 官方地址。
- 8001 端口运行当前项目的 Uvicorn 进程。
- SQLite Checkpoint 中最新 AIMessage 的 `response_metadata.model_name` 均为 `deepseek-v4-flash`。
- 项目源码没有 Claude 或 Anthropic 身份提示。

关键结论：

```text
LLM 的自然语言自我介绍
    ≠ 后端实际模型配置
    ≠ Provider 返回的运行元数据
```

模型名称必须来自可信后端配置或响应元数据。下一阶段将通过正式 Prompt Builder 和 SystemMessage 约束 Agent 产品身份，但系统仍不能把 LLM 自我声明当成安全事实。

#### 当前边界

本功能点仍未实现：

- Thread ID 的设备持久化。
- 新会话、线程列表和线程切换。
- 页面重开后的历史回放。
- 服务端真正取消 Run。
- SSE 重连和事件重放。
- Markdown、引用、文件和 Artifact。

这些能力都有正式扩展位置，不需要把网络、状态和渲染重新塞回一个页面组件。

### 功能点 9.8 小结

完成该功能点后，已经掌握：

- Composer、ChatPage、hook、client、parser、decoder、reducer 和 UI 的职责分工。
- POST SSE 为什么使用 fetch 和 ReadableStream。
- 网络 chunk、SSE frame 和模型 token 的真实区别。
- UTF-8 中文字符为什么可能跨网络 chunk。
- 为什么外部 JSON 必须先校验为 TypeScript 判别联合。
- thread ID、run ID、message ID、tool call ID 和 sequence 的不同作用。
- 工具参数分片如何合并，并与工具结果关联。
- Python/LangChain 消息如何经 RunEvent 和 SSE 转为浏览器事件。
- Projector 如何隔离 Agent 内部实现与公开 Web 协议。
- DeerFlow `useStream` 与 Mini Deer 手工流式栈的对应关系。
- 为什么模型的自我介绍不能作为真实模型身份。
- 自动化测试如何发现视觉之外的无障碍缺陷。

下一功能点将建立正式的前端 Thread Repository，使当前线程可以在刷新后续接，并实现“新会话”的真实行为。完成 Thread 本地边界后，再建立后端线程、消息和 Run 历史 API。

## 功能点 9.9：设备本地 Thread Repository 与刷新续接

#### 本功能点目标

上一个功能点中，`ChatPage` 使用：

```tsx
const [threadId] = useState(() => crypto.randomUUID());
```

这个 ID 只在当前 React 组件生命周期内稳定。浏览器刷新后 JavaScript 运行时重新创建，新的 UUID 会让后端把下一轮请求放入另一个 Checkpoint 线程，导致 Agent 无法续接刷新前的上下文。

本功能点只解决一个可独立验证的问题：

```text
刷新页面
    → 恢复相同 thread_id
    → 下一次 Run 继续使用同一个 SQLite Checkpoint
```

本功能点暂不实现线程列表、新会话、URL 路由和消息历史回放。

#### 与 DeerFlow 的对应关系

DeerFlow 的 `frontend/src/components/workspace/chats/use-thread-chat.ts` 把 Thread 身份从普通页面状态提升为独立边界：

```text
已有 Thread 路由
    → 从 URL 参数取得 thread_id

/new 路由
    → 生成新 UUID
    → 在当前新会话生命周期内保持稳定

线程切换或删除
    → 同步 URL、Thread 状态和聊天视图
```

DeerFlow 已经具有线程路由和服务端线程资源，因此 URL 是当前 Thread 的主要来源。Mini Deer 还没有线程列表和路由，本阶段先使用设备本地 Repository：

```text
DeerFlow useThreadChat
    → URL + 新线程状态 + 切换同步

Mini Deer CurrentThreadRepository
    → localStorage + UUID 校验 + 无存储降级
```

两者的共同原则是：Thread 身份不属于 `ChatPage` 的临时展示细节，应该由独立边界提供。

#### 为什么放在 entities/thread

新增文件：

```text
frontend/src/entities/thread/model/current-thread-repository.ts
```

Thread 是聊天、Run、历史、Artifact 和权限都会共同引用的领域实体，不应放入 `features/chat` 内部。

依赖方向为：

```text
ChatPage
    → CurrentThreadRepository 接口
        → localStorage 实现
```

页面不知道存储 key、UUID 校验或浏览器异常。以后改为 URL Repository、服务端 Thread Repository 或测试替身时，聊天页面只替换依赖来源。

#### 版本化 localStorage key

当前 key：

```text
mini-deer-agent.current-thread-id.v1
```

加入 `v1` 的原因是浏览器存储会跨版本长期存在。未来如果存储结构从单个字符串升级为带元数据的对象，可以使用新版本 key 或明确迁移，不能把旧数据误当成新格式。

localStorage 只保存设备选择的 Thread ID，不保存：

- 聊天消息。
- DeepSeek API Key。
- 用户令牌。
- Thread 所有权。
- LangGraph Checkpoint。

因此该 ID 只代表“这台设备当前选择哪个线程”，不是用户身份或授权凭证。

#### 浏览器数据必须校验

localStorage 可以被用户、浏览器扩展或其他页面脚本修改，不能直接拼入 API 路径。

Repository 读取后执行：

```text
读取字符串
    → trim
    → 转为小写
    → 校验标准 UUID 形状
        ├── 合法：复用并规范化保存值
        └── 非法：生成新 UUID 并覆盖
```

例如以下值不能成为 Thread ID：

```text
../../not-a-thread
```

这不仅保护后端 UUID 路径契约，也避免无效浏览器状态让整个聊天功能持续失败。

#### Repository 的 get-or-create 语义

`getOrCreateCurrentThreadId()` 的流程为：

```text
Repository 内已有 volatileThreadId
    → 直接复用

否则读取 localStorage
    ├── 存在合法 UUID
    │      → 写入 volatileThreadId
    │      → 返回
    └── 不存在、无效或读取失败
           → createThreadId()
           → 校验工厂结果
           → 写入 volatileThreadId
           → 尝试写入 localStorage
           → 返回
```

`volatileThreadId` 保证即使 localStorage 被禁用，同一个 Repository 实例仍然只创建一次 Thread ID。

#### localStorage 失败为什么不能阻断聊天

以下情况可能让浏览器存储抛出异常：

- 隐私或无痕模式策略。
- 浏览器禁用站点存储。
- 安全沙箱限制。
- 存储配额或实现异常。

设备持久化属于增强能力，不应该成为聊天页面的单点故障。因此 Repository 在读取或写入失败时降级为：

```text
当前页面内存 Thread
```

降级后的页面仍能发送和接收消息，只是刷新后可能产生新 Thread。异常不会把本地存储实现细节显示给用户。

#### UUID 工厂为什么仍需校验

生产默认使用：

```text
crypto.randomUUID()
```

测试会注入固定 ID factory。即使工厂属于内部依赖，Repository 仍校验其结果，防止测试替身、未来配置或错误适配器把非法 ID 送入正式 API 路径。

非法工厂结果会在本地立即抛出固定错误：

```text
线程 ID 工厂必须返回 UUID
```

#### ChatPage 如何接入 Repository

`ChatPage` 现在接收可选的 `CurrentThreadRepository`：

```tsx
const [threadRepository] = useState(
  () => currentThreadRepository ?? createCurrentThreadRepository(),
);

const [threadId] = useState(() =>
  threadRepository.getOrCreateCurrentThreadId(),
);
```

这里使用两层惰性 `useState`：

1. Repository 在组件生命周期内保持同一实例，不在每次 render 时重新读取存储。
2. Thread ID 只初始化一次，不因聊天状态更新重新变化。

页面测试注入固定 Repository，而不是操作真实 localStorage：

```text
CurrentThreadRepository
    → getOrCreateCurrentThreadId() 返回固定 UUID
```

这样组件测试关注页面调用契约，Repository 自己的存储行为由独立测试保护。

#### 刷新续接的完整调用链

第一次打开页面：

```text
App
    → ChatPage
    → createCurrentThreadRepository
    → localStorage 中没有 v1 key
    → crypto.randomUUID
    → 保存 thread_id
    → useChatRun(threadId)
    → POST /api/v1/threads/{thread_id}/runs/stream
    → SQLite Checkpointer 保存状态
```

刷新页面后：

```text
新的 JavaScript 运行时
    → 新的 ChatPage
    → 新的 Repository
    → 从 localStorage 读取相同 thread_id
    → useChatRun 使用相同 threadId
    → 后端恢复同一个 SQLite Checkpoint
    → 模型可以理解刷新前的对话
```

#### 上下文续接与消息回放不是同一能力

本功能点完成后，页面刷新会暂时变为空白，但 Agent 仍能记住前文。这是因为：

```text
后端 Checkpointer
    → 已有完整 LangGraph 消息状态

前端页面
    → 只有本次挂载后的 reducer timeline
    → 尚未请求服务端历史消息
```

必须区分：

- **Agent 上下文连续**：相同 thread ID 恢复 Checkpoint，本功能点已完成。
- **页面历史回放**：查询并渲染既有消息，后续 Thread/Message API 实现。

不能为了快速显示历史而让浏览器直接读取 SQLite Checkpointer 表。产品消息 API 必须经过正式 Thread Application Service 和稳定 schema。

#### 自动化测试

`tests/current-thread-repository.test.ts` 覆盖：

1. 两个默认浏览器 Repository 实例通过真实 jsdom localStorage 复用同一 ID。
2. 已存 UUID 的大小写和空格规范化。
3. 非法已存值被新 UUID 替换。
4. localStorage 读写异常时使用稳定内存降级。
5. 无效 UUID 工厂在本地被拒绝。

页面测试改为注入固定 `CurrentThreadRepository`，继续验证真实聊天事件链不受 Thread 来源变化影响。

最终自动化结果：

```text
Repository 定向测试：5 passed
前端测试文件：7 passed
前端测试用例：48 passed
TypeScript typecheck：通过
ESLint：通过
生产 build：通过
```

#### 真实运行验证

验证流程：

```text
第一次打开页面
    → 记录顶部 thread 短 ID
    → 要求 Agent 记住一个代号
    → 等待 Run 完成

刷新页面
    → 顶部 thread 短 ID 保持不变
    → 询问刚才的代号
    → Agent 从 SQLite Checkpoint 恢复并正确回答
```

用户完成实际验证并确认继续，说明设备 Thread ID、HTTP 路径和后端 Checkpoint 已形成跨刷新连续链路。

#### 当前边界

本功能点还没有改变：

- “新会话”按钮仍不可用。
- 页面没有线程列表。
- Thread ID 尚未进入 URL。
- 刷新后不回放旧消息气泡。
- localStorage Thread ID 仍不代表认证或权限。
- 服务端还没有 Thread 元数据和所有权模型。

### 功能点 9.9 小结

完成该功能点后，已经掌握：

- 为什么 Thread 身份不能只存在于 ChatPage 临时状态。
- DeerFlow `useThreadChat` 与 Mini Deer Repository 的职责对应关系。
- 为什么设备选择状态适合 localStorage，而消息和密钥不适合。
- 为什么 localStorage 输入必须经过 UUID 校验。
- 版本化存储 key 如何为未来迁移保留边界。
- 存储不可用时为什么应该降级而不是阻断聊天。
- Repository 如何隔离 UI 与具体存储实现。
- 为什么上下文续接和页面历史回放是两个独立能力。
- 相同 thread ID 如何让 FastAPI、LangGraph 和 SQLite 恢复同一对话状态。

下一功能点将在现有 Repository 上增加显式创建新 Thread 的能力，把侧栏“新会话”按钮从禁用预览变成真实动作，并验证新旧 Thread 的上下文彼此隔离。

## 功能点 9.10：新会话与 Thread 上下文隔离

#### 可观察目标

本功能点把侧栏“新会话”从禁用预览变成真实动作，并保证它不是单纯清空页面消息：

```text
创建新 UUID
    → 保存设备当前 Thread
    → 重置前端线程级状态
    → 下一轮请求使用新 thread_id
    → SQLite Checkpointer 进入独立上下文
```

运行期间不允许切换 Thread，避免旧 SSE 流的事件进入新页面状态。

#### DeerFlow 源码对应

DeerFlow 的 `frontend/src/components/workspace/chats/use-thread-chat.ts` 使用 URL 和 React 状态管理当前 Thread。

进入 `/new` 路径时，它通过 `newThreadIdRef` 保存新 UUID：

```ts
const newThreadIdRef = useRef<string | null>(
  threadIdFromPath === "new" ? uuid() : null,
);
```

`useRef` 防止组件每次 render 都重新生成 ID。真正的新会话动作是：

```ts
const resetToNewThread = useCallback(() => {
  const nextThreadId = uuid();
  newThreadIdRef.current = nextThreadId;
  setIsNewThreadState(true);
  setThreadIdState(nextThreadId);
}, []);
```

其核心语义不是“删除消息”，而是改变所有下游聊天 Hook 使用的 Thread 身份。

Mini Deer 当前还没有完整的 Thread 路由和服务端历史列表，因此没有复制 DeerFlow 的 URL 实现，而是保留同一职责边界：

| 职责 | DeerFlow | Mini Deer |
| --- | --- | --- |
| 生成新 Thread | `uuid()` | `crypto.randomUUID()` |
| 稳定保存当前 ID | `newThreadIdRef` 和路由状态 | `CurrentThreadRepository` |
| 切换 React 状态 | `setThreadIdState` | `setThreadId` |
| 重置运行状态 | 下游 Stream Hook | `useChatRun` 的 `thread/reset` |
| 隔离后端上下文 | Thread ID | Thread ID 与 SQLite Checkpointer |

#### Repository 新增创建契约

`CurrentThreadRepository` 增加：

```ts
readonly createNewCurrentThreadId: () => string;
```

创建逻辑统一进入 `createAndRememberThreadId()`：

```text
调用 ID 工厂
    → 规范化并校验 UUID
    → 拒绝与当前 Thread 相同的 ID
    → 更新 Repository 内存状态
    → 尝试写入 localStorage
    → 返回新 ID
```

拒绝相同 ID 很重要。如果工厂错误地返回旧值，只清空前端时间线会让页面看起来像新会话，但后端仍会继续读取旧 Checkpoint。

`persistThreadId()` 单独封装浏览器存储边界。localStorage 写入失败时只失去跨刷新选择能力，当前页面仍然使用内存中的新 Thread，不让浏览器存储策略阻断聊天。

#### ChatPage 的切换入口

`ChatPage` 把 `threadId` 改为可更新状态：

```tsx
const [threadId, setThreadId] = useState(() =>
  threadRepository.getOrCreateCurrentThreadId(),
);
```

新会话处理函数为：

```tsx
const createNewThread = useCallback(() => {
  if (isActive) {
    return;
  }

  setThreadId(threadRepository.createNewCurrentThreadId());
}, [isActive, threadRepository]);
```

页面同时使用两层保护：

1. `ConversationRail` 在 Run 活动期间禁用按钮。
2. `ChatPage` 处理函数再次判断 `isActive`，避免未来其他入口绕过按钮约束。

这属于界面约束和业务入口约束的纵深保护。

#### useChatRun 如何完成真正重置

`threadId` 改变后，`useChatRun` 的 `useLayoutEffect` 执行：

```ts
activeOperationRef.current?.controller.abort();
activeOperationRef.current = null;
previousThreadIdRef.current = threadId;
dispatch({ type: "thread/reset", threadId });
```

它会清除当前 Thread 的：

- `phase`
- `runId`
- `lastSequence`
- `startedAt`
- `finishReason`
- `timeline`
- `error`

使用 `useLayoutEffect` 可以在浏览器绘制前完成重置，避免短暂显示“新 Thread 标题配旧消息列表”。

此外，每个异步流在派发事件前仍要验证：

```text
operation ID 仍是当前 operation
并且
operation.threadId 等于当前 threadId
```

所以旧请求即使在 abort 后仍有迟到 Promise 或缓冲数据，也不能写入新 Thread。

#### 完整调用链

```text
ConversationRail 点击“新会话”
    → ChatPage.createNewThread
    → CurrentThreadRepository.createNewCurrentThreadId
    → 生成、校验并保存新 UUID
    → setThreadId
    → useChatRun 发现 Thread 改变
    → abort 旧请求并 dispatch(thread/reset)
    → Header 显示新 Thread，时间线恢复为空
    → 用户发送下一条消息
    → POST /api/v1/threads/{new_thread_id}/runs/stream
    → FastAPI 把 new_thread_id 传入 LangGraph configurable
    → SQLite Checkpointer 在新 Thread 命名空间运行
    → RunEvent 携带新 thread_id 返回
    → reducer 只接收当前 Thread 的事件
```

因此真正的上下文隔离依据是：

```text
新 thread_id → 新 Checkpoint 命名空间 → 新 Agent 上下文
```

而不是 `setMessages([])`。

#### 自动化测试

Repository 测试新增保护：

1. 创建新 Thread 后立即替换内存和设备当前 ID。
2. 新 ID 被持久化到版本化 localStorage key。
3. 工厂返回当前 ID 时明确失败。

页面交互测试覆盖完整生命周期：

1. 第一轮 Run 活动期间“新会话”按钮禁用。
2. 第一轮结束后按钮恢复。
3. 点击后顶部 Thread ID 改变，旧时间线被清空。
4. 第二轮请求确实使用新 Thread ID。

最终自动化结果：

```text
前端测试文件：7 passed
前端测试用例：51 passed
TypeScript typecheck：通过
ESLint：通过
生产 build：通过
```

#### 真实运行验证

浏览器验证使用带随机后缀的测试代号：

```text
旧 Thread 要求 Agent 记住代号
    → 等待 Run 完成
    → 点击“新会话”
    → 顶部 Thread ID 改变
    → 旧消息从当前时间线消失
    → 新 Thread 询问旧代号
    → 不继承旧 Thread 上下文
```

用户完成源码讨论和实际页面验证后确认继续，说明浏览器 Thread 选择、SSE 运行状态与后端 Checkpoint 已形成一致的隔离链路。

#### 当前边界

本功能点没有伪装以下尚未实现的能力：

- 侧栏仍没有服务端最近会话列表。
- 不能重新选择已离开的旧 Thread。
- 刷新页面只能续接 Agent 上下文，尚不能回放旧消息气泡。
- Thread ID 仍不是用户身份或授权凭证。
- 服务端还没有正式 Thread、Message、Run 查询模型。

### 功能点 9.10 小结

完成该功能点后，已经掌握：

- DeerFlow `resetToNewThread` 的真正含义是切换身份，而不是清空数组。
- Repository 如何隔离 UI、UUID 工厂和浏览器存储。
- 为什么新 Thread 必须与旧 Thread 拥有不同 ID。
- 为什么 Run 活动期间不能随意切换 Thread。
- `useLayoutEffect` 如何在绘制前完成线程级状态重置。
- operation ID 与 thread ID 双重检查如何拒绝旧流迟到事件。
- localStorage 当前选择和 SQLite Agent 上下文分别承担什么职责。

下一功能点将建立正式的 Thread、Message、Run 历史查询边界，使页面刷新后不仅能让 Agent 记住上下文，还能恢复用户看得见的历史消息。

## 功能点 9.11：产品历史持久化、查询 API 与页面重开恢复

#### 学习目标

此前页面已经能够保存当前 `thread_id`，LangGraph Checkpointer 也能让模型在同一 Thread 中恢复上下文，但刷新浏览器以后，旧消息气泡仍然会消失。

本功能点要解决的是两类不同问题：

```text
LangGraph Checkpointer
    → 为 Agent 执行恢复图状态和模型上下文

产品历史存储
    → 为浏览器提供稳定的 Thread、Run、Message 和 Tool 查询模型
```

目标不是把 Checkpointer 的内部 SQLite 表直接暴露给页面，而是建立独立、可演进的产品历史边界。

#### DeerFlow 源码对应关系

DeerFlow 同样区分运行时状态恢复和产品查询：

- Checkpoint 接口面向图执行状态和调试历史。
- `/threads/{thread_id}/messages/page` 面向前端可展示消息的分页查询。
- Run 查询接口返回产品级运行状态，而不是让浏览器理解 LangGraph 内部对象。
- 前端历史 Hook 通过分页查询恢复消息，并把服务端历史与当前流式消息协调起来。

这说明“模型记得上一轮”和“页面能显示上一轮”不是同一能力。前者属于 Agent Runtime，后者属于应用数据模型。

#### 为什么不能读取 Checkpointer BLOB 作为产品 API

LangGraph Checkpointer 的职责是保存图状态。它的数据布局、序列化格式和版本变化由运行时框架决定，可能包含：

- 框架内部 Channel 状态。
- 序列化消息对象。
- Checkpoint 父子关系。
- Pending write 和其他执行细节。

如果产品页面直接读取这些内部表，就会产生三个问题：

1. 浏览器 API 被第三方框架的内部格式绑定。
2. 很难稳定分页、授权、归档和审计。
3. 框架升级可能破坏产品历史查询。

因此 Mini Deer 新建独立的应用 SQLite 数据库，由自己的 Repository 和迁移规则负责。

#### 领域模型

`domain/conversations.py` 定义了产品级对象：

- `ThreadRecord`：对话容器及其更新时间。
- `RunRecord`：一次执行的状态、序号和错误信息。
- `MessageHistoryItem`：用户或模型消息。
- `ToolExecutionHistoryItem`：工具调用参数、结果和状态。
- `ConversationHistoryPage`：按时间线分页后的统一结果。

领域层只表达业务事实，不依赖 FastAPI、SQLite 或 React，因此以后替换数据库、增加 CLI 或消息渠道时不需要重写核心语义。

#### 应用历史数据库结构

应用数据库采用版本化迁移并启用 `foreign_keys`、WAL 和 `busy_timeout`。核心表为：

```text
schema_migrations
    └─ 记录已经执行的应用数据库迁移

threads
    └─ 一个产品会话容器

runs
    └─ Thread 上的一次 Agent 执行

timeline_items
    └─ Thread 内统一、单调递增的展示顺序
       ├─ messages
       └─ tool_executions
```

`messages` 和 `tool_executions` 保存各自专有字段，`timeline_items` 负责统一排序。这样可以避免分别查询消息和工具后，再用不可靠的时间戳猜测交错顺序。

关键约束包括：

- `(thread_id, thread_sequence)` 唯一，保证同一 Thread 的历史顺序确定。
- 活动 Run 使用部分唯一索引，保证同一 Thread 默认只有一个会修改状态的在途 Run。
- 外键把 Run、Message、Tool 与所属 Thread 串联起来。
- 服务启动时把遗留的 `pending`、`running` Run 收敛为 `interrupted`，避免进程崩溃后 Thread 永久被锁住。

#### 写入链路

完整写入流程是：

```text
浏览器生成 user message_id
    → POST /api/v1/threads/{thread_id}/runs/stream
    → RunStreamService.create_run(...)
    → Repository 原子创建 Thread、Run 和用户消息
    → LangGraph 产生 RunEvent
    → Repository.apply_run_event(event)
    → 物化模型消息、工具执行和 Run 状态
    → 事件写入成功后才 yield 给 SSE
```

浏览器生成并提交用户消息 ID 很重要：同一条用户消息在乐观 UI、请求协议和持久化历史中拥有相同身份，刷新后的历史才能与当前页面安全合并。

服务端遵循“先持久化，再发送”的顺序。若先把事件发给浏览器、后写数据库，用户可能已经看到内容，但刷新后内容丢失。

#### 模型消息 ID 的稳定投影

模型供应商或 LangChain 产生的原始消息 ID 不一定符合产品 UUID 契约，也不应该直接成为跨 Run 的产品身份。

投影器使用 Run 命名空间和供应商消息 ID 生成确定性的 UUID：

```text
product_message_id = UUIDv5(run_id namespace, provider_message_id)
```

同一 Run 内重复看见同一供应商消息会得到相同产品 ID，不同 Run 又不会冲突。这也让流式增量和最终历史记录可以按稳定 ID 合并。

#### 中断清理边界

SSE 生成器使用 `finally` 检查本次 Run 是否已经产生终态。如果浏览器断开、请求被 Abort 或生成器被提前关闭，Repository 会把仍在活动的 Run 标记为 `interrupted`。

这项能力解决的是“连接断开后不要留下永久 running 状态”，但它还不等于正式的服务端取消：

- 尚无显式取消 API。
- 尚无跨请求 Run Task Manager。
- 尚无真正控制后台执行任务的取消句柄。
- 尚未定义重复取消和终态取消的幂等响应。

#### 历史查询 API

新增产品接口：

```text
GET /api/v1/threads/{thread_id}
GET /api/v1/threads/{thread_id}/runs
GET /api/v1/threads/{thread_id}/messages?limit=...&before_sequence=...
```

消息接口返回统一的消息和工具时间线，并通过 `before_sequence` 向更早记录分页。

一个设备刚生成但尚未发过消息的 prospective Thread，查询消息历史时返回：

```text
thread_exists = false
items = []
```

这不是服务器错误，因此不返回 404；而查询明确要求存在的 Thread 元数据或 Run 列表时，不存在仍返回 404。

#### 前端历史恢复

前端恢复链路由三个层次组成：

1. `thread-history.ts` 请求历史 API，并严格校验版本、UUID、状态、顺序和分页游标。
2. `use-thread-history.ts` 管理初次加载、错误重试、向前分页、`AbortController` 和 generation 防旧请求回写。
3. Chat reducer 通过稳定 ID 把服务端历史与当前实时事件合并，并拒绝其他 Thread 的历史。

页面状态转换为：

```text
读取本地当前 thread_id
    → 查询该 Thread 的产品历史
    → 校验响应
    → hydrate reducer
    → 展示用户消息、工具执行和模型回答
    → 必要时继续加载更早历史
```

切换或新建 Thread 时，旧请求即使晚到，也会因为取消、generation 或 thread ID 检查而无法污染当前页面。

#### 两个 SQLite 数据库的职责

当前项目明确保留两个不同数据库：

```text
data/checkpoints.sqlite
    → LangGraph Checkpointer
    → Agent 图状态、模型上下文和执行恢复

data/application.sqlite
    → Mini Deer 产品数据
    → Thread、Run、Message、Tool 和页面查询
```

这不是重复保存同一份数据，而是用不同投影服务不同职责。后续产品库可以迁移到 PostgreSQL，Checkpointer 也可以独立升级或更换。

#### 自动化验证

后端测试覆盖：

- 应用数据库迁移、约束和统一时间线物化。
- 历史分页及索引查询路径。
- 同 Thread 活动 Run 冲突。
- 服务启动时遗留 Run 恢复。
- 完整 SSE 写入后再查询历史。
- 流关闭后 Run 收敛为 `interrupted`。

前端测试覆盖：

- 历史 API 客户端的严格校验。
- Hook 的加载、分页、重试和过期请求隔离。
- reducer 的历史与实时消息合并。
- 页面刷新后的完整历史恢复。

最终自动化结果：

```text
后端测试：48 passed
前端测试文件：9 passed
前端测试用例：59 passed
TypeScript typecheck：通过
ESLint：通过
Prettier：通过
生产 build：通过
```

#### 真实运行验证

用户重新启动后端和前端，在真实浏览器中完成了一轮包含真实工具执行的对话，随后刷新页面，确认：

- 用户消息能够恢复。
- 工具请求、工具结果和最终模型回答能够按原顺序恢复。
- 刷新后仍可在同一 Thread 继续下一轮对话。
- 页面未出现重复历史或错误 Thread 混入。

用户确认测试没有问题后，本节才正式写入学习文档。

#### 当前边界

本功能点仍然没有伪装以下能力：

- 旧 Checkpointer 数据不会自动反向填充到新的产品历史库。
- 侧栏尚无服务端最近 Thread 列表和旧 Thread 选择。
- Thread 尚未绑定认证主体和所有权。
- 当前使用本地 SQLite，尚未引入多实例数据库部署。
- 当前是历史状态物化，不是支持断线重放的 Event Store。
- 流断开清理不等于正式、可幂等的服务端 Run 取消。

### 功能点 9.11 小结

完成该功能点后，已经掌握：

- Checkpointer 状态恢复与产品历史查询的职责差异。
- 为什么不能把 LangGraph SQLite 内部 BLOB 当作稳定产品 API。
- 如何使用统一时间线为 Message 和 Tool 建立确定顺序。
- 为什么同 Thread 活动 Run 需要数据库级并发约束。
- 为什么 SSE 必须先持久化事件再发送给浏览器。
- 如何用稳定产品 ID 协调乐观 UI、流式增量和刷新历史。
- 前端如何校验、分页并抵御旧请求回写。
- 如何通过真实浏览器验证完整的跨进程历史恢复链路。

下一功能点将对照 DeerFlow 的 Run Manager、取消状态机和幂等接口，建立真正的服务端 Run 取消能力。

## 功能点 9.12：服务端 Run 取消与中断工具历史恢复

#### 学习目标

上一功能点只能在 SSE 连接关闭时把产品数据库中的活动 Run 收敛为
`interrupted`。浏览器的 `AbortController` 停止的是网络读取，不能单独证明模型
请求、工具 HTTP 请求或后台 Agent 执行已经终止。

本功能点建立正式的服务端 Run 生命周期：

```text
启动 Run
    → 后台 asyncio.Task 执行 LangGraph
    → SSE 订阅 RunEvent
    → 浏览器使用 run ID 显式取消
    → 服务端取消真实 Task
    → 持久化 run_interrupted
    → SSE 交付可信终态
```

实际验证还发现了第二个问题：Run 在工具节点中途取消后，LangGraph checkpoint
可能保留 `AIMessage.tool_calls`，却没有对应的 `ToolMessage`。这种历史必须在下次
调用模型前修复，否则 DeepSeek 等严格 OpenAI-compatible 模型会拒绝请求。

#### DeerFlow 源码对应关系

DeerFlow 将 Run 本身与 SSE 订阅分离：

- `runtime/runs/manager.py` 的 `RunRecord` 保存 `task`、`abort_event`、状态和
  Run 身份。
- `RunManager` 负责活动 Run 注册、持久化状态竞争、取消、启动屏障和关闭清理。
- `gateway/services.py` 先完成持久化准入，再无 `await` 窗口地调用
  `asyncio.create_task()` 附加后台 Worker。
- `gateway/routers/thread_runs.py` 提供独立的 Run 取消接口。
- SSE 断开时根据明确策略调用同一个 `RunManager.cancel()`，而不是在传输层
  复制另一套清理逻辑。

DeerFlow 还始终注册 `DanglingToolCallMiddleware`。它在模型调用边界：

1. 找出 AI 消息声明的全部工具调用。
2. 把已有 ToolMessage 移到对应 AI 消息之后。
3. 为没有结果的工具调用生成错误 ToolMessage。
4. 丢弃没有上游工具调用的孤儿 ToolMessage。
5. 只改变本次模型请求的消息视图，不篡改持久化 checkpoint。

它使用模型调用包装层而不是简单的图前置节点，因为缺失 ToolMessage 必须插入到
原 AIMessage 后面；只在消息列表末尾追加并不能修复协议顺序。

#### 为什么 Run 与 SSE 必须分离

旧链路近似为：

```text
浏览器 fetch
    → FastAPI StreamingResponse
    → Python 生成器
    → LangGraph 同步 stream
```

这种结构把“客户端是否继续读取”和“服务端工作是否继续执行”耦合在一起。它没有
跨 HTTP 请求可寻址的后台任务句柄，也无法为重复取消、终态取消和应用关闭定义
统一语义。

新链路为：

```text
POST runs/stream
    → RunExecutionManager.start_run
    → 创建产品 Run
    → 持久化 run_started
    → 注册 _ActiveRun
    → asyncio.create_task(_execute)

StreamingResponse
    → 只订阅 _ActiveRun.events

POST runs/{run_id}/cancel
    → 寻址同一个 _ActiveRun.task
    → 取消并等待终止持久化
```

因此 SSE 是 Run 的一个订阅者，不再是 Run 本身。

#### `RunExecutionManager` 的进程内状态

`application/run_execution.py` 定义 `_ActiveRun`，保存：

- `run_id` 和 `thread_id`：身份与所有权关联。
- `events`：有界异步事件队列。
- `task`：真正执行 Agent 的后台 Task。
- `abort_event`：协作式停止信号。
- `cancel_lock`：串行化并发重复取消。
- `last_sequence`：生成中断终态时使用的下一序号。
- `abort_reason`：区分用户取消、连接断开和服务关闭。
- `terminal`：防止重复生成终态。

Task、Lock、Event 和 Queue 都只在当前 Python 进程有效，不能写入 SQLite。数据库
保存可持久化的 Run 事实，`_ActiveRun` 保存当前 Worker 才能使用的执行句柄。

#### 无半附加状态的启动屏障

`start_run()` 依次执行：

1. 在产品数据库创建 Thread、Run 和用户消息。
2. 持久化 sequence 为 1 的 `run_started`。
3. 把 `run_started` 放入事件队列。
4. 把 `_ActiveRun` 注册到进程内字典。
5. 无等待窗口地创建后台 Task。
6. 向 Router 返回 Run ID 和事件订阅器。

从注册 `_ActiveRun` 到 `create_task()` 之间没有 `await`，取消请求不能观察到
“数据库 Run 已存在、进程字典也存在、但 Task 尚未附加”的半状态。若 Task 附加
本身失败，服务端会把刚创建的 Run 收敛为错误状态。

Run ID 同时通过 `X-Run-ID` 响应头返回。浏览器不必等待第一条 SSE body 才知道
正在执行哪个 Run，因此可以尽早建立取消寻址。

#### 真正可取消的异步调用链

外层有 `asyncio.Task` 并不代表内部一定能及时取消。若模型或工具仍在执行同步
阻塞调用，`task.cancel()` 只能等阻塞函数返回。

本功能点把 Web 执行路径贯通为真正的异步链路：

```text
RunExecutionManager._execute
    → RunStreamService.astream_run_events
    → aproject_run_events
    → astream_agent_messages
    → graph.astream
    → async_model_node / ToolNode
    → model.ainvoke / get_weather coroutine
    → 异步模型 HTTP / httpx.AsyncClient
```

Checkpointer 同时改用原生 `AsyncSqliteSaver`。CLI 和历史学习示例仍保留同步
`invoke()`、`stream()` 和同步天气函数；同一模型节点通过 `RunnableLambda` 的
同步与异步实现分别服务两类入口。

#### 先持久化再发布与取消竞态

后台 Task 获得一个 RunEvent 后，执行顺序为：

```text
RunEvent
    → Repository.apply_run_event
    → SQLite 事务提交
    → 更新 last_sequence
    → 放入 SSE 队列
```

这样浏览器只要看见某个事件，产品数据库就已经能够在刷新后恢复它。

应用数据库目前仍是同步 Repository，所以异步管理器使用 `asyncio.to_thread()`
调用。已经开始运行的线程写入不能被 `task.cancel()` 强杀，因此代码用
`asyncio.shield()` 保护单条写入：取消落在 SQLite 写入中间时，先等待该事件
完整提交并排队，再继续传播 `CancelledError`。这避免数据库已经写入事件，而
管理器还使用旧 sequence 生成重复终态。

Repository 对终态采用“第一个终态获胜”：一旦 Run 不再是 `pending/running`，
迟到的 `run_completed`、`run_error` 或 `run_interrupted` 都不能翻转结果，也不会
进入 SSE。

#### 幂等取消状态机

正式接口为：

```http
POST /api/v1/threads/{thread_id}/runs/{run_id}/cancel
```

管理器先同时检查持久化 Run 和进程内 `_ActiveRun`：

- Run 或 Thread 不匹配：`404 run_not_found`。
- `pending/running` 且由当前 Worker 持有：执行取消并返回 204。
- 已经是 `interrupted`：等待首个取消完成清理，然后幂等返回 204。
- 已自然 `completed/failed`：返回 409，不能伪造取消成功。
- 数据库显示活动，但不属于当前进程：返回 `409 run_not_active`，为未来多 Worker
  协调保留明确边界。

真实取消同时使用：

```text
abort_event.set()
    → 协作式执行点观察停止意图

task.cancel()
    → 向当前异步等待点注入 CancelledError

await task
    → 等待工具、模型、事件和数据库清理完成

run_interrupted
    → 把取消物化为浏览器和数据库共同认可的终态
```

浏览器断开订阅和应用 shutdown 都复用该状态机，只改变 `reason`。应用退出时先
停止并等待本进程全部 Run，再关闭 Checkpointer 和产品数据库，避免资源关闭后
仍有后台写入。

#### 前端 `stopping` 与可信终态

前端从响应头取得 Run ID 后，点击“停止”会：

1. reducer 从 `connecting/streaming` 进入 `stopping`。
2. 调用正式取消 API。
3. 不主动关闭已经建立的 SSE。
4. 等待服务端发送 `run_interrupted`。
5. 把 Run 设为 `cancelled`，并把 pending 工具卡收敛为“已取消”。

HTTP 204 说明取消命令已经被服务端接受并完成处理，但 SSE 中按 sequence 到达的
`run_interrupted` 才是页面状态机的可信终态。若取消接口失败，页面返回生成状态
并显示“停止请求失败”，不会谎报已取消。

若用户在响应头到达前立即停止，浏览器尚无 Run ID 可用于显式取消。此时
AbortController 仍作为连接阶段回退；服务端订阅关闭后会进入相同的
`client_disconnected` 取消状态机。

#### 第一次真实验证暴露的恢复故障

用户在浏览器发送八城市天气任务并点击停止后，实际观察到：

- 未完成的天气工具卡全部显示“已取消”。
- Run 不再继续追加模型内容。
- 同一 Thread 已经能够再次提交消息。

但发送“继续刚才的任务”和“继续”时，两次新 Run 都立即显示：

```text
Agent execution failed
```

读取 `application.sqlite` 后确认：

- 原 Run 已正确保存为 `interrupted/user_cancelled`。
- 后续两个 Run 都成功创建，不存在活动 Run 锁残留。
- 两个 Run 都在模型执行阶段以 `agent_execution_failed` 结束。

随后只读取 `checkpoints.sqlite` 的消息类型、ID 和关联字段，不输出消息正文，得到：

```text
AIMessage
    tool_calls = 8 个天气调用
HumanMessage("继续刚才的任务")
HumanMessage("继续")
```

八个工具调用对应的 ToolMessage 全部缺失。取消发生在 ToolNode 提交结果之前，
因此产品数据库正确记录了取消，但 LangGraph checkpoint 保留了一个严格模型不能
重放的不完整工具协议。

这再次证明两个数据库职责不同：产品历史状态正确，不代表 Agent checkpoint 一定
可以直接交给模型继续执行。

#### Dangling Tool Call 修复

Mini Deer 新建 `agents/middleware/tool_history.py`，在 `model_node` 和
`async_model_node` 调用模型前执行纯函数修复：

```text
原 checkpoint messages
    → 收集 AIMessage.tool_calls
    → 按 tool_call_id 索引已有 ToolMessage
    → 在对应 AIMessage 后重新排列已有结果
    → 为缺失结果补 status=error 的 ToolMessage
    → 丢弃无来源 ToolMessage
    → 得到 model-bound messages
    → invoke / ainvoke
```

合成结果明确告诉模型：工具调用已中断、不能假设成功，如果任务仍需要结果就应
重新调用工具。它不会进入 checkpoint，也不会作为真实工具结果展示给用户。

不能直接把合成 ToolMessage 追加到消息列表末尾，因为严格协议要求每个工具结果
紧跟发起它的 AIMessage，并且位于后续 HumanMessage 之前。模型边界修复还能处理
已经被失败重试追加了多条 HumanMessage 的历史，而无需重写持久化 checkpoint。

#### 自动化验证

后端新增和加强的测试覆盖：

- 显式取消真正抵达后台 Task 的 `CancelledError`。
- 取消发生在订阅读取第一条事件之前仍能交付 started 与 interrupted。
- 重复取消幂等、Thread 不匹配和自然完成后的迟到取消。
- SQLite 第一个终态获胜。
- 异步天气 HTTP 请求确实可取消。
- dangling 工具调用按原调用顺序补齐错误结果。
- 已有工具结果复用，只补缺失结果。
- 孤儿 ToolMessage 从模型视图移除。
- 合法工具历史保持原消息对象和顺序。
- 同步与异步模型节点都执行同一修复。

前端测试覆盖：

- 从 `X-Run-ID` 建立取消寻址。
- 调用取消接口后不提前 Abort SSE。
- `stopping` 等待 `run_interrupted` 收口。
- 取消接口失败后恢复流式状态。
- 工具卡在中断终态变为 cancelled。

最终自动化结果：

```text
后端测试：58 passed
前端测试文件：9 passed
前端测试用例：62 passed
TypeScript typecheck：通过
ESLint：通过
Prettier：通过
生产 build：通过
```

使用真实受损 Thread 做不访问 DeepSeek 的模型输入预检，确认原 checkpoint 的
8 个缺失工具结果全部被补到对应 AIMessage 后，后续 HumanMessage 顺序合法。

#### 真实运行验证

用户重新启动后端，在真实浏览器和真实 DeepSeek、Open-Meteo 链路中完成取消与
继续验证，确认：

- “停止”会短暂显示“正在停止”。
- 后端 Run 最终进入 interrupted，页面显示“已取消”。
- pending 工具卡收敛为“已取消”。
- 同一 Thread 可以继续提交新 Run。
- 中断历史不再导致 `Agent execution failed`。
- 模型能够根据合成错误结果重新调用仍然需要的天气工具并继续任务。

用户确认后，本节才写入学习文档。

#### 当前边界

本功能点没有伪装以下能力：

- `_ActiveRun` 和事件队列仍只存在于单进程内，尚无多 Worker 租约、心跳或远程
  取消命令。
- SSE 事件尚未进入 Event Store，断线后不能通过 Last-Event-ID 重放。
- 任意同步阻塞第三方工具不能被 asyncio 安全硬杀；生产工具应提供异步实现，
  高风险阻塞任务应放入独立进程或 Sandbox。
- 取消不执行回滚；已经提交的消息和工具副作用仍然保留。
- 当前修复结构化 tool_calls；未来接入更多模型供应商时，还要处理无效调用 ID、
  非法工具名、原始 provider payload 和更多孤儿分支。
- 尚无认证主体、Thread 所有权和 Run 取消授权。

### 功能点 9.12 小结

完成该功能点后，已经掌握：

- 为什么关闭 SSE 不等于取消服务端 Agent Run。
- 为什么 Run 执行 Task 必须与事件订阅分离。
- `abort_event`、`task.cancel()` 和持久化终态分别解决什么问题。
- 为什么启动注册与 Task 附加之间不能留下 `await` 窗口。
- 如何保证事件先持久化后发布，并处理不可强杀的 SQLite 线程写入。
- 如何定义重复取消、迟到取消和非本 Worker Run 的明确语义。
- 前端为什么必须等待 `run_interrupted`，而不是收到 204 就立即关闭 SSE。
- 为什么中断工具节点会产生 dangling tool calls。
- 为什么工具消息修复必须位于模型边界，并保持 checkpoint 与产品历史不变。
- 如何通过真实故障同时检查 application database 与 checkpoint database。

下一功能点将实现正式的 Prompt Builder 与 SystemMessage，为 Agent 产品身份、基础
行为和后续动态模型配置建立可信的服务端边界。

## 功能点 9.13：版本化 Prompt Builder 与可信 SystemMessage 边界

#### 本功能点目标

此前 Mini Deer 已经能通过真实 DeepSeek 模型完成多轮对话和工具循环，但 Agent
Runtime 没有正式的产品级 System Prompt。模型可能根据预训练语料自称 Claude、
ChatGPT 或其他助手，也没有统一声明工具结果、安全和保密边界。

本功能点只建立一个可独立验证的能力：

```text
可信服务端配置与真实工具注册表
    → 版本化 Prompt Builder
    → 唯一且位于首位的 SystemMessage
    → 同步与异步模型调用
```

System Prompt 定义的是 Mini Deer Agent 产品身份，不是底层模型身份。模型供应商和
模型名称继续由 `Settings → create_chat_model()` 决定，不能混入 Prompt 模板。

#### 与 DeerFlow 的对应关系

DeerFlow 的 `agents/lead_agent/prompt.py` 使用 `apply_prompt_template()` 构建 Lead
Agent 的静态系统提示，并根据 Agent、Skills、Sub-Agent 和运行配置生成对应片段。
`client.py` 则把 `create_chat_model(...)`、真实工具列表和
`apply_prompt_template(...)` 的结果分别传入 Agent 工厂。这说明模型构造、工具
注册和 Prompt 组装是相邻但不同的职责。

DeerFlow 的 `SystemMessageCoalescingMiddleware` 还在最终模型请求边界合并多个
SystemMessage，使严格 OpenAI-compatible 后端只收到一个位于首位的系统消息。
该中间件只修改请求视图，不重写持久化会话状态。

Mini Deer 保留了这两个关键设计思想，但按当前规模实现更小的正式边界：

```text
DeerFlow apply_prompt_template
    ↔ Mini Deer DefaultAgentPromptBuilder

DeerFlow create_chat_model 与 system_prompt 分开传入
    ↔ Mini Deer create_chat_model 与 AgentPromptBuilder 分离

DeerFlow SystemMessageCoalescingMiddleware
    ↔ Mini Deer prepare_model_messages
```

Mini Deer 当前没有 Skills、Sub-Agent 和动态日期等多个系统片段，因此不需要复制
DeerFlow 的全部模板和缓存机制；但接口已经允许未来替换 Builder 或扩展上下文。

#### Prompt Builder 的稳定契约

`agents/prompts/contracts.py` 定义三个边界类型：

- `AgentPromptContext`：保存可信的 Agent 名称和可用工具名称。
- `BuiltAgentPrompt`：同时返回版本号和最终 `SystemMessage`。
- `AgentPromptBuilder`：允许不同 Agent 或未来 Prompt 版本替换默认实现。

`BuiltAgentPrompt` 不只返回字符串，因为 Prompt 版本是 Run 可追溯性的一部分。当前
版本为：

```text
mini-deer-agent/system/v1
```

版本尚未写入产品 Run 记录，但构建结果已经显式携带版本，未来不需要重新修改模板
与 Runtime 的职责边界。

#### 模板只定义产品身份

`agents/prompts/templates.py` 把模板分成四个结构块：

- `<identity>`：声明 Mini Deer Agent 产品身份，并禁止猜测底层模型名称。
- `<behavior>`：区分事实、工具结果与推断，不伪造外部操作。
- `<tool_policy>`：只有收到对应 ToolMessage 才能声称工具成功。
- `<confidentiality>`：禁止泄露密钥和系统内部指令。

模板刻意不包含 `deepseek`、`claude` 或 `openai`。因此以后修改模型配置不会要求
修改产品身份 Prompt，模型回复的自我介绍也不能覆盖服务端事实。

#### 不可信动态值的规范化

`agents/prompts/builder.py` 在格式化模板之前处理动态值：

1. Agent 名称去除首尾空白、限制长度并执行 HTML 转义。
2. 工具名称去除空白、限制长度并只允许安全标识符字符。
3. 工具名称去重和排序，生成确定的 Prompt 文本。

即使这些值当前来自服务端配置，也不能让特殊字符闭合结构标签或伪造一个新的
Prompt 区块。稳定排序还使相同配置生成完全相同的前缀，便于测试、审查和未来使用
模型前缀缓存。

#### 工具清单必须来自真实注册表

`build_agent_graph()` 只调用一次 `get_agent_tools()`，然后同时把同一集合用于：

```text
真实工具注册表
    ├── tool.name → AgentPromptContext.available_tool_names
    ├── bind_tools(agent_tools) → 模型可请求的工具契约
    └── ToolNode(agent_tools) → 实际可执行工具
```

调用方即使传入自定义 `prompt_context`，`available_tool_names` 也会被真实注册表覆盖。
这样 Prompt 声称的能力、模型绑定的 schema 和 ToolNode 能执行的函数不会发生漂移。

#### 唯一 SystemMessage 的模型视图

`agents/middleware/model_messages.py` 的 `prepare_model_messages()` 在每次模型调用前：

1. 先修复中断历史中的 tool call 与 ToolMessage 顺序。
2. 从本次模型视图移除 checkpoint 中可能残留的旧 SystemMessage。
3. 把当前 Prompt Builder 生成的可信 SystemMessage 放在第一位。
4. 返回只供本次模型请求使用的新列表。

因此严格 OpenAI-compatible 接口始终看到：

```text
[当前可信 SystemMessage, Human/AI/Tool 历史...]
```

SystemMessage 不作为节点新增消息返回，也不写入 LangGraph `MessagesState`。刷新、
恢复和多轮调用不会在 checkpoint 中不断累积系统消息；旧历史如果已经含有系统消息，
也只在调用视图中移除，不篡改持久化事实。

#### 同步与异步链路使用同一个 Prompt

`agents/main/graph.py` 在构图时只构建一次 Prompt，再把同一个
`built_prompt.system_message` 注入 `model_node` 和 `async_model_node`：

```text
DefaultAgentPromptBuilder.build
    → built_prompt.system_message
        ├── model_node → model.invoke
        └── async_model_node → model.ainvoke
```

CLI/测试的同步入口与 Web Run 的可取消异步入口因此不会出现身份或规则差异。
节点仍只返回本次 AIMessage，`MessagesState` reducer 继续负责追加真实对话历史。

#### 自动化验证

测试保护了以下契约：

- Prompt 版本稳定，且包含 Mini Deer Agent 产品身份。
- 模板不包含 DeepSeek、Claude 或 OpenAI 等具体底层模型名称。
- 工具名称稳定排序、去重，非法名称被拒绝。
- Agent 名称中的结构字符会被转义。
- 每次模型请求只有一个位于首位的可信 SystemMessage。
- dangling tool call 修复仍在 SystemMessage 注入后保持合法消息顺序。
- Prompt 工具清单来自实际注册表，不能由调用方伪造。
- 同步和异步模型节点收到完全相同的 Prompt 规则。
- SystemMessage 不进入 checkpoint，历史恢复不会重复累积。
- Run、取消和天气工具链路没有因 Prompt 接入发生回归。

最终自动化结果：

```text
后端测试：63 passed
前端测试：62 passed
TypeScript typecheck：通过
ESLint：通过
Prettier：通过
生产 build：通过
```

#### 真实运行验证

用户重启后端，并在真实浏览器、真实 DeepSeek 与 Open-Meteo 链路中完成验证，确认：

- 询问“你是谁？”时，Agent 以 Mini Deer Agent 的产品身份回答，不再自称 Claude。
- 询问“你是什么模型？”时，不猜测具体底层模型名称，并以服务端运行信息或产品
  界面作为可信来源。
- 要求使用天气工具查询北京当前天气时，真实工具调用和最终回答仍然正常完成。

用户确认后，本节才写入学习文档。

#### 当前边界

本功能点没有伪装以下能力：

- Prompt 版本尚未作为配置快照保存到产品 Run 记录。
- 前端尚未从可信 Run 元数据展示实际模型名称。
- 当前模板只有一个默认版本，尚无管理后台、灰度发布或在线版本切换。
- Prompt 约束能改善模型行为，但不是权限系统，不能替代 Tool Runtime、审批和
  Sandbox。
- Prompt injection 不能仅靠自然语言模板彻底解决，外部输入仍需代码级校验和权限
  隔离。

### 功能点 9.13 小结

完成该功能点后，已经掌握：

- 为什么 Agent 产品身份与底层模型身份必须分离。
- 为什么模型工厂不能负责拼接产品 Prompt。
- 如何用 Protocol、上下文和版本化结果建立可替换的 Prompt Builder。
- 为什么动态 Prompt 值即使来自服务端也需要转义、校验和稳定排序。
- 为什么 Prompt 中的工具清单必须来自真实工具注册表。
- 为什么严格模型接口只应收到一个位于首位的 SystemMessage。
- 为什么 SystemMessage 应投影到模型调用视图，而不是不断写入 checkpoint。
- 如何让同步 CLI 与异步 Web Run 使用完全相同的 Prompt。
- 为什么模型自然语言自称仍然不能作为 provider 或运行配置证据。

Prompt Builder 已完成源码、自动化检查和真实浏览器验证。项目按用户要求在此暂停，
不自动进入 Event Store、Thread 最近列表或其他后续功能。

## 功能点 9.14：最近 Thread 服务端列表 API

#### 本功能点目标

此前前端只在 `localStorage` 保存当前设备选择的 Thread ID。产品数据库已经持久化
多个 Thread，但服务端没有正式列表接口，因此页面无法取得最近会话。

本功能点只建立一个可独立验证的服务端能力：

```text
application.sqlite 中的 Thread 产品记录
    → 按最近活动时间稳定排序
    → GET /api/v1/threads?limit=20
    → ThreadResponse[]
```

暂不实现 Thread 标题、搜索、分页、前端列表和旧 Thread 切换。

#### 与 DeerFlow 的对应关系

DeerFlow 正式 Gateway 的 `POST /api/threads/search` 不扫描 LangGraph checkpoint，
而是通过 `ThreadMetaStore.search()` 查询独立 Thread metadata store。SQL 实现使用：

```text
pinned DESC
    → updated_at DESC
    → thread_id DESC
```

Memory 实现也保持相同排序语义。DeerFlow 的嵌入式 `client.list_threads()` 仍存在
遍历 Checkpointer 的旧路径，但 Mini Deer 对照的是正式 Gateway 产品边界：
checkpoint 保存 Agent 执行快照，不能作为产品 Thread 列表、所有权和标题的稳定事实
来源。

Mini Deer 当前没有置顶、标题、搜索和认证，因此只实现 DeerFlow 搜索能力的最小
子集：查询产品数据库并按最近活动时间排序，不伪造尚未落地的字段。

#### Application Service 与仓储端口

`application/conversations.py` 在 `ConversationRepository` Protocol 中增加：

```python
def list_threads(self, *, limit: int) -> tuple[ThreadRecord, ...]: ...
```

`ConversationHistoryService.list_threads()` 只编排用例，不感知 FastAPI、SQLite 表名
或 JSON。HTTP、CLI 和未来其他入口可以复用同一查询边界。

#### SQLite v2 增量迁移

列表查询的正式排序为：

```sql
ORDER BY updated_at DESC, thread_id DESC
```

为了避免 Thread 增长后全表扫描和临时排序，v2 迁移创建完全匹配的索引：

```sql
CREATE INDEX IF NOT EXISTS idx_threads_recent
ON threads(updated_at DESC, thread_id DESC)
```

迁移必须逐版执行。若真实 `application.sqlite` 已经登记 v1，仅修改旧建表语句不会
创建新索引。新的 `_MIGRATIONS` 会跳过已存在版本，再执行并登记 v2，因此现有
Thread、Run、Message 和 Tool 历史无需删除或重建。

`thread_id DESC` 是必要的确定性次级排序：多个 Thread 可能具有相同时间字符串，
只按 `updated_at` 会导致返回顺序不稳定，并为未来游标分页制造重复或遗漏。

#### HTTP 接口与完整调用链

Router 新增：

```http
GET /api/v1/threads?limit=20
```

FastAPI 把 `limit` 限制为 1 至 100。Router 通过依赖取得应用生命周期中的共享
`ConversationHistoryService`，不能在请求内自行打开数据库。

完整调用链为：

```text
Uvicorn lifespan
    → 打开 application.sqlite
    → SqliteConversationRepository._setup
    → 应用 v2 迁移并创建 ConversationHistoryService

浏览器 GET /api/v1/threads
    → FastAPI 校验 limit
    → get_conversation_history_service
    → ConversationHistoryService.list_threads
    → SqliteConversationRepository.list_threads
    → idx_threads_recent
    → ThreadRecord tuple
    → ThreadResponse[]
    → JSON
```

该查询不会调用 DeepSeek、LangGraph、Checkpointer、天气工具或 RunExecutionManager。
同步 Router 由 FastAPI 在线程池执行，仓储再使用 `RLock` 保护共享 SQLite 连接。

#### 自动化验证

仓储测试创建三个 Thread，然后主动删除 v2 索引和迁移记录来模拟旧数据库，固定
`updated_at` 后重新打开仓储，确认：

- v1 数据完整保留并自动升级到 v2。
- 相同时间的 Thread 按 `thread_id DESC` 确定排序。
- `limit` 正确截断结果。
- `EXPLAIN QUERY PLAN` 实际命中 `idx_threads_recent`。

HTTP 集成测试确认正式 Run 完成后，列表与单 Thread 查询读取相同产品事实；OpenAPI
也只公开正式版本化路径。

最终自动化结果：

```text
后端测试：64 passed
```

前端源码没有改动，本轮没有把既有前端检查重复计入该功能结果。

#### 真实运行验证

用户重启真实后端，在前端创建并完成第二个 Thread 的 Run。随后读取真实接口确认：

- `limit=20` 返回两个 Thread，HTTP 状态为 200。
- 两个 Thread 按 `updated_at DESC` 排列，最新活动项位于第一位。
- `limit=1` 只返回一项，且与完整列表首项一致。
- 两个 Thread 的最终状态均为 `idle`。
- 响应只包含公开的 `thread_id`、`status`、`created_at` 和 `updated_at`。

用户按约定回复继续后，本节才写入学习文档。

#### 当前边界

本功能点仍未实现：

- Thread 标题、置顶、归档和搜索。
- offset 或游标分页。
- Principal 所有权过滤和多租户隔离。
- 前端最近会话列表与旧 Thread 切换。

当前接口只适用于本地单用户开发边界。公开部署前必须按可信 Principal 过滤查询，
不能向调用者返回其他用户的 Thread。

### 功能点 9.14 小结

完成该功能点后，已经掌握：

- 为什么产品 Thread 列表不能通过扫描 LangGraph checkpoint 实现。
- DeerFlow 正式 ThreadMetaStore 与旧嵌入式 checkpoint 列表路径的区别。
- 如何通过 Protocol 和 Application Service 隔离 HTTP 与 SQLite。
- 为什么最近列表需要 `updated_at + thread_id` 的确定性排序。
- 为什么新索引必须使用增量数据库迁移，而不是修改已经执行过的 v1。
- 如何通过 `EXPLAIN QUERY PLAN` 验证查询确实使用目标索引。
- 如何从服务启动、依赖注入、仓储查询一直追踪到最终 JSON 响应。

最近 Thread 服务端列表已经完成源码讲解、自动化检查和真实运行验证。下一原子功能
可以在独立确认后实现前端最近会话列表，但不会在本功能点中自动开始。

## 功能点 9.15：前端最近会话列表与 Thread 切换

#### 本功能点目标

功能点 9.14 已经提供正式最近 Thread API，但前端侧栏仍只能展示当前本地 Thread。
本功能点把服务端列表、设备选择和现有历史恢复链路连接为一个完整可观察行为：

```text
加载最近 Thread
    → 侧栏展示真实产品记录
    → 点击已有 Thread
    → 持久化设备选择
    → 重置旧 Thread 运行状态
    → 加载并展示目标 Thread 历史
    → 刷新后仍恢复同一 Thread
```

列表与切换合并为一个原子功能，因为只展示不可操作的列表不能验证 Thread 身份、
历史恢复和状态隔离是否真正连通。

#### 与 DeerFlow 的对应关系

DeerFlow 前端把职责分为：

- `useThreads()`：调用 Thread 搜索接口并管理 Query 缓存。
- `VirtualThreadList`：渲染稳定 Thread 列表。
- Thread `Link`：把选择转换为 URL 导航。
- `useThreadChat()`：从路由读取当前 `thread_id`，处理 `/new` 临时 Thread。
- `useThreadHistory/useThreadStream`：在 Thread 身份改变后重建历史和运行状态。

Mini Deer 保留相同职责边界，但当前尚无 React Router，因此身份载体不同：

```text
DeerFlow：URL path → current thread_id
Mini Deer：localStorage → current thread_id
```

Mini Deer 的列表 client、历史 hook 和聊天 reducer 都不依赖 `localStorage`。未来把
当前身份迁移到 URL 时，只需替换选择入口，不需要重写这些下游能力。

#### 不可信列表响应的运行时校验

`features/threads/api/thread-list.ts` 定义 `ThreadSummary` 的网络适配边界。
`parseThreadList()` 在 JSON 进入 UI 前验证：

- 顶层必须是数组。
- 每项必须是 JSON object。
- `thread_id` 必须是 UUID，并统一为小写。
- `status` 只能是 `idle`、`busy` 或 `error`。
- `created_at` 和 `updated_at` 必须是有效日期时间。
- Thread ID 不能重复。

通过校验后，snake_case 网络字段才投影为 camelCase 领域字段。TypeScript 类型不能
替代这一步，因为 `response.json()` 在运行时仍是不可信数据。

`fetchThreadList()` 请求：

```http
GET /api/v1/threads?limit=20
Accept: application/json
Cache-Control: no-store（fetch cache 选项）
```

它在发出请求前限制 `limit` 为 1 至 100，并把错误收敛为
`invalid_request/http_error/invalid_response/network_error/aborted`，避免组件解析
原始 HTTP 异常或展示内部细节。

#### 最近列表异步生命周期

`features/threads/model/use-thread-list.ts` 只管理列表查询状态：

```text
items + isLoading + error + retry
```

首次加载和显式重试都会创建新的 `AbortController`。组件卸载或 revision 改变时取消
旧请求，旧结果不能继续写入页面。刷新期间保留已有 items，网络暂时失败也不会破坏
聊天主区域。

#### 选择已有 Thread 的设备仓储

`CurrentThreadRepository` 新增 `selectCurrentThreadId()`：

1. 对外部 ID 去除空白并统一小写。
2. 在写入前执行 UUID 校验。
3. 更新 Repository 当前生命周期内的内存选择。
4. 写入版本化 `localStorage` key。
5. 返回规范化后的 Thread ID。

无效 ID 不能进入历史 API、Run API、日志或页面刷新状态。选择先持久化再更新 React
状态，因此刷新浏览器会恢复刚才选中的旧 Thread。

#### 侧栏展示与可信边界

`ConversationRail` 现在展示真实 `ThreadSummary`：

- 使用 Thread ID 前八位作为当前无标题阶段的稳定标签。
- 使用 `aria-current="page"` 标记当前 Thread。
- 展示服务端状态和更新时间。
- 列表失败时提供独立重试，不阻断聊天页面。
- 当前本地 Thread 尚无产品记录时显示“新对话”占位。
- 当前页面有活动 Run 或目标 Thread 为 `busy` 时禁止切换。

当前没有 Thread 标题领域字段，因此 UI 不读取第一条消息或生成只存在于浏览器的
假标题。标题将在服务端具有正式事实来源后单独实现。

#### Thread 切换的完整状态链路

`ChatPage.selectThread()` 先拒绝活动 Run 和重复选择，再调用仓储保存身份并更新
`threadId`。之后复用已经验证过的 Thread 级状态边界：

```text
setThreadId(target)
    ├── useChatRun 观察 Thread 改变
    │     ├── abort 旧 operation（防御层）
    │     └── dispatch thread/reset
    │           → 清空旧 timeline、run ID、phase、error 和工具状态
    ├── useThreadHistory 取消旧查询
    │     ├── 重建目标 Thread 分页状态
    │     ├── GET /threads/{target}/messages
    │     └── Thread ID 双重检查后 hydrateHistory
    ├── Composer key 改变并重新挂载
    │     └── 清除旧 Thread 未发送草稿
    └── ConversationRail 更新当前高亮
```

UI 禁止活动 Run 中切换是第一层安全边界；`useChatRun` 仍会在身份变化时 abort 旧
operation，防止未来其他入口绕过按钮。历史 hook 同时使用 AbortController 和
Thread ID 校验，旧请求即使迟到也不能覆盖目标会话。

#### 新 Thread 如何进入列表

点击“新会话”只在设备创建一个新 UUID，此时服务端没有产品记录，侧栏显示本地
“新对话”。首个 Run 开始后，后端创建 Thread；当 Run 进入 completed、failed 或
cancelled 终态时，`ChatPage` 刷新最近列表。

`lastRefreshedRunId` 防止 React effect 或重复渲染为同一 Run 多次刷新：

```text
Run 终态
    → application.sqlite 已有最新事实
    → retryThreadList()
    → 新 Thread 出现在侧栏
    → updated_at 最新，因此位于列表顶部
```

#### 自动化验证

新增和加强的测试覆盖：

- 列表 UUID、状态、日期与重复身份校验。
- 越界 `limit` 在网络请求前被拒绝。
- 列表失败后显式重试。
- 已有 Thread 选择的规范化与持久化。
- 无效选择不能污染当前 Thread。
- 点击列表后只展示目标 Thread 历史。
- 原 Thread 消息从切换后的页面移除。
- 当前项具有 `aria-current="page"`。
- 活动 Run 中“新会话”和 Thread 切换同时禁用。
- 新会话仍使用独立 Thread ID。
- Thread 切换后 Composer 使用新实例，不继承旧草稿。
- 旧历史请求迟到时不能覆盖目标 Thread。

最终自动化结果：

```text
前端测试：11 files / 70 passed
TypeScript typecheck：通过
ESLint：通过
Prettier：通过
生产 build：通过
```

#### 真实运行验证

用户在真实浏览器中完成并确认本功能符合预期：

- 侧栏显示服务端返回的真实最近会话，当前 Thread 正确高亮。
- 点击旧 Thread 后，顶部 Thread ID 和消息历史切换到目标会话。
- 原会话历史没有残留在目标页面。
- 刷新浏览器后仍恢复刚才选择的 Thread 和历史。
- 活动 Run 期间不能创建新会话或切换到其他 Thread。
- Run 结束后列表恢复可操作，并反映最新活动顺序。
- 本地新会话完成首个 Run 后进入正式最近列表。

用户明确回复“已验证”后，本节才写入学习文档。

#### 当前边界

本功能点没有实现：

- 人类可读 Thread 标题。
- URL 路由和浏览器前进/后退导航。
- 服务端列表分页与无限滚动。
- Thread 删除、归档和置顶。
- Principal 所有权过滤和多租户隔离。
- 多标签页之间的选择状态同步。

### 功能点 9.15 小结

完成该功能点后，已经掌握：

- DeerFlow 如何用 URL、列表 Query 和 Thread hooks 组合会话导航。
- 如何在无路由阶段用独立 Repository 保存设备当前 Thread。
- 为什么 TypeScript 类型不能替代网络 JSON 运行时校验。
- 为什么 Thread 切换必须同时处理运行状态、历史请求、工具状态和输入草稿。
- 为什么 UI 禁止切换和 hook 内 abort 应同时存在。
- 如何用 AbortController 与 Thread identity 双重防止迟到响应污染。
- 为什么新 Thread 必须等产品记录落库后才进入正式列表。
- 如何在 Run 终态刷新列表并防止同一终态重复刷新。

前端最近会话列表与 Thread 切换已经完成源码讲解、自动化检查和真实浏览器验证。
项目在此暂停，等待用户明确指定下一原子功能。

# 第 10 课：Run 流可靠性与断线恢复

## 功能点 10.1：服务端 SSE 注释心跳

#### 本功能点目标

Agent 在等待模型首 token、长时间工具调用或外部 HTTP 响应时，可能暂时没有任何
业务事件。只有 `Connection: keep-alive` 响应头不能保证反向代理或客户端不会把
这种静默连接按 idle timeout 关闭，因此需要在不改变业务协议的前提下周期发送字节。

本功能点的可观察契约是：连续 15 秒没有 `RunEvent` 时发送标准 SSE 注释
`: heartbeat`，业务事件到达后继续原来的事件流。

#### 与 DeerFlow 的对应关系

DeerFlow 把心跳分成三层：

1. `stream_bridge/base.py` 定义独立 `HEARTBEAT_SENTINEL`。
2. `MemoryStreamBridge.subscribe()` 在等待 Condition 超时时产生该哨兵。
3. `gateway/services.py::sse_consumer()` 把哨兵投影为 `: heartbeat\n\n`。

这说明心跳是连接保活信号，不是 Agent 领域事实。DeerFlow 的 StreamBridge 还承担
缓冲、跨进程和重放职责；Mini Deer 尚未实现 Event Store，因此只把当前必需的
静默计时与 SSE 注释投影放进传输编码器，不复制尚未需要的桥接系统。

#### Mini Deer 的实现

`streaming/sse.py::aiter_run_sse_frames()` 新增默认 15 秒的
`heartbeat_interval`：

```text
等待同一个 anext(events) Task
    ├── 业务事件先到 → 编码 id/event/data RunEvent 帧
    ├── 15 秒先到    → 发送 : heartbeat，继续等待同一个 Task
    └── 输出流关闭   → 取消待处理 Task，并关闭上游 iterator
```

实现使用 `asyncio.wait()`，而不是直接对 `anext()` 使用
`asyncio.wait_for()`。后者在超时时会取消上游读取，可能触发
`RunExecutionManager._subscribe()` 的 `finally`，从而把一次普通静默误判成
`client_disconnected`。保留同一个 Task 可以跨多个心跳周期继续等待真实事件。

心跳帧没有 `id`、`event`、`data` 或 `sequence`，因此：

- 不创建 `RunEvent`。
- 不写入 application SQLite。
- 不推进业务 sequence。
- 不参与未来 Last-Event-ID 重放。
- 不会被前端展示成聊天消息。

正式 `/api/v1/threads/{thread_id}/runs/stream` 已经通过
`aiter_run_sse_frames()` 编码 Run 流，所以不需要改变 Router 或公开请求契约。
旧 `/chat/stream` 兼容接口保持原字节行为，没有在本轮扩展。

#### 连接关闭与资源生命周期

心跳实现会为待处理的 `anext()` 创建一个 Task。若 StreamingResponse 因浏览器
断开而关闭输出生成器，`finally` 必须取消并等待该 Task，再关闭上游 iterator。
这样取消才能继续抵达 `RunExecutionManager._subscribe()`，并复用已经验证过的
`cancel_run(reason="client_disconnected")` 终态链，而不会留下孤儿读取任务。

#### 前端兼容性

Mini Deer 的 `SseParser` 已遵守 SSE 规范：冒号开头的行属于注释，只有包含
`data` 字段的 frame 才会产生业务事件。本轮补充了“独立心跳注释后继续解析业务
事件”的测试，确认心跳不会进入 `parseChatRunEvent()` 或 reducer。

#### 自动化与真实验证

新增测试覆盖：

- 静默期发送精确的 `: heartbeat\n\n`。
- 心跳前后的业务 sequence 保持 1、2 连续。
- 心跳后业务事件仍能从同一个上游读取任务抵达。
- 客户端关闭输出流时，被阻塞的事件源执行清理。
- 前端忽略独立心跳，并继续解析紧随其后的业务事件。

最终自动化结果：

```text
后端测试：66 passed
前端测试：11 files / 71 passed
ESLint：通过
Prettier：通过
TypeScript typecheck：通过
生产 build：通过
```

用户按照当前窗口给出的真实终端步骤运行后，明确回复“已验证”。本节在该确认后
才写入学习记录。

#### 当前边界

本功能点只证明“服务端在静默期仍发送字节”，不代表：

- Agent 或模型一定在正常推进。
- 前端已经根据心跳判断连接卡死。
- 断线后可以自动重连。
- 服务端支持 Last-Event-ID 或事件重放。
- 多 Worker 之间具有共享 Run 事件流。

### 功能点 10.1 小结

完成该功能点后，已经掌握：

- 为什么 `Connection: keep-alive` 不能代替实际心跳字节。
- 为什么传输心跳不能占用业务事件 sequence。
- DeerFlow 如何用 StreamBridge 哨兵隔离等待机制与 SSE 文本投影。
- 为什么超时等待不能意外取消正在进行的上游事件读取。
- 如何在客户端断开时清理等待 Task，并保留 Run 的可信终态链。
- 为什么前端 parser 应忽略注释，而 reducer 不应认识 heartbeat 业务事件。

服务端 SSE 心跳已经完成源码讲解、自动化检查和用户真实终端验证。下一原子功能
可以利用“最后收到任何 SSE 字节的时间”实现前端断线检测，但不会在本节中混入。

## 功能点 10.2：前端 SSE 静默超时与连接异常提示

#### 本功能点目标

服务端每 15 秒发送一次 SSE 注释心跳后，前端已经可以把“长期收不到任何字节”
作为连接异常信号。本功能点建立以下可观察闭环：

```text
SSE 响应已经建立
    → 连续 45 秒没有任何网络字节
    → 取消 response body reader
    → 产生可重试 stream_inactive
    → Run UI 进入 failed
    → 展示连接异常提示并恢复输入能力
```

业务事件、注释心跳和暂时尚未闭合的半个 frame 都属于连接活动，都会重新开始
45 秒计时。

#### 与 DeerFlow 的对应关系

DeerFlow 使用 LangGraph SDK 消费 Run 流，并在 `core/api/api-client.ts` 包装
`runs.stream()` 与 `joinStream()`。当服务端报告 `StreamGap` 时，
`recoverStreamReplayGaps()` 会读取持久化 Thread state，再携带 `Last-Event-ID`
加入同一 Run。

Mini Deer 当前没有 Event Store、重放游标或重新加入 Run 的 API，因此不能直接
复制 DeerFlow 的自动重连。否则断线期间丢失的事件可能无法补齐，页面却会错误地
宣告恢复成功。本功能只检测静默、明确失败和释放连接，不伪装已具备重放能力。

#### 为什么必须在字节读取层计时

`IncrementalSseParser` 按 SSE 规范忽略冒号注释，并且只有包含 `data` 字段的 frame
才会产生 `SseFrame`。因此服务端发送的 `: heartbeat` 不会进入 ChatRunEvent 或
reducer。

如果只在业务 frame 抵达时刷新计时器，正常心跳也无法续期，长时间工具调用会被
误判为断线。计时必须放在 `ReadableStreamDefaultReader.read()` 边界：只要任意
字节抵达，就证明连接仍有传输活动。

#### 共享 SSE 读取器

`shared/api/sse-parser.ts` 新增 `SseStreamOptions` 和独立的
`SseInactivityTimeoutError`。网络读取通过 `Promise.race()` 同时等待：

```text
reader.read() 先完成
    → 返回 chunk
    → 清除本轮定时器
    → 下一次 read 建立新周期

静默定时器先完成
    → 抛出 SseInactivityTimeoutError
    → finally 取消 reader
    → 释放底层 HTTP 连接
```

静默错误不继承 `SseParseError`，因为“没有字节”与“收到非法格式字节”是不同故障。
parser 的超时选项保持可选，只有聊天 Run 客户端按自己的策略启用，其他未来 SSE
消费者不会被隐式套用聊天超时。

#### 聊天客户端错误分类

`features/chat/api/chat-stream.ts` 使用 45 秒默认静默上限，相当于允许服务端连续
错过三个 15 秒心跳周期，为浏览器调度、短暂网络抖动和代理缓冲留出余量。

客户端错误保持明确分类：

- 用户主动 Abort：`aborted`，不可重试的本地取消语义。
- 45 秒无任何字节：`stream_inactive`，可重试。
- fetch 或 TCP 直接失败：`network_error`，可重试。
- SSE 或 RunEvent 格式损坏：`stream_protocol_error`。
- 流关闭但没有可信终态：`incomplete_stream`。

底层超时正文不会直接进入 UI，`stream_inactive` 使用固定公开文案：
“长时间未收到 Agent 心跳或事件，连接可能已经中断”。

#### 页面状态链

错误沿现有职责链传播，不增加组件局部布尔状态：

```text
streamChatRun 抛出 ChatStreamClientError
    → useChatRun 确认仍是当前 Thread/operation
    → dispatch run/client-failed
    → reducer 设置 phase=failed、收束 pending 工具卡
    → ChatPage 的 run-error 展示固定文案和重试提示
    → failed 不属于 active phase，Composer 自动恢复输入
```

旧 Thread 或旧 operation 的迟到错误仍会被 hook 的身份检查拒绝。

#### 自动化与真实验证

新增和调整的测试覆盖：

- 永久静默流会在配置的短超时后失败。
- 静默失败会调用底层 `ReadableStream.cancel()`。
- 注释心跳虽然不产生业务 frame，但会重置静默计时。
- 聊天 API 将底层超时映射为可重试 `stream_inactive`。
- 页面展示连接异常与“可以稍后重新发送”，并恢复输入框。

最终自动化结果：

```text
前端测试：11 files / 74 passed
ESLint：通过
Prettier：通过
TypeScript typecheck：通过
生产 build：通过
```

用户使用真实浏览器和临时静默 SSE 服务完成验证，随后明确回复“已验证，继续”。
本节在该确认后才写入学习记录。

#### 当前边界

本功能尚未实现：

- fetch 在收到响应头之前的连接建立超时。
- 自动重连同一 Run。
- Last-Event-ID 和断线事件重放。
- 断线后查询服务端 Run 的最终真实状态。
- 多 Worker 共享 Run 流。

### 功能点 10.2 小结

完成该功能点后，已经掌握：

- 为什么心跳注释必须在业务 parser 之前参与连接活动计时。
- 如何用 `Promise.race()` 为单次 `reader.read()` 建立静默上限。
- 为什么任意网络字节都应该续期，而不是只认完整业务事件。
- 如何区分主动取消、网络失败、协议损坏、流不完整和静默超时。
- 如何通过既有 hook、reducer 和 UI 状态链呈现连接异常。
- 为什么没有 Event Store 时不能把自动重连伪装成可靠恢复。

前端 SSE 静默检测已经完成源码对照、自动化检查和用户真实浏览器验证。下一功能
应先建立断线后可查询的服务端 Run 事实，再讨论自动重连或事件重放。

## 功能点 10.3：单个 Run 详情查询与 Thread 归属校验

#### 本功能点目标

SSE 连接异常后，客户端不能仅凭本地状态判断服务端 Run 是否已经结束。本功能点
提供一个只读取 application database 持久化事实的精确查询入口：

```text
GET /api/v1/threads/{thread_id}/runs/{run_id}
```

成功时返回既有 `RunResponse`；Run 不存在或不属于路径中的 Thread 时，统一返回
`run_not_found` 404。

#### 与 DeerFlow 的对应关系

DeerFlow 的同名路由先用当前用户身份按 `run_id` 查询记录，再检查
`record.thread_id != thread_id`。记录缺失和路径归属不匹配都按 404 处理，最后通过
专用响应投影脱敏配置中的秘密。

Mini Deer 当前仍是本地单用户边界，没有复制尚不存在的认证装饰器和用户过滤；但
保留了同一个关键不变量：知道一个 `run_id`，不等于可以绕过路径 Thread 查询它。
公开响应也继续使用较窄的 `RunResponse`，不暴露执行配置或数据库内部字段。

#### 为什么查询持久化 Run，而不是活动任务表

进程内活动 Run 注册表只适合取消当前 Worker 中仍在执行的任务：进程重启后会
丢失，Run 结束后也会清理。application SQLite 中的 `runs` 才保存
`pending/running/completed/failed/cancelled/interrupted` 生命周期事实。

因此详情请求复用仓储已有的 `get_run(run_id)`：

```text
HTTP thread_id + run_id
    → ConversationHistoryService.get_run()
    → SQLiteConversationRepository.get_run(run_id)
    → 得到 RunRecord
    → 校验 RunRecord.thread_id
    → 投影为 RunResponse
```

仓储按 Run 主键查询一次即可。Router 如果先查 Thread 再查 Run，不仅多一次数据库
访问，仍然不能省略 Run 自身的归属检查。

#### 统一 404 的安全边界

应用服务把以下两种情况都收束为 `None`：

- 数据库中没有这个 Run。
- 数据库中存在这个 Run，但它属于另一个 Thread。

Router 随后统一返回固定 `run_not_found`。调用方无法利用不同错误码或错误正文枚举
另一个 Thread 中的 Run。UUID 格式错误仍由 FastAPI 返回 422，因为它属于请求格式
错误，而不是资源查询结果。

#### 自动化与真实验证

测试覆盖：

- OpenAPI 正式公开单 Run 路径。
- SSE Run 完成后可通过 Thread/Run 复合身份查询。
- 单条详情与 Run 列表来自同一个 `RunRecord` 投影。
- 不存在的 Run 返回安全 404。
- 真实 Run 放入错误 Thread 路径时返回完全相同的 404。

最终自动化结果：

```text
后端测试：66 passed
定向契约与持久化集成测试：10 passed
git diff --check：通过
```

用户使用真实 API 验证正常详情、缺失 Run 和 Thread/Run 错配后，明确回复“已验证，
继续原定计划的下一功能点”。本节在该确认后才写入学习记录。

#### 当前边界

本功能点只提供服务端事实入口，尚未实现：

- 前端在 SSE 异常后自动调用该接口。
- `pending/running` Run 的轮询策略。
- 自动重新加入同一个 SSE Run。
- Last-Event-ID、Event Store 和断线事件重放。

### 功能点 10.3 小结

完成该功能点后，已经掌握：

- 为什么 SSE 断线后的状态恢复必须查询持久化事实。
- 为什么单 Run 查询仍需校验路径 Thread 归属。
- 为什么缺失和跨 Thread 错配应该使用相同 404。
- 为什么应用服务适合承载归属规则，而 Router 只负责协议投影。
- 为什么 Run 详情查询不等于自动重连或事件重放。

下一功能点可以让前端在 SSE 连接异常后自动查询该接口，并根据服务端终态修正页面；
如果 Run 仍在执行，则必须使用明确的有限等待策略，不能伪装成已经恢复事件流。

## 功能点 10.4：SSE 断线后自动核对 Run 状态

#### 本功能点目标

功能点 10.3 已经让持久化 Run 状态可以被精确查询，但前端发生 SSE 静默、网络断开
或缺少终止帧时仍只会展示本地连接错误。本功能点把两条已有链路接起来：

```text
SSE 在已取得 Run ID 后异常结束
    → 有限查询 GET /threads/{thread_id}/runs/{run_id}
    → 服务端已经终止：用持久化终态修正页面
    → 服务端仍在执行或查询失败：保留原 SSE 错误
```

它解决的是“连接结果不确定时，核对 Run 最终是否结束”，不是补回断线期间丢失的
消息、工具结果或增量正文。

#### 与 DeerFlow 的对应关系

DeerFlow 的 `frontend/src/core/api/api-client.ts` 在加入既有 Run 流之前，会通过
`runs.get(threadId, runId)` 检查 Run 是否已经处于终态；遇到 `StreamGap` 时，
`recoverStreamReplayGaps()` 还会读取持久化 Thread state，并携带事件游标重新加入
同一个 Run。

Mini Deer 当前只有 Run 生命周期记录，没有 Event Store、事件游标和重新加入接口，
因此只采用 DeerFlow 的第一层原则：网络连接不是 Run 状态的事实来源，必须查询服务端
持久化状态。不能复制后半段重放流程，否则页面可能漏掉正文却错误宣称恢复成功。

#### Run 详情客户端与不可信响应校验

`features/chat/api/chat-stream.ts::fetchChatRun()` 请求功能点 10.3 的复合身份路径，
并在 TypeScript 类型之外执行运行时校验：

- 校验 Run ID、Thread ID、状态、时间与可空错误字段。
- 校验响应中的身份与请求路径完全一致。
- 非 2xx、非法 JSON 或字段不合法都作为查询失败处理，不能写入 reducer。

`reconcileChatRunAfterDisconnect()` 使用有限预算核对：最多查询 5 次、相邻查询间隔
250ms，整个过程最多 5 秒。终态一旦出现就立即返回；预算结束仍为
`pending/running` 时只返回最后快照，不无限轮询。

短暂轮询是为了覆盖浏览器发现断线与服务端完成断开清理、提交最终状态之间的竞争窗口，
而不是后台监控机制。总超时还会中止挂起的详情请求，避免页面留下孤儿网络操作。

#### 哪些错误允许自动核对

`useChatRun()` 只有同时满足以下条件才进入核对：

1. 已经从 SSE 响应头取得可信 Run ID。
2. 错误属于 `stream_inactive`、`network_error` 或 `incomplete_stream`。
3. 当前 Thread 和 operation 身份仍然匹配。

主动取消不查询，因为它已经沿取消 API 处理；协议错误不查询，因为服务端状态不能证明
客户端收到的数据格式正确；响应头之前失败时还没有 Run ID，也不能猜测目标 Run。

#### 持久化终态如何进入页面

Reducer 新增 `run/status-reconciled`，直接消费 Run 详情快照，不伪造一条并不存在的
SSE 事件或 sequence：

```text
completed             → phase = completed
failed                → phase = failed，并采用持久化 error_code
cancelled/interrupted → phase = cancelled
pending/running       → 不覆盖原连接错误
```

查询本身失败或有限预算内仍没有终态时，页面保留最初的 SSE 错误。这能避免“恢复查询
也失败”掩盖真正触发恢复的网络问题。

#### 自动化与真实验证

自动化测试覆盖：

- Run 详情 URL、公开字段、UUID、时间和响应身份校验。
- 活动状态的有限重试、终态提前结束和 5 秒总预算。
- 三类可恢复连接错误触发查询。
- 主动取消、协议错误、无 Run ID 和旧 operation 不触发查询。
- completed、failed、cancelled/interrupted 的 reducer 收敛。
- 默认页面链路在 SSE 缺少终止帧后，通过默认 Run GET 到达完成状态。

最终自动化结果：

```text
前端测试：11 files / 85 passed
ESLint：通过
Prettier：通过
TypeScript typecheck：通过
生产 build：通过
```

真实浏览器的 Network 面板观察到 `stream` 请求之后，前端自动发起了以 Run ID 命名
的详情请求，证明异常分支确实进入自动核对链。用户结合操作过程最终确认本功能按通过
验收；未把截图中没有确认的 HTTP 状态码写成成功事实。

#### 当前边界

本功能点没有实现：

- 断线期间缺失事件的持久化与补发。
- Last-Event-ID 或 sequence 游标重放。
- 重新加入仍在执行的同一个 Run 流。
- 跨 Worker 的共享事件流。
- 长时间后台轮询活动 Run。

### 功能点 10.4 小结

完成该功能点后，已经掌握：

- 为什么 SSE 连接状态与服务端 Run 生命周期状态必须分开。
- 为什么恢复前必须已有可信 Run ID。
- 为什么只有网络不确定性错误适合自动核对，协议错误不适合。
- 如何用有限次数、有限间隔和总超时处理终态持久化竞争窗口。
- 为什么 reducer 应消费状态快照，而不是伪造 SSE sequence。
- 为什么 Run 详情只能修正生命周期，不能替代 Event Store 恢复内容。

SSE 断线状态核对已经完成源码对照、自动化检查和用户真实浏览器验收。下一连续功能点
应从 Event Store 的可查询持久化事实开始，再逐步加入事件游标和重放，不能一次性把
持久化、重新加入和前端恢复全部混在一起。

## 功能点 10.5：RunEvent 持久化与事件查询

#### 本功能点目标

此前 application SQLite 只保存 Run、Message 和 Tool 的当前投影。两个
`ai_delta` 会被拼接成一条 assistant message，因此页面可以恢复最终文本，但无法回答
“sequence 17 当时究竟发送了什么”。功能点 10.5 保存每条公开 `RunEvent` 的原始
envelope，并提供可在后端重启后继续使用的前向游标查询：

```text
RunEvent
    → 同一 SQLite 事务
        ├── 写入 run_events 原始事实
        └── 更新 Run / Message / Tool 当前投影
    → 提交成功
    → 发布到进程内 SSE 队列
```

公开查询接口为：

```http
GET /api/v1/threads/{thread_id}/runs/{run_id}/events
    ?after_sequence=0
    &limit=200
```

#### 与 DeerFlow 的对应关系

DeerFlow 的 `runtime/events/store/base.py::RunEventStore` 定义持久事件必须可查询、
sequence 必须单调递增，`list_events()` 使用 `after_seq` 提供前向游标。
`DbRunEventStore` 使用 SQLAlchemy 数据库表和事务分配 Thread 全局 sequence，
`RunJournal` 从 LangChain callback 收集审计事件并批量 flush。

DeerFlow 的 `GET /threads/{thread_id}/runs/{run_id}/events` 用于审计和调试；真正的
`Last-Event-ID` 临时重放由另一套 `StreamBridge` 完成。内存或 Redis bridge 只保留
有界事件，游标落在保留区之前时返回 `StreamGap`，不会把不完整重放伪装成成功。

Mini Deer 采用同样的职责原则，但不复制 DeerFlow 更宽的审计 catalog：当前直接保存
已经稳定公开的 v1 `RunEvent` envelope。Mini Deer 的 sequence 是单 Run sequence，
所以数据库身份使用 `(run_id, sequence)`，而不是 DeerFlow 的 Thread 全局 sequence。

#### SQLite v3 与事件身份

application SQLite v3 新增 `run_events`，保存：

- `version`
- `event`
- `run_id`
- `thread_id`
- `sequence`
- `message_id`
- `payload_json`
- `created_at`

`(run_id, sequence)` 是主键；`(thread_id, run_id, sequence)` 复合索引服务公开路径的
复合身份和游标查询。迁移按版本幂等执行，既有产品数据库不需要删除。

#### 原始事实与产品投影为什么必须同事务

`SqliteConversationRepository.apply_run_event()` 是 Run 事件进入持久化的唯一入口。
它先验证事件 Run 确实属于 Thread，并确认 Run 尚未终止，然后在同一个事务中：

1. 检查新 sequence 是否恰好等于已存最大值加一。
2. 插入原始 `run_events` 记录。
3. 根据事件更新 Run 状态、拼接 Message 或物化 ToolExecution。

任一步失败，SQLite context manager 会整体回滚。这样不会出现“浏览器收到并能查询原始
事件，但产品消息没更新”，也不会出现“页面历史更新了，原始事件却丢失”的半状态。

严格连续校验同时拒绝重复、倒序和跳号。只依赖唯一主键只能阻止重复 sequence，无法
阻止 1 后面直接写 3；一旦允许缺口，未来重放就无法区分“确实没有 sequence 2”和
“sequence 2 丢失”。因此这里选择失败关闭。

#### 应用服务与安全查询

`RunEventHistoryService` 通过独立 `RunEventStore` Protocol 表达查询职责。当前 Event
Store 与产品历史共享同一物理 SQLite 和适配器，以获得原子事务；逻辑边界仍然独立，
Router 不直接执行 SQL，未来可以更换存储实现。

查询前先读取 Run 并验证 `record.thread_id == path.thread_id`。Run 不存在和属于其他
Thread 都返回同一个 `run_not_found` 404，沿用功能点 10.3 的防枚举边界。
`after_sequence` 是排他游标，结果使用 `sequence ASC`；`limit` 限制为 1 至 500，
避免一次请求无界读取长 Run。

#### 自动化验证

测试覆盖：

- 完整 envelope、message ID、payload 和写入时间不丢失。
- `after_sequence` 分页严格正序。
- 关闭并重新打开 SQLite 后事件仍存在。
- sequence 跳号会让原始事件与消息投影共同回滚。
- 跨 Thread 查询返回与缺失 Run 相同的安全 404。
- OpenAPI 正式公开事件查询路径。
- `EXPLAIN QUERY PLAN` 使用目标复合索引。
- 完整真实 HTTP Run 完成后能查询事件，新应用实例仍能读取相同事件。

最终自动化结果：

```text
后端测试：68 passed
compileall：通过
git diff --check：通过
Ruff：当前虚拟环境未安装，未执行
```

#### 真实运行验证与 URL 排查

用户使用真实 Thread `80951da3-4ee8-4a39-bf46-b4436f096ea5` 和 Run
`e6139aa3-fb15-4d34-9c64-c2ad8104b7c7` 验证。该 Run 共保存 1890 条连续事件：

```text
sequence 1    → run_started
sequence 2…   → ai_delta 等业务事件
sequence 1890 → run_completed
```

前向游标能够分别读取开头和末尾，重启后端后相同事件仍可查询。用户随后明确回复
“已验证继续”。

验证过程出现过两次 422，但都来自请求 URL，而不是 Event Store：

1. 把文档中的 `{thread_id}` 占位符原样放入路径，FastAPI 正确拒绝非法 UUID。
2. 把查询参数分隔符 `&` 写成 `%26`，导致 `after_sequence` 的实际值变成字符串
   `0&limit=3`，FastAPI 正确拒绝将其解析成整数。

这也说明验证说明应尽量提供真实可复制的 URL，并明确区分路径占位符、URL 编码和值的
边界。多个查询参数必须用原始 `&` 分隔；`%26` 表示参数值内部的字面量 `&`。

#### 当前边界

本功能点仍未实现：

- 解析 SSE 请求的 `Last-Event-ID`。
- 把 Event Store 中的事件重新编码并发送到 SSE。
- 活动 Run 从持久历史无缝切换到实时队列。
- 保留期限、裁剪和 `StreamGap`。
- 多 Worker 共享活动事件流。
- Principal 所有权和多租户过滤。

### 功能点 10.5 小结

完成该功能点后，已经掌握：

- 产品当前投影与原始事件事实的区别。
- 为什么原始事件和投影必须在同一事务提交。
- 为什么唯一键之外还要拒绝 sequence 跳号。
- 如何用复合身份、排他游标和正序索引查询单 Run 事件。
- 为什么共享物理数据库不代表应用职责必须混在一起。
- 为什么 Event Store 可查询不等于 SSE 已经支持断线重放。
- 如何从 FastAPI 422 的 `loc/input` 判断错误发生在路径占位符还是查询参数编码。

RunEvent 持久化与事件查询已经完成源码对照、自动化检查和用户真实后端验证。下一
连续功能点可先让已终止 Run 根据 `Last-Event-ID` 重放持久事件，再单独处理活动 Run
从历史追赶到实时订阅的竞态。

## 功能点 11.1：会话标题完整闭环

#### 本功能点目标

此前最近会话侧栏只能显示 Thread UUID 的前八位。UUID 是寻址身份，不是用户能够识别
的业务名称。本功能点建立完整标题闭环：新 Thread 从首条用户消息得到服务端默认标题，
最近会话列表读取真实标题，用户可以手动改名，并且刷新页面或重启后端后标题仍然存在。

#### 与 DeerFlow 的对应关系

DeerFlow 的 `TitleMiddleware` 只在线程尚无标题、且第一轮用户与 Assistant 交换满足
条件时生成标题，防止后续轮次覆盖既有名称。默认路径直接从首条用户消息生成本地标题；
只有显式配置标题模型时才增加一次 LLM 调用。前端 `useRenameThread()` 通过服务端状态
写入接口改名，成功后更新查询缓存；改名失败时对话框保持打开并保留用户输入。

Mini Deer 借鉴的是这些职责规则，而不是复制 checkpoint 实现。Mini Deer 的标题属于
Application Database 中的产品 Thread 元数据，因此不写入 LangGraph checkpoint：

```text
首条用户消息
    → create_run() 同一事务
        ├── 创建 Thread 与默认 title
        ├── 创建 Run
        └── 保存首条用户消息

手动改名
    → PATCH /api/v1/threads/{thread_id}
    → ConversationHistoryService
    → ConversationRepository
    → 更新 threads.title 与 updated_at
```

这样即使首轮模型运行失败，已经创建的产品 Thread 仍有可识别标题；手动改名也不需要
占用 DeerFlow checkpoint state-write 使用的运行串行锁。

#### 标题领域规则与 SQLite v4

`domain/conversations.py` 集中定义标题规则：连续空白和换行压缩为一个空格，最大长度
为 60 个字符，超长默认标题为正文截断后追加 `...`。规则不放在 Router 或 React
组件中，因此 HTTP 之外的未来入口也可以复用。

application SQLite v4 为 `threads` 增加可空 `title`。`create_run()` 的
`INSERT ... ON CONFLICT` 只在新建 Thread 的 INSERT 分支写入默认标题；冲突更新分支
只更新状态和活动时间，不更新标题。这条 SQL 边界保证：

- 第一轮消息可以生成默认标题；
- 第二轮及之后的消息不会重命名 Thread；
- 用户手动设置的标题不会被下一次 Run 覆盖。

迁移前已经存在的 Thread 保持 `title = null`，前端临时退回短 UUID。系统没有用后来
的任意消息反推旧 Thread 标题，因为那可能把第五轮消息错误地伪装成首条消息；用户可
通过正式改名入口补充标题。

#### PATCH API 与应用边界

`ThreadTitleUpdateRequest` 禁止额外字段，并在长度校验前规范化空白。空标题、超过
60 字符和尝试夹带 `status` 等字段都会得到 422；不存在的 Thread 返回稳定的
`thread_not_found` 404。

Router 只负责 UUID、schema、404 和响应投影。`ConversationHistoryService` 承担统一
业务校验，SQLite Repository 原子更新标题和活动时间，并返回提交后的完整
`ThreadRecord`。前端因此不需要猜测服务端最终保存了什么。

#### 前端真实标题与失败重试

`ThreadSummary` 增加 `title: string | null`，API parser 在不可信 JSON 进入页面前
校验类型、空值和长度。侧栏优先显示服务端标题，只有旧 Thread 的标题为空时才显示
短 UUID 回退文案。

行内改名不会先做可能回滚的乐观覆盖：`useThreadList.renameTitle()` 等待 PATCH 成功，
再用服务端返回的完整 Thread 替换列表记录。失败时编辑框、草稿和错误提示都保留，
用户可以原地重试；成功后编辑框关闭，刷新页面会从 SQLite 重新读取同一标题。

#### 自动化与真实验证

自动化覆盖：

- SQLite v1 数据保留并自动升级到 v4。
- 默认标题空白规范化与只生成一次。
- 手动标题不被后续 Run 覆盖。
- 关闭并重新打开 SQLite 后标题仍存在。
- PATCH 成功、404、空标题与额外字段 422。
- 前端标题 parser、PATCH 请求与服务端返回事实。
- 改名失败保留输入并允许第二次保存。

功能完成时的检查结果：

```text
后端测试：77 passed
前端测试：11 files / 89 passed
TypeScript typecheck、ESLint、Prettier、生产 build：通过
Python compileall、git diff --check：通过
```

用户在真实浏览器验证了默认标题、手动改名和刷新后持久存在，并明确回复“已验证，
继续”。验证前发生过一次 5173 端口占用，是自动检查启动的 Vite 进程尚未关闭；释放
5173 与 8001 后即可由用户自己的终端正常启动，不属于标题功能故障。

### 功能点 11.1 小结

完成该功能点后，已经掌握：

- 为什么 Thread ID 只负责寻址，标题必须成为服务端产品事实。
- 为什么默认标题只应在 Thread 首次创建时写入。
- 为什么本地确定性标题不需要额外 LLM 调用。
- 如何通过迁移兼容旧 Thread，而不使用后续消息伪造首轮标题。
- 为什么改名校验属于 Application Service，而不是 Router 或 UI。
- 为什么前端应采用 PATCH 返回的完整记录，并在失败时保留编辑上下文。
- 为什么 Mini Deer 的产品数据库标题不需要复制 DeerFlow 的 checkpoint 写锁。

会话标题完整闭环已经完成源码对照、自动化检查和用户真实浏览器验证。功能点 11.2
“前端对话窗口工程化渲染”由用户完成并保持原编号；后续功能从 11.3 继续。

## 功能点 11.2：前端对话窗口工程化渲染

#### 本功能点目标

此前前端已经具备可靠 SSE、历史恢复和工具时间线，但展示层仍把 Assistant 正文直接
放入 `<p>`，工具参数和结果始终展开，也没有粘底滚动、复制和独立轮次投影。本功能点
在不修改 SSE v1、历史 API 和持久化协议的前提下，把扁平业务事实变成安全、稳定、
可交互的对话界面。

#### 从 DeerFlow 学到的职责边界

DeerFlow 的关键不在于某个气泡样式，而在于消息事实、派生分组和渲染组件分离。
Mini Deer 因此保留 reducer 的扁平 `ChatTimelineItem`，新增纯函数
`projectConversation()`：用户消息开启轮次，Assistant 和工具保持事件原顺序，只有
最后一轮从当前 `ChatRunPhase` 派生 streaming、failed 或 cancelled。

这避免了两类耦合：

- reducer 不需要知道气泡、复制按钮或折叠状态；
- `MessageList` 不再同时负责分组、正文解析、工具卡和滚动策略。

#### 安全 Markdown 与纯文本边界

Assistant 正文通过 `react-markdown + remark-gfm` 渲染，支持标题、列表、引用、表格、
链接和代码块。原始 HTML 被完全跳过，`javascript:` URL 由默认安全转换清空，外链增加
`noopener noreferrer`。模型生成的远程图片不会自动请求，而是显示文本占位，避免
浏览器在用户不知情时向第三方发送网络请求。

用户消息继续使用 React 文本节点和 `white-space: pre-wrap`。即使用户输入 Markdown
或 HTML，也必须逐字显示，不能在历史恢复时重新解释成富文本。

#### 工具步骤与原始事实

工具卡使用原生 `<details>/<summary>`：pending、failed 和 cancelled 默认展开，
completed 默认收起。合法 JSON 只格式化一个展示副本，reducer 保存的原始 input/result
不变；长内容在卡内滚动，空结果显示明确提示而不是永远停留在“等待结果”。

#### 滚动所有权

自动滚动不能简单地在每个 delta 后执行 `scrollToBottom()`。真正规则是：

1. 用户距离底部 64px 内时，视为仍在跟随最新内容。
2. 用户主动上滚后停止跟随，新内容只触发“回到最新”提示。
3. 历史从顶部插入时使用新旧 `scrollHeight` 差补偿 `scrollTop`，保持原阅读锚点。
4. 切换 Thread 时清除旧会话的滚动意图并定位到新会话底部。
5. `prefers-reduced-motion` 下不发起平滑滚动。

React 19 的 refs/immutability Lint 还验证了一个 API 约束：自定义 hook 不应把可变 ref
直接暴露给调用组件。本实现把 ref 保留在 hook 内，只公开 callback ref 和事件函数。

#### 复制资格是派生状态

复制入口不能仅按 `role === assistant` 判断。一个工具型 Run 可能包含工具前说明、工具
调用和最终回答；流式、失败或取消的最后文本也可能不完整。因此只有 status 为 final
的轮次中最后一条 Assistant 消息获得“复制回答”和代码块复制。整条回答复制保留原始
Markdown，代码块复制提取纯代码并移除围栏。剪贴板权限失败只显示非阻塞错误，原文继续
保持可选择。

#### 自动化与真实验证

自动化覆盖：

- Assistant Markdown、用户纯文本、危险链接、原始 HTML 和远程图片边界。
- 工具四种状态、折叠交互、JSON 格式化和空结果。
- 轮次顺序、孤立历史边界以及最后一轮状态投影。
- 粘底、主动上滚、历史前插锚点和 Thread 切换。
- 流式复制禁用、最终回答/代码复制、权限失败和工具前说明不误判。

最终结果：

```text
前端测试：16 files / 111 passed
Prettier：通过
ESLint：通过
TypeScript typecheck：通过
生产 build：通过
```

用户在真实浏览器逐项验证了 Markdown、工具折叠、刷新顺序、滚动、复制和 320px 窄屏，
并明确回复“已验证”。

### 功能点 11.2 小结

完成该功能点后，已经掌握：

- 原始消息事实、展示投影和组件渲染为什么必须分层。
- 为什么用户文本与 Assistant Markdown 应使用不同安全策略。
- 为什么工具 JSON 格式化不能修改 reducer 保存的原始事实。
- 为什么滚动跟随是用户意图状态，而不是每次更新都执行的副作用。
- 为什么历史前插需要高度补偿，Thread 切换需要重置滚动意图。
- 为什么复制资格必须由轮次终态和最后 Assistant 消息共同决定。

前端对话窗口工程化渲染已经完成自动化检查和用户真实浏览器验证。下一项“显示执行时间”
应先定义 total run wall-clock 的事实来源、活动 Run 的临时计时与历史 Run 的权威恢复，
不能把组件挂载时间误当成服务端执行时间。

## 功能点 11.3：会话删除完整闭环

#### 本功能点目标

此前 Mini Deer 可以创建、切换和改名会话，但不能删除已经持久化的 Thread。仅从前端
侧栏移除一项并不等于真正删除：产品历史保存在 `application.sqlite`，LangGraph 模型
上下文保存在 `checkpoints.sqlite`，任一侧残留都可能让刷新后的列表或复用相同 UUID 的
模型上下文重新出现。

本功能点建立完整删除闭环：用户在侧栏二次确认后，服务端共同删除 checkpoint 与完整
业务历史；删除当前会话时，页面只在服务端成功后切换到全新 Thread；活动 Run 所属
Thread 明确拒绝删除。

#### 与 DeerFlow 的对应关系

DeerFlow 的删除路由不只处理可见列表。它还会清理本地 Thread 目录、LangGraph
checkpoint、`thread_meta` 和关联浏览器会话。前端 `useDeleteThread()` 在远端删除成功后
剔除查询缓存、重新校准列表；如果删除的是当前 Thread，则重置聊天状态并导航到新会话。

Mini Deer 没有 sidecar Thread、工作区文件目录、React Query 缓存或浏览器自动化会话，
因此没有复制这些外围机制，而是保留当前产品真正需要的职责：

```text
用户确认删除
    → ConversationRail
    → ChatPage
    → useThreadList
    → DELETE /api/v1/threads/{thread_id}
    → ThreadLifecycleService
        ├── 检查 Thread 存在且不 busy
        ├── adelete_thread() 删除 LangGraph checkpoint
        └── delete_thread() 删除业务 Thread
              └── SQLite 外键级联清除全部业务历史

若删除的是当前 Thread
    → 服务端返回 204
    → createNewCurrentThreadId()
    → 现有 Thread 身份切换机制清空旧页面状态
```

#### 双 SQLite 生命周期边界

`ThreadLifecycleService` 是本功能的核心应用服务。Router 只处理 UUID、HTTP 状态与错误
映射，不直接访问 SQLite；应用服务通过 `ConversationRepository` 和最小
`ThreadCheckpointStore` Protocol 编排两个持久化端口。

删除前先读取业务 Thread：不存在返回 `thread_not_found` 404；状态为 `busy` 时，在触碰
任一数据库前抛出 `ActiveThreadDeleteConflictError`，Router 将其映射为稳定的
`thread_busy` 409。这样不会在后台 Run 仍写入时拆除一半状态。

空闲 Thread 先调用 Checkpointer 的 `adelete_thread(thread_id)`，再删除业务 Thread。
checkpoint 保存的是模型可恢复上下文；如果只清理业务库，将来意外复用相同 UUID 时仍
可能继承已经删除的对话。业务仓储在事务内再次检查 `busy`，避免校验与最终 SQL 之间
完全失去防线。

#### SQLite 级联删除

业务库没有逐表执行六条删除语句。现有 Schema 已经让 `runs`、`timeline_items`、
`messages`、`tool_executions` 和 `run_events` 通过 `ON DELETE CASCADE` 依附 Thread 或
Run，并在连接启动时启用 `PRAGMA foreign_keys = ON`。

因此仓储只需在事务中执行：

```sql
DELETE FROM threads WHERE thread_id = ?
```

SQLite 会把整棵业务事实一起清除。这个设计既减少漏删新表的风险，也保证单个业务库内
不会出现 Thread 已消失但 Message 或 Run 成为孤儿的中间提交。

#### 前端确认、失败恢复与当前身份切换

`ConversationRail` 为每条持久化会话提供“删除”入口。第一次点击只进入确认态，明确显示
“此操作不可撤销”；确认期间按钮变为“删除中…”。请求失败时确认态和会话记录都保留，
错误显示在原位置，用户可以直接重试或取消。

`useThreadList.deleteThread()` 不做乐观删除：它先等待正式 DELETE API 返回 204，再从
本地列表移除对应 Thread。这样网络失败或服务端 409 不会制造“侧栏已经消失、刷新又
回来”的假成功。

`ChatPage.deletePersistedThread()` 同样先等待删除成功。只有被删 ID 等于当前
`threadId` 时，才调用既有 `CurrentThreadRepository.createNewCurrentThreadId()`。随后
`useChatRun`、历史 Hook、Run 列表和 Composer 都因 Thread 身份改变而沿用原有重置链路，
不需要为删除另写一套清空 reducer 的旁路逻辑。

活动 Run 期间，当前会话删除按钮和后端 409 形成双层边界：前端减少误操作，服务端仍是
最终事实来源，不能依赖按钮禁用保证数据安全。

#### 自动化与真实验证

自动化覆盖：

- DELETE 成功返回 204 空响应，并同时调用 checkpoint 与业务仓储删除。
- 不存在的 Thread 返回稳定 404，且不触碰 checkpoint。
- `busy` Thread 返回稳定 409，两套存储均保持不变。
- 删除完成 Thread 后，Thread、Run、时间线、Message、ToolExecution 和 RunEvent 全部
  由外键级联清空。
- 前端 DELETE client 校验 UUID，并把 409 映射为可理解错误。
- Hook 只在服务端成功后移除列表记录，失败时保留原项。
- 删除当前会话后生成全新 Thread 并清除旧历史；失败时保留确认区域并允许重试。

功能完成时的检查结果：

```text
后端测试：81 passed
前端测试：19 files / 138 passed
TypeScript typecheck、ESLint、Prettier、生产 build：通过
Python compileall：通过
```

用户在真实浏览器验证了删除确认、取消、删除非当前会话、刷新后不恢复、删除当前会话后
进入空白新 Thread，以及活动 Run 期间禁止删除，并明确回复“已验证”。

### 功能点 11.3 小结

完成该功能点后，已经掌握：

- 为什么从侧栏移除一行不等于删除会话。
- 为什么产品历史和 LangGraph checkpoint 必须由应用服务共同编排。
- 为什么 Router 不应直接操作双 SQLite。
- 如何使用外键级联原子清理完整业务事实树。
- 为什么活动 Run 的删除必须由服务端拒绝，前端禁用只能改善交互。
- 为什么删除 UI 不应乐观隐藏记录。
- 为什么删除当前会话应复用既有 Thread 身份切换机制，而不是手工清空多个状态容器。

会话删除完整闭环已经完成 DeerFlow/Mini Deer 源码对照、测试驱动实现、整库自动化检查
和用户真实浏览器验证。下一业务功能点从 11.4 连续编号，具体内容由下一轮计划选择决定。

## 功能点 11.4：网页搜索与引用展示闭环

#### 本功能点目标

Mini Deer 已有真实 `web_search` 工具，但搜索结果此前只在工具卡里显示为原始 JSON，
最终回答也没有稳定的来源格式。用户无法快速判断 Agent 搜过哪些网页、哪个事实来自
哪里，刷新后虽然原始消息仍在，也没有把它们重新投影为来源 UI。

本功能点建立从搜索证据到最终引用的完整业务链路：工具卡展示可点击搜索来源，Assistant
回答显示就近引用与去重来源面板，刷新后从既有持久历史恢复相同展示。

#### 与 DeerFlow 的对应关系

DeerFlow 的 DDG 搜索工具返回 `query/total_results/results`，每条结果包含标题、URL 和
摘要；聊天页面把 `web_search` 工具结果渲染为搜索条目。最终回答使用
`[citation:title](url)` 约定，前端引用提取器按 URL 去重、统计使用次数并遮蔽代码区，
再由消息组件同时渲染正文引用和来源面板。

Mini Deer 已经拥有相同形状的搜索 JSON，也已经把 ToolMessage 和 Assistant 文本保存到
application SQLite。因此实现没有复制 DeerFlow 的完整消息模型，也没有新增 citation
数据库表，而是沿用真正存在的事实边界：

```text
web_search 返回结构化 JSON
    → ToolMessage
    → projector 生成 tool_result.content
    → SSE 与 application SQLite 保存原文
    → ToolActivity 安全解析为搜索来源卡

模型根据搜索证据生成 citation Markdown
    → Assistant Message 持久化原文
    → MessageContent 渲染行内引用
    → extractCitationSources 去重
    → CitationSources 展示来源面板
```

#### Prompt v2 与引用真实性边界

默认 Prompt 升级为 `mini-deer-agent/system/v2`。新规则要求每个需要联网来源支持的关键
事实使用 `[citation:来源标题](https://来源URL)`，并且只能引用 `web_search` 真实返回的
URL，不得编造或改写。

引用关系不能由前端根据关键词可靠猜测：只有模型在生成回答时知道某句话使用了哪条
证据。因此后端 Prompt 负责建立语义约束，前端只负责验证协议形状和安全展示。当前
Prompt 版本仍未进入 Run 配置快照，这是已有可追溯性待办，不影响本次可见引用闭环。

#### 搜索结果解析与回退

`parseWebSearchResult()` 把持久化工具正文当作不可信输入：必须是对象，必须包含字符串
`query` 与数组 `results`，可选 `error` 必须是字符串。每条来源只接受 HTTP(S) URL，
缺少标题时使用域名，最多展示十条；非法候选被跳过，整体结构非法则返回 `null`。

`ToolActivity` 只在工具名为 `web_search` 时调用该解析器。解析成功后展示搜索词、来源
数量、可点击标题、域名、摘要和明确错误；解析失败或工具不是搜索时继续使用原有文本/
格式化 JSON 路径。专用展示能力没有破坏通用工具卡的兼容边界。

#### citation 提取与安全渲染

`extractCitationSources()` 只匹配明确的 citation Markdown，并在提取前遮蔽围栏代码与
闭合行内代码，避免示例代码变成真实来源。正则排除 Markdown 图片，URL 再经过
`URL` 解析并限制为 HTTP(S)。相同 URL 使用 `Map` 去重并累计引用次数；通用标题
“source/来源”会回退为域名。

`MessageContent` 继续保持角色边界：用户消息仍是纯文本，只有 Assistant Markdown 会
提取 citation。行内引用在 `react-markdown` 的链接渲染层转换为来源徽标，仍保留
`noopener noreferrer`；普通链接、禁用原始 HTML、危险协议过滤和远程图片占位规则均
保持不变。`CitationSources` 使用原生折叠面板展示去重来源、域名和使用次数。

#### 持久化与刷新恢复

本功能没有新增数据库迁移或 SSE v2。既有 projector 已将 `ToolMessage.text` 放入
`tool_result.content`，仓储保存原始工具结果；Assistant 增量最终形成持久化 Markdown。
历史 API 返回这两类原始事实，刷新后的 reducer 恢复同一时间线，展示组件再执行相同
解析，因此来源卡和引用面板可以自然重建。

这比单独维护第三份 citation 表更适合当前阶段：原始搜索结果仍是工具事实，引用关系仍
是回答正文的一部分，不会产生工具 JSON、回答 Markdown 与引用表三者不一致的问题。

#### 自动化与真实验证

自动化覆盖：

- Prompt 版本和真实搜索 URL 引用规则。
- citation URL 去重、次数统计、代码区/图片/危险协议忽略与通用标题回退。
- Assistant 行内引用和来源面板，以及用户消息不解析 citation。
- `web_search` 标题、域名、摘要、空结果错误和普通工具回退。
- SQLite 关闭重开后搜索工具 JSON 与 Assistant citation Markdown 保持原文。
- 页面刷新历史后重新显示搜索来源卡、行内引用和来源面板。

功能完成时的检查结果：

```text
后端测试：83 passed
前端测试：20 files / 146 passed
TypeScript typecheck、ESLint、Prettier、生产 build：通过
Python compileall：通过
```

用户在真实浏览器验证了搜索工具卡、来源标题与摘要、Assistant 行内引用、参考来源外链
以及刷新后的完整恢复，并明确回复“已验证”。启动验证时曾把 PowerShell 提示符
`(.venv) PS ...>` 一同粘贴到命令中导致 ParserError；只执行 `python -m uvicorn ...`
后即可正常启动，这不是功能故障。

### 功能点 11.4 小结

完成该功能点后，已经掌握：

- 为什么搜索证据、回答引用和展示投影应分属工具、模型与前端职责。
- 为什么 citation 的语义对应由模型生成，而 URL 安全与展示形状由前端校验。
- 为什么既有 ToolMessage 与 Assistant Message 已足以支撑刷新恢复。
- 如何在不新增 SSE 事件和数据库表的情况下完成可追踪引用闭环。
- 为什么专用搜索卡需要保留通用工具文本回退。
- 为什么只解析 Assistant citation，并忽略用户文本、代码和图片。

网页搜索与引用展示闭环已经完成 DeerFlow/Mini Deer 源码对照、测试驱动实现、整库自动化
检查和用户真实浏览器验证。下一业务功能点使用连续编号 11.5，具体内容由下一轮选择。

## 功能点 11.5：网页正文抓取与深度阅读闭环

#### 本功能点目标

11.4 已让 `web_search` 的标题、URL、摘要和最终 citation 对用户可见，但搜索摘要并不是
网页正文。模型无法回答摘要没有覆盖的细节，也无法证明自己真正阅读过来源。

本功能点新增只读 `web_fetch`：Agent 可以直接读取用户给出的公开网页，或在搜索后选择
一个真实 URL 深入阅读；提取后的正文进入现有工具循环，最终回答继续复用 11.4 的行内
引用和来源面板，刷新后恢复同一工具事实。

#### 与 DeerFlow 的对应关系

DeerFlow 把 `web_fetch` 统一为逻辑工具名，再允许 Jina、Crawl4AI、Browserless、Exa 等
不同 Provider 实现。Jina 版本要求精确 URL，下载 HTML 后用 Readability 提取文章并把
模型可见正文截断为 4096 字符；Browserless 版本可以渲染动态页面，但仍先调用共享 URL
safety 拒绝内网目标。前端不会展开全部正文，而是显示所读取网页的标题和链接。

DeerFlow 还为 `web_fetch/web_search` 增加远端结果中和中间件：网页内容与用户输入一样
属于攻击者可控数据，其中伪造的 `<system-reminder>` 或用户输入边界不能成为可信框架
指令。

Mini Deer 没有 Provider 配置体系、浏览器服务或 Readability 依赖，因此没有机械复制。
当前实现使用既有 `httpx` 与标准库 `HTMLParser`，形成可直接验证的公开静态网页闭环：

```text
用户问题
    → web_search 返回候选 URL
    → 模型选择精确 URL 调用 web_fetch
    → URL/DNS/重定向安全检查
    → 有界下载 HTML 或纯文本
    → 提取标题与主要正文
    → 中和伪系统结构标记
    → ToolMessage / SSE / SQLite
    → 模型基于正文生成 citation 回答
    → 前端网页读取卡与来源面板
```

#### URL 与 SSRF 安全边界

后端网页工具运行在用户机器上，不能把 URL 当成普通字符串直接请求。否则模型或恶意网页
可以让服务端访问 `127.0.0.1`、私网服务或云元数据地址。

`_validate_public_url()` 只接受带主机名的 HTTP(S)，拒绝 URL 用户名/密码、localhost、
`.local`、已知元数据域名和超长地址。主机名必须先解析 DNS；字面 IP 和 DNS 返回的所有
地址都要拒绝 private、loopback、link-local、reserved、multicast 与 unspecified 类型。

httpx 不自动跟随重定向。同步与异步读取器每次收到 Location 都使用当前 URL 解析新目标，
再执行完整检查；公网入口跳转到内网时不会发出第二次请求。当前检查与 DeerFlow 一样属于
保守的请求前筛选，不宣称解决所有 DNS rebinding 或上游代理风险。

#### 下载、取消与上下文预算

网页读取限制为 10 秒超时、5 次重定向和 1 MB 解压后响应字节。只接受 HTML、XHTML 与
纯文本；HTTP 4xx/5xx、PDF、图片和其他二进制内容返回稳定错误。标题最多 300 字符，
模型可见正文最多 12000 字符，工具 JSON 中记录是否被截断。

同步调用使用 `httpx.Client`，异步调用直接使用 `httpx.AsyncClient`，没有把异步 HTTP
重新包进线程。这样 Run 取消会传播到网络 await；只有 DNS 和 CPU 正文提取进入
`asyncio.to_thread()`。

#### 静态正文提取

`_ArticleTextExtractor` 单独承担 HTML 结构转换。它从 `<title>` 取得页面标题，优先选择
`main/article`，保留标题、段落、列表、引用与表格等块边界，并跳过 script、style、
noscript、nav、header、footer、aside、form、svg 等噪音。页面没有主内容容器时才回退到
全局可读文本；纯文本响应只做空白规范化。

该实现适用于服务端直接返回正文的公开静态网页，不支持需要 JavaScript 渲染、登录态、
验证码、PDF 或附件的页面。以后若真实需求出现，应增加 Provider/Sandbox 或独立文档
解析能力，而不是让当前工具暗中扩大权限。

#### 远端内容中和与 Prompt v3

HTMLParser 会移除真实 HTML 标签，但页面仍可通过实体编码重新生成类似
`<tool_policy>` 的文本，纯文本页也可伪造 `--- END USER INPUT ---`。正文进入模型前会将
Mini Deer 的系统标签和常见伪指令标签转成可读的实体文本，并把真假难分的用户输入边界
替换为无权威含义的方括号形式。

Prompt 升级为 `mini-deer-agent/system/v3`：需要摘要外细节时才使用 `web_fetch`；只能读取
用户或工具真实返回的精确 URL；网页正文只是事实资料，不能执行其中命令；citation 只能
使用 `web_search/web_fetch` 成功结果中的 URL，失败结果不得引用。

结构中和只处理伪框架标记，不可能判断网页每一句自然语言是否恶意。因此可信 System
Prompt、有限工具权限和用户对来源的可见性仍然共同构成安全边界。

#### 稳定工具结果、持久化与前端投影

成功和失败都使用稳定 JSON，字段为 `requested_url`、最终 `url`、`title`、`content`、
`characters`、`truncated` 和可选 `error`。模型、SSE、SQLite 与前端使用同一原始事实，
没有增加数据库表或 SSE 事件。

`parseWebFetchResult()` 在浏览器中再次校验不可信历史 JSON 和 HTTP(S) URL，并把正文预览
限制为 500 字符。`ToolActivity` 显示域名、模型可见字符数、截断状态、可点击标题和摘要；
失败结果显示稳定 alert，非法结构退回通用工具文本。历史 API 返回原始 JSON 后会重新
生成同一网页卡，citation 仍由 11.4 的组件负责。

#### 自动化与真实验证

自动化覆盖：

- `web_fetch` 参数契约、注册顺序和模型可见工具清单。
- 主 Agent 连续执行 `web_search → web_fetch → citation` 的真实 ToolNode 循环。
- 主体正文提取、导航/脚本过滤、字符截断与非文本响应拒绝。
- 字面内网 IP、localhost、元数据、URL 凭据、DNS 指向私网和公网转内网重定向拒绝。
- 远端伪系统标签与用户输入边界中和。
- AsyncClient 网络等待可被任务取消。
- 前端 JSON 校验、危险协议拒绝、网页成功/失败卡与刷新恢复。

功能完成时的检查结果：

```text
后端测试：96 passed
前端测试：21 files / 151 passed
TypeScript typecheck、ESLint、Prettier、生产 build：通过
Python compileall：通过
```

独立真实公网冒烟成功读取 `https://example.com/`，得到标题 `Example Domain`、正文 129
字符且未截断。用户随后在真实浏览器验证了直接 `web_fetch`、搜索后正文读取、最终引用与
刷新恢复，并明确回复“已验证”。

### 功能点 11.5 小结

完成该功能点后，已经掌握：

- 为什么搜索摘要和网页正文是两种不同的工具事实。
- 为什么服务端网页工具必须在网络请求前建立 SSRF 边界。
- 为什么重定向后的每个目标都要重新校验。
- 如何在没有浏览器和外部抓取 Provider 时提取公开静态网页正文。
- 为什么下载预算、模型上下文预算和前端预览预算需要分别限制。
- 为什么网页正文的伪框架标记必须中和，但普通事实内容应保持可读。
- 为什么通用 ToolMessage/SSE/SQLite 已足够支撑新工具的刷新恢复。

网页正文抓取与深度阅读闭环已经完成 DeerFlow/Mini Deer 源码对照、测试驱动实现、整库
自动化检查、真实公网冒烟和用户浏览器验证。下一业务功能点使用连续编号 11.6。
