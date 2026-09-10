"""从环境变量加载 Mini Deer Agent 的后端配置。"""

import os
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_tool_output_directory() -> Path:
    """把内部大结果放在 OS 应用数据区，默认不落进任一项目树。"""
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        return Path(local_app_data) / "MiniDeerAgent" / "run-outputs"
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "mini-deer-agent" / "run-outputs"
    return Path.home() / ".local" / "share" / "mini-deer-agent" / "run-outputs"


def _default_user_skills_directory() -> Path:
    """把用户技能包保存在应用数据区，与项目文件和内置发布资产隔离。"""
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        return Path(local_app_data) / "MiniDeerAgent" / "skills"
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "mini-deer-agent" / "skills"
    return Path.home() / ".local" / "share" / "mini-deer-agent" / "skills"


def _default_model_credentials_path() -> Path:
    """把模型密钥保存到本机应用数据目录，避免进入项目和 models.yaml。"""
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        return Path(local_app_data) / "MiniDeerAgent" / "model-credentials.json"
    if xdg_data_home := os.environ.get("XDG_DATA_HOME"):
        return Path(xdg_data_home) / "mini-deer-agent" / "model-credentials.json"
    return (
        Path.home()
        / ".local"
        / "share"
        / "mini-deer-agent"
        / "model-credentials.json"
    )


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
    # 项目登记默认关闭：允许根由用户配置，不能由模型或请求参数自行扩充。
    workspace_allowed_roots: tuple[Path, ...] = ()
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
    # 用户 Skill 只从受管本地目录加载；启停影响之后创建的 Run 快照。
    user_skills_directory: Path = Field(default_factory=_default_user_skills_directory)
    # 可信多模型清单只保存非敏感配置；API Key 由各 Profile 声明的环境变量提供。
    models_config_path: Path = Path("models.yaml")
    # 设置页新增模型时，API Key 单独保存且永不通过读取 API 返回。
    model_credentials_path: Path = Field(
        default_factory=_default_model_credentials_path
    )
    # 可指定更小的非工具模型做 Goal 完成判断；省略时复用主模型配置。
    goal_evaluator_model_name: str | None = None
    goal_evaluation_timeout_seconds: float = Field(default=60.0, gt=0)
    # 整个产品 Run（包括 Goal 隐藏续跑）的硬截止时间，避免永久占用 Thread。
    run_timeout_seconds: float = Field(default=900.0, gt=0)
    # Run 内重复调用的提醒与硬收尾阈值；构图时继续校验两者的顺序关系。
    tool_loop_soft_limit: int = Field(default=3, ge=2)
    tool_loop_hard_limit: int = Field(default=5, ge=3)
    tool_transient_failure_limit: int = Field(default=3, ge=2)
    tool_repeated_content_limit: int = Field(default=2, ge=2)
    # 大工具结果独立存入 OS 应用数据目录，不污染项目树、搜索与 Diff。
    tool_output_directory: Path = Field(default_factory=_default_tool_output_directory)
    tool_output_max_inline_chars: int = Field(default=12_000, ge=1_024)
    tool_output_sample_chars: int = Field(default=1_200, ge=64)
    tool_output_read_chunk_chars: int = Field(default=8_000, ge=256)
    # 主 Agent 与全部子 Agent 共用同一 Run 累计预算。
    run_token_soft_limit: int = Field(default=80_000, ge=1)
    run_token_hard_limit: int = Field(default=120_000, ge=2)
    run_model_turn_soft_limit: int = Field(default=16, ge=1)
    run_model_turn_hard_limit: int = Field(default=24, ge=2)
