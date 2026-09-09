"""验证固定能力基准 HTTP 入口。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from mini_deer_agent.core import Settings
from mini_deer_agent.persistence import open_sqlite_conversation_repository
from mini_deer_agent.server import create_app


RUN_ID = "22222222-2222-4222-8222-222222222222"


class StubRunExecutionManager:
    async def shutdown(self) -> None:
        return None


def _app(tmp_path: Path):
    database_path = tmp_path / "app.sqlite"

    @asynccontextmanager
    async def open_checkpoint(_path: str) -> AsyncIterator[Any]:
        yield object()

    @asynccontextmanager
    async def open_repository(_path: str) -> AsyncIterator[Any]:
        with open_sqlite_conversation_repository(database_path) as repository:
            yield repository

    return create_app(
        settings_factory=lambda: Settings(_env_file=None),
        checkpointer_context_factory=open_checkpoint,
        conversation_repository_context_factory=open_repository,
        run_stream_service_factory=lambda _checkpoint, _repository: object(),
        run_execution_manager_factory=lambda _service, _repository: StubRunExecutionManager(),
    )


def test_cases_endpoint_exposes_fixed_prompts(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/v1/benchmarks/cases")

    assert response.status_code == 200
    assert len(response.json()) == 8
    assert response.json()[0]["case_id"] == "simple-qa"


def test_missing_attempt_uses_stable_404(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get(f"/api/v1/benchmarks/attempts/{RUN_ID}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "benchmark_attempt_not_found"


def test_regression_endpoint_is_honest_when_runs_are_missing(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/v1/benchmarks/regression")

    assert response.status_code == 200
    payload = response.json()
    assert payload["case_count"] == 8
    assert payload["rerun_case_count"] == 0
    assert payload["all_cases_rerun"] is False
    assert payload["ready_to_close"] is False
    assert set(payload["gates"].values()) == {"insufficient_data"}
