from pathlib import Path

import pytest

from mini_deer_agent.core import Settings


MODEL_ENV_VARS = (
    "MINI_DEER_MODEL_PROVIDER",
    "MINI_DEER_MODEL_NAME",
    "MINI_DEER_API_KEY",
    "MINI_DEER_API_BASE_URL",
)


def test_settings_has_non_sensitive_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in MODEL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.model_provider == "openai"
    assert settings.model_name is None
    assert settings.api_key is None
    assert settings.api_base_url is None
    assert settings.checkpoint_database_path == Path("data/checkpoints.sqlite")
    assert settings.application_database_path == Path("data/application.sqlite")
    assert settings.workspace_allowed_roots == ()
    assert settings.context_summary_enabled is True
    assert settings.context_summary_trigger_tokens == 50_000
    assert settings.context_summary_trigger_messages == 40
    assert settings.context_summary_keep_messages == 10
    assert settings.context_summary_input_tokens == 25_000
    assert settings.mcp_config_path == Path("mcp_servers.json")
    assert settings.mcp_server_init_timeout_seconds == 10.0
    assert settings.user_skills_directory.name == "skills"
    assert settings.goal_evaluator_model_name is None
    assert settings.tool_output_directory.name == "run-outputs"
    assert settings.tool_output_max_inline_chars == 12_000
    assert settings.tool_output_sample_chars == 1_200
    assert settings.tool_output_read_chunk_chars == 8_000
    assert settings.run_token_soft_limit == 80_000
    assert settings.run_token_hard_limit == 120_000
    assert settings.run_model_turn_soft_limit == 16
    assert settings.run_model_turn_hard_limit == 24


def test_environment_variables_override_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINI_DEER_MODEL_PROVIDER", "openai-compatible")
    monkeypatch.setenv("MINI_DEER_MODEL_NAME", "test-model")
    monkeypatch.setenv("MINI_DEER_API_KEY", "test-secret-key")
    monkeypatch.setenv("MINI_DEER_API_BASE_URL", "https://example.invalid/v1")

    settings = Settings(_env_file=None)

    assert settings.model_provider == "openai-compatible"
    assert settings.model_name == "test-model"
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "test-secret-key"
    assert "test-secret-key" not in repr(settings)
    assert str(settings.api_base_url) == "https://example.invalid/v1"


def test_settings_can_load_dotenv_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in MODEL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "MINI_DEER_MODEL_PROVIDER=local\n"
        "MINI_DEER_MODEL_NAME=dotenv-model\n"
        "MINI_DEER_API_KEY=dotenv-secret\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.model_provider == "local"
    assert settings.model_name == "dotenv-model"
    assert settings.api_key is not None
    assert settings.api_key.get_secret_value() == "dotenv-secret"


def test_example_env_targets_deepseek_without_exposing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公开模板应选中本课模型，但不能包含任何真实密钥。"""
    for name in MODEL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=Path(".env.example"))

    assert settings.model_provider == "openai-compatible"
    assert settings.model_name == "deepseek-v4-flash"
    assert settings.api_key is None
    assert str(settings.api_base_url) == "https://api.deepseek.com/"
    assert settings.context_summary_enabled is True
    assert settings.context_summary_trigger_tokens == 50_000
    assert settings.context_summary_trigger_messages == 40
    assert settings.context_summary_keep_messages == 10
    assert settings.context_summary_input_tokens == 25_000


def test_environment_can_override_context_summary_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实验收和不同模型可通过环境变量调整摘要预算。"""
    monkeypatch.setenv("MINI_DEER_CONTEXT_SUMMARY_ENABLED", "false")
    monkeypatch.setenv("MINI_DEER_CONTEXT_SUMMARY_TRIGGER_TOKENS", "8000")
    monkeypatch.setenv("MINI_DEER_CONTEXT_SUMMARY_TRIGGER_MESSAGES", "12")
    monkeypatch.setenv("MINI_DEER_CONTEXT_SUMMARY_KEEP_MESSAGES", "4")
    monkeypatch.setenv("MINI_DEER_CONTEXT_SUMMARY_INPUT_TOKENS", "3000")

    settings = Settings(_env_file=None)

    assert settings.context_summary_enabled is False
    assert settings.context_summary_trigger_tokens == 8000
    assert settings.context_summary_trigger_messages == 12
    assert settings.context_summary_keep_messages == 4
    assert settings.context_summary_input_tokens == 3000


def test_environment_can_override_mcp_runtime_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINI_DEER_MCP_CONFIG_PATH", "config/custom-mcp.json")
    monkeypatch.setenv("MINI_DEER_MCP_SERVER_INIT_TIMEOUT_SECONDS", "2.5")

    settings = Settings(_env_file=None)

    assert settings.mcp_config_path == Path("config/custom-mcp.json")
    assert settings.mcp_server_init_timeout_seconds == 2.5


def test_environment_can_override_tool_output_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "private-run-outputs"
    monkeypatch.setenv("MINI_DEER_TOOL_OUTPUT_DIRECTORY", str(output_root))
    monkeypatch.setenv("MINI_DEER_TOOL_OUTPUT_MAX_INLINE_CHARS", "4096")
    monkeypatch.setenv("MINI_DEER_TOOL_OUTPUT_SAMPLE_CHARS", "256")
    monkeypatch.setenv("MINI_DEER_TOOL_OUTPUT_READ_CHUNK_CHARS", "2048")

    settings = Settings(_env_file=None)

    assert settings.tool_output_directory == output_root
    assert settings.tool_output_max_inline_chars == 4096
    assert settings.tool_output_sample_chars == 256
    assert settings.tool_output_read_chunk_chars == 2048
