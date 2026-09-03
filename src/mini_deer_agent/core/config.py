"""从环境变量加载 Mini Deer Agent 的后端配置。"""

from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """定义创建聊天模型所需的配置，并统一处理环境变量前缀。"""

    # 所有后端配置统一使用 MINI_DEER_ 前缀，避免与宿主环境变量发生名称冲突。
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MINI_DEER_",
        env_ignore_empty=True,
        extra="ignore",
    )

    model_provider: str = "openai"
    model_name: str | None = None
    api_key: SecretStr | None = None
    api_base_url: AnyHttpUrl | None = None
    # checkpoint 路径属于后端运行配置，不能硬编码在 HTTP 路由或应用服务中。
    checkpoint_database_path: Path = Path("data/checkpoints.sqlite")
    # 产品历史与 LangGraph checkpoint 分库保存，避免 API 依赖框架内部表结构。
    application_database_path: Path = Path("data/application.sqlite")
    # 摘要只压缩 Agent checkpoint；产品历史仍由 application SQLite 完整保存。
    context_summary_enabled: bool = True
    context_summary_trigger_tokens: int = Field(default=50000, ge=1)
    context_summary_trigger_messages: int = Field(default=40, ge=2)
    context_summary_keep_messages: int = Field(default=10, ge=1)
    context_summary_input_tokens: int = Field(default=25000, ge=1)
    # MCP 配置属于可信的本地运维输入；文件不存在表示当前未启用 MCP。
    mcp_config_path: Path = Path("mcp_servers.json")
    # 每个服务器独立受限，避免一个挂起的外部进程阻止应用启动。
    mcp_server_init_timeout_seconds: float = Field(default=10.0, gt=0)
