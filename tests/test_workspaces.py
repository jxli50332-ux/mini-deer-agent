"""保护项目登记的目录边界、持久身份与本地管理 API 契约。"""

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mini_deer_agent.application.workspaces import (
    ProjectService,
    ThreadProjectConflictError,
)
from mini_deer_agent.core import Settings
from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.persistence.conversations import (
    open_sqlite_conversation_repository,
)
from mini_deer_agent.server import create_app
from mini_deer_agent.server.dependencies import get_directory_picker
from mini_deer_agent.workspace.paths import ProjectRootPolicy


HEADERS = {}  # 本地项目请求无需凭据。


def make_policy(root: Path, **kwargs) -> ProjectRootPolicy:
    """只允许测试临时目录，任何拒绝测试都不读取用户项目内容。"""
    return ProjectRootPolicy(allowed_roots=(root,), **kwargs)


def test_registration_survives_restart_and_thread_deletion(tmp_path: Path) -> None:
    """项目身份独立于 Thread；重开数据库和删除会话不能修改原目录。"""
    root = tmp_path / "项目"
    root.mkdir()
    original = root / "keep.txt"
    original.write_bytes(b"unchanged\r\n")
    database = tmp_path / "app.sqlite"
    with open_sqlite_conversation_repository(database) as repository:
        service = ProjectService(repository.projects, make_policy(tmp_path))
        created = service.register(name=" 学习项目 ", root_path=str(root))
        assert created.name == "学习项目"
        assert created.access_mode == "read_write"
        assert created.status == "available"
        thread_id = str(uuid4())
        run_id = str(uuid4())
        repository.create_run(
            thread_id=thread_id,
            run_id=run_id,
            user_message_id=str(uuid4()),
            user_message="test",
        )
        repository.interrupt_run(thread_id=thread_id, run_id=run_id, error_code="test")
        assert repository.delete_thread(thread_id)
    with open_sqlite_conversation_repository(database) as repository:
        service = ProjectService(repository.projects, make_policy(tmp_path))
        assert service.get(created.project_id) == created
        assert service.list(limit=10, offset=0) == (created,)
    assert original.read_bytes() == b"unchanged\r\n"
    assert list(root.iterdir()) == [original]


def test_duplicate_registration_is_atomic(tmp_path: Path) -> None:
    """并发登记同一路径只能成功一次，不能创建两个可独立授权的项目身份。"""
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repository:
        service = ProjectService(repository.projects, make_policy(tmp_path))

        def register() -> str:
            """将预期冲突作为测试结果，其他异常继续暴露。"""
            try:
                return service.register(name="same", root_path=str(tmp_path)).project_id
            except ProjectError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: register(), range(2)))
        assert results.count("project_already_registered") == 1
        assert len(service.list(limit=10, offset=0)) == 1


def test_unregister_only_removes_metadata_and_survives_restart(
    tmp_path: Path, monkeypatch
) -> None:
    """解除不执行路径检查，保留全部原文件、其他项目和会话；重启不恢复登记。"""
    root = tmp_path / "sample"
    root.mkdir()
    nested = root / "nested"
    nested.mkdir()
    original = nested / "keep.txt"
    original.write_bytes(b"keep original\r\n")
    database = tmp_path / "app.sqlite"
    with open_sqlite_conversation_repository(database) as repository:
        policy = make_policy(tmp_path)
        service = ProjectService(repository.projects, policy)
        project = service.register(name="sample", root_path=str(root))
        other = service.register(name="nested", root_path=str(nested))
        thread_id, run_id = str(uuid4()), str(uuid4())
        repository.create_run(
            thread_id=thread_id,
            run_id=run_id,
            user_message_id=str(uuid4()),
            user_message="preserve",
        )
        repository.interrupt_run(thread_id=thread_id, run_id=run_id, error_code="test")
        history = repository.get_thread(thread_id)
        fact = repository.create_memory_fact(
            content="preserve", category="context", confidence=1
        )

        def reject_inspection(_path):
            """模拟目录检查不可执行，解除登记仍应完成纯元数据操作。"""
            pytest.fail("unregister must not inspect project files")

        monkeypatch.setattr(policy, "inspect", reject_inspection)
        service.unregister(project.project_id)
        service.unregister(project.project_id)
        assert repository.projects.get(project.project_id) is None
        assert repository.projects.get(other.project_id) == other
        assert repository.get_thread(thread_id) == history
        assert repository.search_memory_facts(query="preserve", limit=1)[0] == fact
    with open_sqlite_conversation_repository(database) as repository:
        service = ProjectService(repository.projects, make_policy(tmp_path))
        assert service.get(project.project_id) is None
        assert service.list() == (other,)
        restored = service.register(name="again", root_path=str(root))
        assert restored.project_id != project.project_id
    assert original.read_bytes() == b"keep original\r\n"
    assert list(root.iterdir()) == [nested]
    assert list(nested.iterdir()) == [original]


def test_project_thread_assignment_is_immutable_and_run_preserves_it(
    tmp_path: Path,
) -> None:
    """项目 Thread 首次绑定后不可重绑；首个 Run 补标题但保持归属，普通聊天仍为 null。"""
    database = tmp_path / "app.sqlite"
    project_id, other_project_id = str(uuid4()), str(uuid4())
    project_thread_id, plain_thread_id = str(uuid4()), str(uuid4())
    with open_sqlite_conversation_repository(database) as repository:
        created = repository.create_project_thread(
            thread_id=project_thread_id, project_id=project_id
        )
        assert created.project_id == project_id
        assert created.title is None
        assert (
            repository.create_project_thread(
                thread_id=project_thread_id, project_id=project_id
            )
            == created
        )
        with pytest.raises(ThreadProjectConflictError):
            repository.create_project_thread(
                thread_id=project_thread_id, project_id=other_project_id
            )
        repository.create_run(
            thread_id=project_thread_id,
            run_id=str(uuid4()),
            user_message_id=str(uuid4()),
            user_message="项目首条消息",
        )
        project_thread = repository.get_thread(project_thread_id)
        assert project_thread is not None
        assert project_thread.project_id == project_id
        assert project_thread.title == "项目首条消息"
        repository.interrupt_run(
            thread_id=project_thread_id,
            run_id=repository.list_runs(project_thread_id, limit=1)[0].run_id,
            error_code="test_finished",
        )
        repository.create_run(
            thread_id=plain_thread_id,
            run_id=str(uuid4()),
            user_message_id=str(uuid4()),
            user_message="普通聊天",
        )
        plain_thread = repository.get_thread(plain_thread_id)
        assert plain_thread is not None
        assert plain_thread.project_id is None
        with pytest.raises(ThreadProjectConflictError):
            repository.create_project_thread(
                thread_id=plain_thread_id, project_id=project_id
            )


@pytest.mark.parametrize(
    "invalid",
    [
        ".",
        "../outside",
        "D:relative",
        "//server/share",
        "\\\\?\\C:\\secret",
        "bad\x00path",
    ],
)
def test_registration_rejects_ambiguous_paths(tmp_path: Path, invalid: str) -> None:
    """入口拒绝相对路径、UNC、设备路径和 NUL，不能依赖当前目录解释用户输入。"""
    with pytest.raises(ProjectError):
        make_policy(tmp_path).inspect(invalid)


def test_root_policy_rejects_escape_sensitive_and_non_directory(tmp_path: Path) -> None:
    """字符串前缀相近、上级跳转、秘密目录和文件都不能冒充授权项目根。"""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    sibling = tmp_path / "allowed-other"
    sibling.mkdir()
    secret = allowed / ".ssh"
    secret.mkdir()
    data = allowed / "app-data"
    data.mkdir()
    plain_file = allowed / "file.txt"
    plain_file.write_text("test", encoding="utf-8")
    policy = make_policy(allowed, blocked_roots=(data,))
    for candidate in [
        sibling,
        allowed / ".." / "allowed",
        secret,
        data,
        plain_file,
        Path(allowed.anchor),
        Path.home(),
    ]:
        with pytest.raises(ProjectError):
            policy.inspect(str(candidate))
    with pytest.raises(ProjectError, match="project_root_missing"):
        policy.inspect(str(allowed / "missing"))


def test_symlink_root_and_ancestor_are_rejected(tmp_path: Path) -> None:
    """即便链接最终仍在允许根内，也拒绝跟随，避免后续权限语义分叉。"""
    target = tmp_path / "target"
    target.mkdir()
    (target / "child").mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("当前 Windows 未授予创建符号链接权限；另测 junction")
    for candidate in (link, link / "child"):
        with pytest.raises(ProjectError, match="project_root_link"):
            make_policy(tmp_path).inspect(str(candidate))


@pytest.mark.skipif(os.name != "nt", reason="Windows junction 契约")
def test_windows_junction_root_is_rejected(tmp_path: Path) -> None:
    """真实 junction 必须被 lstat 的 reparse 标志拒绝；无需管理员符号链接权限。"""
    import subprocess

    target = tmp_path / "target"
    target.mkdir()
    junction = tmp_path / "junction"
    # 固定脚本通过独立参数传递临时路径，不拼接 shell 代码或执行删除命令。
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "& { param($linkPath, $targetPath) New-Item -ItemType Junction "
            "-Path $linkPath -Target $targetPath | Out-Null }",
            str(junction),
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    try:
        with pytest.raises(ProjectError, match="project_root_link"):
            make_policy(tmp_path).inspect(str(junction))
    finally:
        # rmdir 仅移除本测试的链接本身，绝不递归跟随目标。
        junction.rmdir()


def test_missing_replaced_and_revoked_roots_are_visible(tmp_path: Path) -> None:
    """目录消失、被另一目录替代或配置收回权限时，查询不能继续声称可用。"""
    root = tmp_path / "project"
    root.mkdir()
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repository:
        service = ProjectService(repository.projects, make_policy(tmp_path))
        project = service.register(name="sample", root_path=str(root))
        root.rename(tmp_path / "original")
        assert service.get(project.project_id).status == "missing"
        root.mkdir()
        assert service.get(project.project_id).status == "changed"
        other = tmp_path / "other"
        other.mkdir()
        restricted = ProjectService(repository.projects, make_policy(other))
        assert restricted.get(project.project_id).status == "unavailable"
    with sqlite3.connect(tmp_path / "app.sqlite") as connection:
        assert (
            connection.execute("SELECT status FROM projects").fetchone()[0]
            == "unavailable"
        )


def make_app(tmp_path: Path, *, enabled: bool = True):
    """使用真实临时持久化和空 MCP 配置，不触发真实模型或第三方服务。"""
    return create_app(
        settings_factory=lambda: Settings(
            _env_file=None,
            checkpoint_database_path=tmp_path / "data" / "checkpoints.sqlite",
            application_database_path=tmp_path / "data" / "application.sqlite",
            mcp_config_path=tmp_path / "absent-mcp.json",
            workspace_allowed_roots=(tmp_path,) if enabled else (),
        )
    )


def test_missing_allowed_root_does_not_prevent_restart(tmp_path: Path) -> None:
    """配置根本身消失后，重建服务仍能查询 missing，不能让整个应用无法启动。"""
    root = tmp_path / "allowed"
    root.mkdir()
    database = tmp_path / "app.sqlite"
    with open_sqlite_conversation_repository(database) as repository:
        service = ProjectService(repository.projects, make_policy(root))
        project = service.register(name="sample", root_path=str(root))
    root.rename(tmp_path / "original")
    with open_sqlite_conversation_repository(database) as repository:
        service = ProjectService(repository.projects, make_policy(root))
        assert service.get(project.project_id).status == "missing"
        root.mkdir()
        assert service.get(project.project_id).status == "changed"


def test_directory_permission_denied_is_safe_status(
    tmp_path: Path, monkeypatch
) -> None:
    """权限拒绝保留登记，底层异常文字不能进入状态或 HTTP 错误。"""
    root = tmp_path / "sample"
    root.mkdir()
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repository:
        service = ProjectService(repository.projects, make_policy(tmp_path))
        project = service.register(name="sample", root_path=str(root))
        scandir = os.scandir

        def deny_project(path):
            """只模拟该项目根的权限拒绝，保留测试清理和其他目录访问。"""
            if Path(path) == root:
                raise PermissionError("internal error details")
            return scandir(path)

        monkeypatch.setattr(os, "scandir", deny_project)
        refreshed = service.get(project.project_id)
        assert refreshed.status == "unavailable"
        assert refreshed.status_reason == "project_root_unavailable"


@pytest.mark.skipif(os.name != "nt", reason="Windows 盘符与设备名契约")
def test_windows_path_aliases_and_ads(tmp_path: Path) -> None:
    """ADS、保留设备名和末尾点空格拒绝；路径大小写变体不产生第二份登记。"""
    root = tmp_path / "Sample"
    root.mkdir()
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repository:
        service = ProjectService(repository.projects, make_policy(tmp_path))
        service.register(name="sample", root_path=str(root))
        with pytest.raises(ProjectError, match="project_already_registered"):
            service.register(name="duplicate", root_path=str(root).upper())
        for invalid in (
            str(root) + ":secret",
            str(root) + ".",
            str(root) + " ",
            str(root / "CON"),
        ):
            with pytest.raises(ProjectError, match="project_root_invalid"):
                service.register(name="invalid", root_path=invalid)


def test_http_registration_pagination_and_restart(tmp_path: Path) -> None:
    """API 返回真实持久身份、读写权限和显式分页；重复登记不得静默覆盖名称。"""
    root = tmp_path / "sample"
    root.mkdir()
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        assert "APIKeyHeader" not in client.get("/openapi.json").json().get("components", {}).get("securitySchemes", {})
        body = {"name": "sample", "root_path": str(root)}
        response = client.post("/api/v1/projects", headers=HEADERS, json=body)
        assert response.status_code == 201, response.text
        project = response.json()
        assert project["access_mode"] == "read_write"
        assert "root_identity" not in project
        assert response.headers["cache-control"] == "no-store"
        assert (
            client.post("/api/v1/projects", headers=HEADERS, json=body).status_code
            == 409
        )
        for index in range(2):
            child = root / str(index)
            child.mkdir()
            assert (
                client.post(
                    "/api/v1/projects",
                    headers=HEADERS,
                    json={"name": str(index), "root_path": str(child)},
                ).status_code
                == 201
            )
        page = client.get("/api/v1/projects?limit=2", headers=HEADERS).json()
        assert len(page["items"]) == 2
        assert page["next_offset"] == 2
        last = client.get("/api/v1/projects?limit=2&offset=2", headers=HEADERS).json()
        assert len(last["items"]) == 1
        assert last["next_offset"] is None
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        assert (
            client.get(
                f"/api/v1/projects/{project['project_id']}", headers=HEADERS
            ).json()
            == project
        )


def test_http_native_picker_registers_selection_and_cancel_is_noop(
    tmp_path: Path,
) -> None:
    """目录选择结果走现有登记策略；取消不创建项目或伪造错误。"""
    selected = tmp_path / "project-test"
    selected.mkdir()
    application = make_app(tmp_path)

    class StubPicker:
        def __init__(self) -> None:
            self.values = iter((str(selected), None))

        def pick(self) -> str | None:
            return next(self.values)

    picker = StubPicker()
    application.dependency_overrides[get_directory_picker] = lambda: picker
    with TestClient(
        application,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        created = client.post("/api/v1/projects/pick-directory", headers=HEADERS)
        assert created.status_code == 201, created.text
        assert created.json()["name"] == "project-test"
        assert Path(created.json()["root_path"]) == selected
        cancelled = client.post(
            "/api/v1/projects/pick-directory", headers=HEADERS
        )
        assert cancelled.status_code == 204
        assert cancelled.content == b""
        assert cancelled.headers["cache-control"] == "no-store"
        assert len(client.get("/api/v1/projects", headers=HEADERS).json()["items"]) == 1


def test_http_native_picker_rejects_selection_outside_allowed_root(
    tmp_path: Path,
) -> None:
    """原生对话框不是授权边界，返回路径仍必须通过允许根策略。"""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    data = tmp_path / "data"
    allowed.mkdir()
    outside.mkdir()
    data.mkdir()
    application = create_app(
        settings_factory=lambda: Settings(
            _env_file=None,
            checkpoint_database_path=data / "checkpoints.sqlite",
            application_database_path=data / "application.sqlite",
            mcp_config_path=data / "absent-mcp.json",
            workspace_allowed_roots=(allowed,),
        )
    )

    class OutsidePicker:
        def pick(self) -> str:
            return str(outside)

    application.dependency_overrides[get_directory_picker] = OutsidePicker
    with TestClient(
        application,
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        response = client.post(
            "/api/v1/projects/pick-directory", headers=HEADERS
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "project_root_not_allowed"
        assert client.get("/api/v1/projects", headers=HEADERS).json()["items"] == []


def test_http_unregister_requires_access_and_accepts_missing_root(
    tmp_path: Path,
) -> None:
    """解除沿用管理门禁，目录移走也能解除；204 无正文且重复请求幂等。"""
    root = tmp_path / "sample"
    root.mkdir()
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        project = client.post(
            "/api/v1/projects",
            headers=HEADERS,
            json={"name": "sample", "root_path": str(root)},
        ).json()
        url = f"/api/v1/projects/{project['project_id']}"
        assert (
            client.delete(
                url, headers={**HEADERS, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.get(url, headers=HEADERS).status_code == 200
        root.rename(tmp_path / "original")
        for _ in range(2):
            response = client.delete(url, headers=HEADERS)
            assert response.status_code == 204
            assert response.content == b""
            assert response.headers["cache-control"] == "no-store"
        assert client.get(url, headers=HEADERS).status_code == 404
        assert client.get("/api/v1/projects", headers=HEADERS).json()["items"] == []
        assert (
            client.delete("/api/v1/projects/not-a-uuid", headers=HEADERS).status_code
            == 422
        )
    assert (tmp_path / "original").is_dir()


def test_http_project_threads_are_isolated_idempotent_and_persistent(
    tmp_path: Path,
) -> None:
    """两个 Project 只列出各自 Thread；重试不重复，重启和解除登记都不篡改历史归属。"""
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        root.mkdir()
    thread_ids = [str(uuid4()), str(uuid4())]
    database = tmp_path / "data" / "application.sqlite"
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        projects = [
            client.post(
                "/api/v1/projects",
                headers=HEADERS,
                json={"name": f"project-{index}", "root_path": str(root)},
            ).json()
            for index, root in enumerate(roots)
        ]
        urls = [
            f"/api/v1/projects/{project['project_id']}/threads" for project in projects
        ]
        for url, thread_id, project in zip(urls, thread_ids, projects, strict=True):
            response = client.post(url, headers=HEADERS, json={"thread_id": thread_id})
            assert response.status_code == 200, response.text
            assert response.json()["project_id"] == project["project_id"]
            assert response.json()["title"] is None
            assert (
                client.post(url, headers=HEADERS, json={"thread_id": thread_id}).json()
                == response.json()
            )
        assert [
            item["thread_id"] for item in client.get(urls[0], headers=HEADERS).json()
        ] == [thread_ids[0]]
        assert [
            item["thread_id"] for item in client.get(urls[1], headers=HEADERS).json()
        ] == [thread_ids[1]]
        assert client.get(
            f"{urls[0]}?limit=1&offset=1", headers=HEADERS
        ).json() == []
        assert client.get(
            "/api/v1/threads?scope=standalone", headers=HEADERS
        ).json() == []
        conflict = client.post(
            urls[1], headers=HEADERS, json={"thread_id": thread_ids[0]}
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "thread_project_conflict"
        assert client.post(urls[0], json={"thread_id": thread_ids[0]}).status_code == 200
        assert (
            client.post(
                urls[0],
                headers=HEADERS,
                json={"thread_id": str(uuid4()), "root_path": str(roots[0])},
            ).status_code
            == 422
        )
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        restored = client.get(urls[0], headers=HEADERS)
        assert restored.status_code == 200
        assert restored.json()[0]["thread_id"] == thread_ids[0]
        assert (
            client.delete(
                f"/api/v1/projects/{projects[0]['project_id']}", headers=HEADERS
            ).status_code
            == 204
        )
        assert client.get(urls[0], headers=HEADERS).status_code == 404
        historical = client.get(f"/api/v1/threads/{thread_ids[0]}")
        assert historical.status_code == 200
        assert historical.json()["project_id"] == projects[0]["project_id"]
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT project_id FROM threads WHERE thread_id = ?", (thread_ids[0],)
            ).fetchone()[0]
            == projects[0]["project_id"]
        )


def test_unavailable_or_unknown_project_cannot_create_thread(tmp_path: Path) -> None:
    """目录失效和未知 Project 都在写入 Thread 前拒绝，错误不泄露路径。"""
    root = tmp_path / "sample"
    root.mkdir()
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        project = client.post(
            "/api/v1/projects",
            headers=HEADERS,
            json={"name": "sample", "root_path": str(root)},
        ).json()
        root.rename(tmp_path / "removed")
        response = client.post(
            f"/api/v1/projects/{project['project_id']}/threads",
            headers=HEADERS,
            json={"thread_id": str(uuid4())},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "project_unavailable",
            "message": "项目目录当前不可用，不能创建项目会话。",
        }
        unknown = client.post(
            f"/api/v1/projects/{uuid4()}/threads",
            headers=HEADERS,
            json={"thread_id": str(uuid4())},
        )
        assert unknown.status_code == 404
        assert client.get("/api/v1/threads").json() == []


@pytest.mark.parametrize(
    "extra_headers",
    [
        {**HEADERS, "Origin": "https://evil.example"},
        {**HEADERS, "Host": "evil.example"},
        {**HEADERS, "Origin": "null"},
        {**HEADERS, "Sec-Fetch-Site": "cross-site"},
    ],
)
def test_local_api_rejects_untrusted_requests(
    tmp_path: Path, extra_headers: dict
) -> None:
    """本地访问不是自动授权；GET 也保护路径元数据，POST 未通过门禁不落盘。"""
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        for method in (client.get, client.post):
            assert method("/api/v1/projects", headers=extra_headers).status_code == 403
        assert client.get("/api/v1/projects", headers=HEADERS).json()["items"] == []


def test_disabled_remote_and_invalid_requests_fail_closed(tmp_path: Path) -> None:
    """默认关闭登记能力；远端连接、非法 schema 和越界根都有稳定拒绝。"""
    with TestClient(
        make_app(tmp_path, enabled=False),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        assert client.get("/api/v1/projects", headers=HEADERS).status_code == 503
        assert client.get("/api/v1/health").status_code == 200
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("192.0.2.1", 50100),
    ) as client:
        assert client.get("/api/v1/projects", headers=HEADERS).status_code == 403
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        assert (
            client.post(
                "/api/v1/projects",
                headers=HEADERS,
                json={
                    "name": "sample",
                    "root_path": str(tmp_path),
                    "access_mode": "write",
                },
            ).status_code
            == 422
        )
        response = client.post(
            "/api/v1/projects",
            headers=HEADERS,
            json={"name": "sample", "root_path": str(tmp_path.parent)},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "project_root_not_allowed"
        assert (
            client.get(f"/api/v1/projects/{uuid4()}", headers=HEADERS).status_code
            == 404
        )


def test_v8_database_migrates_without_losing_history(tmp_path: Path) -> None:
    """项目表由既有业务迁移器升级到 v9，不能删除旧 Memory 或另造 schema 版本链。"""
    database = tmp_path / "app.sqlite"
    with open_sqlite_conversation_repository(database) as repository:
        fact = repository.create_memory_fact(
            content="preserve", category="context", confidence=1
        )
    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX idx_threads_project_recent")
        connection.execute("ALTER TABLE threads DROP COLUMN project_id")
        connection.execute("DROP TABLE projects")
        connection.execute("DELETE FROM schema_migrations WHERE version IN (9, 10)")
    with open_sqlite_conversation_repository(database) as repository:
        assert repository.search_memory_facts(query="preserve", limit=1)[0] == fact
        assert repository.projects.list(limit=1, offset=0) == ()
        assert repository.list_threads(limit=1) == ()


def test_v10_project_access_mode_migrates_to_read_write(tmp_path: Path) -> None:
    """已有只读 Project 升级后保留身份、目录和 Thread 归属。"""
    root = tmp_path / "project"
    root.mkdir()
    database = tmp_path / "v10.sqlite"
    with open_sqlite_conversation_repository(database) as repository:
        service = ProjectService(repository.projects, make_policy(tmp_path))
        project = service.register(name="sample", root_path=str(root))
        thread_id = str(uuid4())
        repository.create_project_thread(
            thread_id=thread_id, project_id=project.project_id
        )

    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX idx_projects_created")
        connection.execute("ALTER TABLE projects RENAME TO projects_latest")
        connection.execute(
            """
            CREATE TABLE projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
                root_path TEXT NOT NULL,
                root_key TEXT NOT NULL UNIQUE,
                root_identity TEXT NOT NULL,
                access_mode TEXT NOT NULL CHECK (access_mode = 'read_only'),
                status TEXT NOT NULL CHECK (
                    status IN ('available', 'missing', 'unavailable', 'changed')
                ),
                status_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO projects (
                project_id, name, root_path, root_key, root_identity, access_mode,
                status, status_reason, created_at, updated_at
            )
            SELECT
                project_id, name, root_path, root_key, root_identity, 'read_only',
                status, status_reason, created_at, updated_at
            FROM projects_latest
            """
        )
        connection.execute("DROP TABLE projects_latest")
        connection.execute(
            "CREATE INDEX idx_projects_created ON projects(created_at DESC, project_id DESC)"
        )
        connection.execute("DELETE FROM schema_migrations WHERE version = 11")

    with open_sqlite_conversation_repository(database) as repository:
        migrated = repository.projects.get(project.project_id)
        assert migrated is not None
        assert migrated.access_mode == "read_write"
        assert migrated.root_path == str(root.resolve())
        assert repository.get_thread(thread_id).project_id == project.project_id


def test_http_directory_access_refresh_and_invalid_root(tmp_path: Path) -> None:
    """目录接口复用门禁，不泄露正文；根失效不能继续枚举。"""
    root = tmp_path / "sample"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "hello.py").write_text("private body")
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        project = client.post(
            "/api/v1/projects",
            headers=HEADERS,
            json={"name": "sample", "root_path": str(root)},
        ).json()
        url = f"/api/v1/projects/{project['project_id']}/directory"
        assert client.get(url).status_code == 200
        assert (
            client.get(
                url, headers={**HEADERS, "Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        response = client.get(url, headers=HEADERS, params={"path": "src"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["items"][0]["path"] == "src/hello.py"
        assert "private body" not in response.text
        assert (
            client.get(url, headers=HEADERS, params={"path": "../"}).status_code == 400
        )
        assert (
            client.get(url, headers=HEADERS, params={"limit": 501}).status_code == 422
        )
        root.rename(tmp_path / "old")
        assert client.get(url, headers=HEADERS).status_code == 409


def test_http_file_preview_requires_access(tmp_path: Path) -> None:
    """正文读取门禁与目录一致，秘密文件和失效根均拒绝。"""
    root = tmp_path / "sample"
    root.mkdir()
    (root / "hello.py").write_text("first\nsecond\n", encoding="utf-8")
    (root / ".env").write_text("secret")
    with TestClient(
        make_app(tmp_path),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 50100),
    ) as client:
        project = client.post(
            "/api/v1/projects",
            headers=HEADERS,
            json={"name": "sample", "root_path": str(root)},
        ).json()
        url = f"/api/v1/projects/{project['project_id']}/file"
        assert client.get(url, params={"path": "hello.py"}).status_code == 200
        response = client.get(
            url, headers=HEADERS, params={"path": "hello.py", "limit": 1}
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["lines"] == ["first"]
        assert response.json()["next_line"] == 2
        assert (
            client.get(url, headers=HEADERS, params={"path": ".env"}).status_code == 400
        )
        assert (
            client.get(
                url,
                headers={**HEADERS, "Origin": "https://evil.example"},
                params={"path": "hello.py"},
            ).status_code
            == 403
        )
        root.rename(tmp_path / "old")
        assert (
            client.get(url, headers=HEADERS, params={"path": "hello.py"}).status_code
            == 409
        )
