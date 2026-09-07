"""文件工具适配器使用真实临时项目，验证范围绑定和操作结果。"""

import asyncio
import json
from pathlib import Path
import pytest
from mini_deer_agent.application.workspaces import ProjectService
from mini_deer_agent.persistence.conversations import (
    open_sqlite_conversation_repository,
)
from mini_deer_agent.workspace.paths import ProjectRootPolicy
from mini_deer_agent.tools.project_files import create_project_tools


def test_tools_bound_project_and_real_lines(tmp_path: Path):
    """工具闭包绑定项目 A；创建 B 不会改变 A 的目录，参数不接受 project_id。"""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "main.py").write_text("第一行\n第二行\n", encoding="utf-8")
    (b / "main.py").write_text("other", encoding="utf-8")
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repo:
        service = ProjectService(
            repo.projects, ProjectRootPolicy(allowed_roots=(tmp_path,))
        )
        first = service.register(name="A", root_path=str(a))
        (
            listing,
            reading,
            globbing,
            _searching,
            creating,
            replacing,
            writing,
            directory,
            renaming,
            moving,
            deleting,
        ) = create_project_tools(service, first.project_id)
        second = service.register(name="B", root_path=str(b))
        assert [
            tool.name
            for tool in (
                listing,
                reading,
                globbing,
                _searching,
                creating,
                replacing,
                writing,
                directory,
                renaming,
                moving,
                deleting,
            )
        ] == [
            "list_files",
            "read_file",
            "glob_files",
            "search_files",
            "create_file",
            "str_replace",
            "write_file",
            "create_directory",
            "rename_file",
            "move_file",
            "delete_file",
        ]
        assert json.loads(listing.invoke({}))["items"][0]["path"] == "main.py"
        result = json.loads(
            reading.invoke({"path": "main.py", "start_line": 2, "limit": 1})
        )
        assert result["lines"] == ["第二行"]
        assert result["project_id"] == first.project_id
        assert result["start_line"] == 2
        denied = json.loads(
            reading.invoke({"path": "main.py", "project_id": second.project_id})
        )
        assert denied["error"]["code"] == "project_tool_arguments_invalid"
        assert str(a) not in str(reading.args)
        assert "root_path" not in reading.args


def test_create_file_tool_writes_new_text_without_overwriting(tmp_path: Path):
    """Project 工具创建新文本并可读回；同名目标保持第一次写入内容。"""
    root = tmp_path / "sample"
    root.mkdir()
    with open_sqlite_conversation_repository(tmp_path / "create.sqlite") as repo:
        service = ProjectService(
            repo.projects, ProjectRootPolicy(allowed_roots=(tmp_path,))
        )
        project = service.register(name="A", root_path=str(root))
        tools = create_project_tools(service, project.project_id)
        listing, reading, creating = tools[0], tools[1], tools[4]

        created = json.loads(
            creating.invoke({"path": "notes.txt", "content": "第一行\n第二行\n"})
        )
        assert created["ok"] is True
        assert created["created"] is True
        assert created["path"] == "notes.txt"
        assert created["size_bytes"] == len("第一行\n第二行\n".encode("utf-8"))
        assert json.loads(reading.invoke({"path": "notes.txt"}))["lines"] == [
            "第一行",
            "第二行",
        ]
        assert any(
            item["path"] == "notes.txt"
            for item in json.loads(listing.invoke({}))["items"]
        )

        denied = json.loads(
            creating.invoke({"path": "notes.txt", "content": "覆盖内容"})
        )
        assert denied["ok"] is False
        assert denied["error"]["code"] == "file_already_exists"
        assert (root / "notes.txt").read_text(encoding="utf-8") == "第一行\n第二行\n"


def test_str_replace_tool_edits_one_exact_match_and_preserves_file_format(
    tmp_path: Path,
) -> None:
    """精确替换唯一匹配并保留 UTF-8 BOM 与 CRLF；失败匹配不改文件。"""
    root = tmp_path / "sample"
    root.mkdir()
    target = root / "notes.txt"
    target.write_bytes(b"\xef\xbb\xbfalpha\r\nbeta\r\n")
    with open_sqlite_conversation_repository(tmp_path / "replace.sqlite") as repo:
        service = ProjectService(
            repo.projects, ProjectRootPolicy(allowed_roots=(tmp_path,))
        )
        project = service.register(name="A", root_path=str(root))
        replacing = create_project_tools(service, project.project_id)[5]

        result = json.loads(
            replacing.invoke(
                {"path": "notes.txt", "old_str": "beta", "new_str": "gamma"}
            )
        )
        assert result["ok"] is True
        assert result["replaced"] is True
        assert result["occurrences"] == 1
        assert result["previous_revision"] != result["revision"]
        assert target.read_bytes() == b"\xef\xbb\xbfalpha\r\ngamma\r\n"

        unchanged = target.read_bytes()
        missing = json.loads(
            replacing.invoke(
                {"path": "notes.txt", "old_str": "missing", "new_str": "value"}
            )
        )
        assert missing["error"]["code"] == "file_replace_not_found"
        target.write_text("same\nsame\n", encoding="utf-8", newline="")
        ambiguous_before = target.read_bytes()
        ambiguous = json.loads(
            replacing.invoke(
                {"path": "notes.txt", "old_str": "same", "new_str": "changed"}
            )
        )
        assert ambiguous["error"]["code"] == "file_replace_ambiguous"
        assert unchanged != ambiguous_before
        assert target.read_bytes() == ambiguous_before


def test_write_file_tool_replaces_complete_existing_text(tmp_path: Path) -> None:
    """完整更新已有文本并保留 BOM；缺失目标必须改用 create_file。"""
    root = tmp_path / "sample"
    root.mkdir()
    target = root / "notes.txt"
    target.write_bytes(b"\xef\xbb\xbfprevious\r\n")
    with open_sqlite_conversation_repository(tmp_path / "write.sqlite") as repo:
        service = ProjectService(
            repo.projects, ProjectRootPolicy(allowed_roots=(tmp_path,))
        )
        project = service.register(name="A", root_path=str(root))
        writing = create_project_tools(service, project.project_id)[6]

        result = json.loads(
            writing.invoke({"path": "notes.txt", "content": "first\nsecond\n"})
        )
        assert result["ok"] is True
        assert result["written"] is True
        assert result["created"] is False
        assert result["changed"] is True
        assert result["previous_revision"] != result["revision"]
        assert result["previous_content_preview"] == "previous\r\n"
        assert result["previous_content_truncated"] is False
        assert target.read_bytes() == b"\xef\xbb\xbffirst\nsecond\n"

        long_target = root / "long.txt"
        long_target.write_text("旧" * 4001, encoding="utf-8")
        long_result = json.loads(
            writing.invoke({"path": "long.txt", "content": "updated\n"})
        )
        assert long_result["previous_content_preview"] == "旧" * 4000
        assert long_result["previous_content_truncated"] is True

        missing = json.loads(
            writing.invoke({"path": "missing.txt", "content": "new\n"})
        )
        assert missing["error"]["code"] == "file_write_missing"
        assert not (root / "missing.txt").exists()


def test_tool_errors_and_revocation(tmp_path: Path):
    """工具失败用稳定 JSON 返回，解除登记后原工具不能继续读。"""
    root = tmp_path / "sample"
    root.mkdir()
    (root / ".env").write_text("do-not-return")
    (root / "main.py").write_text("safe")
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repo:
        service = ProjectService(
            repo.projects, ProjectRootPolicy(allowed_roots=(tmp_path,))
        )
        project = service.register(name="A", root_path=str(root))
        listing, reading, *_ = create_project_tools(service, project.project_id)
        for path in (".env", "../outside", "missing.py"):
            result = json.loads(reading.invoke({"path": path}))
            assert result["ok"] is False
            assert "do-not-return" not in str(result)
        service.unregister(project.project_id)
        assert json.loads(reading.invoke({"path": "main.py"}))["ok"] is False
        assert json.loads(listing.invoke({}))["ok"] is False


def test_async_matches_sync_and_root_replacement_fails(tmp_path: Path):
    """异步工具复用相同只读链，根目录被替换后拒绝原绑定。"""
    root = tmp_path / "sample"
    root.mkdir()
    (root / "x.py").write_text("original")
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repo:
        service = ProjectService(
            repo.projects, ProjectRootPolicy(allowed_roots=(tmp_path,))
        )
        project = service.register(name="A", root_path=str(root))
        _, reading, *_ = create_project_tools(service, project.project_id)
        assert asyncio.run(reading.ainvoke({"path": "x.py"})) == reading.invoke(
            {"path": "x.py"}
        )
        root.rename(tmp_path / "old")
        root.mkdir()
        (root / "x.py").write_text("replacement")
        result = json.loads(reading.invoke({"path": "x.py"}))
        assert result["ok"] is False
        assert "replacement" not in str(result)
