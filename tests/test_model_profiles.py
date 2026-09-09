"""验证多模型 Profile、密钥安全投影、默认选择与 Run 快照。"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pydantic import SecretStr

from mini_deer_agent.core import Settings
from mini_deer_agent.llms import (
    ModelConfigurationService,
    ModelProfileCatalog,
    ModelProfileError,
    ModelSelectionConflictError,
)
from mini_deer_agent.server.routers import models


def _settings(tmp_path: Path, config: Path) -> Settings:
    return Settings(
        _env_file=None,
        model_name=None,
        api_key=None,
        models_config_path=config,
        application_database_path=tmp_path / "application.sqlite",
    )


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(
        """version: 1
models:
  - name: primary-openai
    display_name: Primary
    provider: openai
    model: gpt-test
    api_key_env: TEST_PRIMARY_KEY
    supports_tools: true
    supports_reasoning: true
  - name: local-compatible
    display_name: Local
    provider: openai-compatible
    model: local-test
    base_url: http://127.0.0.1:11434/v1
    api_key_env: TEST_LOCAL_KEY
""",
        encoding="utf-8",
    )
    return path


def test_profiles_load_strictly_and_project_no_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEST_PRIMARY_KEY", "super-secret")
    monkeypatch.setenv("TEST_LOCAL_KEY", "local-secret")
    settings = _settings(tmp_path, _config(tmp_path))
    service = ModelConfigurationService(
        settings,
        model_factory=lambda _: FakeListChatModel(responses=["OK"]),
    )

    views = service.list_profiles()
    assert [item.name for item in views] == ["primary-openai", "local-compatible"]
    assert views[0].api_key_configured is True
    assert "super-secret" not in repr(views)
    snapshot = service.create_primary_snapshot()
    assert snapshot.profile_name == "primary-openai"
    assert snapshot.metadata["model_profile_revision"] == service.catalog.revision
    service.update_selection(
        "primary-openai",
        "local-compatible",
        expected_revision=0,
    )
    goal_snapshot = service.create_goal_snapshot()
    assert goal_snapshot.profile_name == "local-compatible"
    assert goal_snapshot.selection_revision == 1


def test_selection_is_cas_persisted_and_validated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_PRIMARY_KEY", "primary-secret")
    monkeypatch.setenv("TEST_LOCAL_KEY", "local-secret")
    settings = _settings(tmp_path, _config(tmp_path))
    first = ModelConfigurationService(settings)
    changed = first.update_selection(
        "local-compatible", "primary-openai", expected_revision=0
    )
    assert changed.revision == 1
    assert ModelConfigurationService(settings).selection() == changed
    with pytest.raises(ModelSelectionConflictError):
        first.update_selection("primary-openai", None, expected_revision=0)
    with pytest.raises(ModelProfileError, match="Unknown"):
        first.update_selection("unknown", None, expected_revision=1)


def test_environment_profile_preserves_legacy_configuration(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        model_provider="openai",
        model_name="legacy-model",
        api_key=SecretStr("legacy-key"),
        goal_evaluator_model_name="legacy-goal-model",
        models_config_path=tmp_path / "missing.yaml",
        application_database_path=tmp_path / "application.sqlite",
    )
    catalog = ModelProfileCatalog.load(settings.models_config_path, settings)
    assert catalog.profiles[0].name == "environment-default"
    assert catalog.profiles[0].model == "legacy-model"
    assert catalog.profiles[1].name == "environment-goal"
    assert catalog.profiles[1].model == "legacy-goal-model"
    service = ModelConfigurationService(settings)
    assert service.selection().goal_model == "environment-goal"


def test_model_construction_failure_does_not_change_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_LOCAL_KEY", raising=False)
    service = ModelConfigurationService(
        _settings(tmp_path, _config(tmp_path)),
        model_factory=lambda _: FakeListChatModel(responses=["OK"]),
    )
    before = service.selection()

    with pytest.raises(ModelProfileError, match="TEST_LOCAL_KEY"):
        service.update_selection(
            "local-compatible",
            None,
            expected_revision=before.revision,
        )

    assert service.selection() == before


def test_model_http_list_selection_update_and_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_PRIMARY_KEY", "primary-secret")
    monkeypatch.setenv("TEST_LOCAL_KEY", "local-secret")
    service = ModelConfigurationService(_settings(tmp_path, _config(tmp_path)))
    app = FastAPI()
    app.state.model_configuration_service = service
    app.include_router(models.models_router)
    app.include_router(models.settings_router)

    with TestClient(app) as client:
        listing = client.get("/api/v1/models")
        assert listing.status_code == 200
        assert "super-secret" not in listing.text
        assert "api_key_configured" in listing.text
        selection = client.get("/api/v1/settings/model-selection").json()
        changed = client.put(
            "/api/v1/settings/model-selection",
            json={
                "primary_model": "local-compatible",
                "goal_model": None,
                "revision": selection["revision"],
            },
        )
        assert changed.status_code == 200
        stale = client.put(
            "/api/v1/settings/model-selection",
            json={
                "primary_model": "primary-openai",
                "goal_model": None,
                "revision": selection["revision"],
            },
        )
        assert stale.status_code == 409
