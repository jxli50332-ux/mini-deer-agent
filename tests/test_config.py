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
