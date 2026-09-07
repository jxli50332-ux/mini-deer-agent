"""通用文件 Scope 同时支持 Project 目录和普通对话允许根。"""

import json
from pathlib import Path

import pytest

from mini_deer_agent.application.workspaces import ReadOnlyFileAccess
from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.tools.project_files import create_file_tools
from mini_deer_agent.workspace.paths import ProjectRootPolicy


def make_policy(root: Path) -> ProjectRootPolicy:
    """只授权测试临时根，避免测试读取工作区或用户目录。"""
    return ProjectRootPolicy(allowed_roots=(root,))


def test_explicit_file_scope_reads_only_selected_file(tmp_path: Path) -> None:
    """明确授权单文件后可读取该文件，但不能顺带读取同目录兄弟文件。"""
    selected = tmp_path / "selected.py"
    sibling = tmp_path / "sibling.py"
    selected.write_text("第一行\n第二行\n", encoding="utf-8")
    sibling.write_text("private sibling", encoding="utf-8")
    access = ReadOnlyFileAccess.for_explicit_path(
        make_policy(tmp_path), str(selected)
    )
    listing, reading, *_ = create_file_tools(access)

    listed = json.loads(listing.invoke({}))
    assert listed["access_source"] == "explicit"
    assert "project_id" not in listed
    assert [item["path"] for item in listed["items"]] == ["selected.py"]
    result = json.loads(reading.invoke({"path": "selected.py"}))
    assert result["lines"] == ["第一行", "第二行"]
    assert result["line_numbers"] == [1, 2]
    denied = json.loads(reading.invoke({"path": "sibling.py"}))
    assert denied["error"]["code"] == "file_access_path_out_of_scope"
    assert "private sibling" not in str(denied)


def test_explicit_directory_scope_reuses_relative_list_and_read(
    tmp_path: Path,
) -> None:
    """明确目录使用与 Project 相同的相对路径、忽略和有界读取实现。"""
    root = tmp_path / "sample"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("answer = 42\n", encoding="utf-8")
    (root / ".env").write_text("secret", encoding="utf-8")
    access = ReadOnlyFileAccess.for_explicit_path(make_policy(tmp_path), str(root))
    listing, reading, *_ = create_file_tools(access)

    root_page = json.loads(listing.invoke({}))
    assert root_page["items"][0]["path"] == "src"
    source = json.loads(reading.invoke({"path": "src/main.py"}))
    assert source["access_source"] == "explicit"
    assert source["lines"] == ["answer = 42"]
    denied = json.loads(reading.invoke({"path": ".env"}))
    assert denied["ok"] is False
    assert "secret" not in str(denied)


def test_explicit_scope_rejects_outside_sensitive_and_replaced_target(
    tmp_path: Path,
) -> None:
    """允许根外、敏感文件和身份替换均失败关闭，不返回替换后的正文。"""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    selected = allowed / "selected.py"
    selected.write_text("original", encoding="utf-8")
    secret = allowed / ".env"
    secret.write_text("secret", encoding="utf-8")
    policy = make_policy(allowed)

    with pytest.raises(ProjectError, match="project_root_not_allowed"):
        ReadOnlyFileAccess.for_explicit_path(
            policy, str(outside / "missing.py")
        )
    with pytest.raises(ProjectError, match="project_root_not_allowed"):
        ReadOnlyFileAccess.for_explicit_path(policy, str(secret))

    access = ReadOnlyFileAccess.for_explicit_path(policy, str(selected))
    _, reading, *_ = create_file_tools(access)
    selected.rename(allowed / "old.py")
    selected.write_text("replacement", encoding="utf-8")
    result = json.loads(reading.invoke({"path": "selected.py"}))
    assert result["ok"] is False
    assert "replacement" not in str(result)


def test_workspace_scope_exposes_all_allowed_roots_through_virtual_paths(
    tmp_path: Path,
) -> None:
    """普通 Thread 始终可浏览允许根，但工具结果不暴露宿主绝对路径。"""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "README.md").write_text("first root\n", encoding="utf-8")
    (second / "main.py").write_text("answer = 42\n", encoding="utf-8")
    policy = ProjectRootPolicy(allowed_roots=(first, second))
    access = ReadOnlyFileAccess.for_allowed_roots(policy)
    tools = create_file_tools(access)
    listing, reading, creating, replacing, writing = (
        tools[0],
        tools[1],
        tools[4],
        tools[5],
        tools[6],
    )

    roots = json.loads(listing.invoke({}))
    assert roots["access_source"] == "workspace"
    assert [item["path"] for item in roots["items"]] == [
        "workspace-1",
        "workspace-2",
    ]
    assert str(first) not in json.dumps(roots)
    second_page = json.loads(listing.invoke({"path": "workspace-2"}))
    assert second_page["items"][0]["path"] == "workspace-2/main.py"
    source = json.loads(
        reading.invoke({"path": "workspace-2/main.py"})
    )
    assert source["path"] == "workspace-2/main.py"
    assert source["lines"] == ["answer = 42"]
    denied = json.loads(reading.invoke({"path": str(first / "README.md")}))
    assert denied["error"]["code"] == "file_access_path_out_of_scope"
    created = json.loads(
        creating.invoke(
            {"path": "workspace-2/created.txt", "content": "ordinary write\n"}
        )
    )
    assert created["ok"] is True
    assert created["path"] == "workspace-2/created.txt"
    assert (second / "created.txt").read_text(encoding="utf-8") == "ordinary write\n"
    replaced = json.loads(
        replacing.invoke(
            {
                "path": "workspace-2/main.py",
                "old_str": "answer = 42",
                "new_str": "answer = 43",
            }
        )
    )
    assert replaced["ok"] is True
    assert replaced["path"] == "workspace-2/main.py"
    assert (second / "main.py").read_text(encoding="utf-8") == "answer = 43\n"
    written = json.loads(
        writing.invoke(
            {"path": "workspace-2/main.py", "content": "answer = 44\nready = True\n"}
        )
    )
    assert written["ok"] is True
    assert written["path"] == "workspace-2/main.py"
    assert (second / "main.py").read_text(encoding="utf-8") == (
        "answer = 44\nready = True\n"
    )


@pytest.mark.parametrize("scope", ["workspace", "explicit"])
def test_directory_creation_scopes_and_existing_targets(tmp_path, scope):
    policy = ProjectRootPolicy(allowed_roots=(tmp_path,))
    access = (ReadOnlyFileAccess.for_allowed_roots(policy) if scope == "workspace"
              else ReadOnlyFileAccess.for_explicit_path(policy, str(tmp_path)))
    prefix = "workspace-1/" if scope == "workspace" else ""
    tool = next(t for t in create_file_tools(access) if t.name == "create_directory")
    assert json.loads(tool.invoke({"path": prefix + "generated"}))["created"] is True
    (tmp_path / "generated/keep.txt").write_text("keep")
    assert json.loads(tool.invoke({"path": prefix + "generated"}))["created"] is False
    assert (tmp_path / "generated/keep.txt").read_text() == "keep"
    assert json.loads(tool.invoke({"path": prefix + "missing/child"}))["ok"] is False
    assert not (tmp_path / "missing").exists()
    assert json.loads(tool.invoke({"path": prefix + "generated/keep.txt"}))["ok"] is False
    assert json.loads(tool.invoke({"path": prefix + "../escape"}))["ok"] is False


@pytest.mark.parametrize("scope", ["workspace", "explicit"])
def test_rename_preserves_bytes_and_rejects_existing_target(tmp_path, scope):
    policy = ProjectRootPolicy(allowed_roots=(tmp_path,))
    access = (ReadOnlyFileAccess.for_allowed_roots(policy) if scope == "workspace"
              else ReadOnlyFileAccess.for_explicit_path(policy, str(tmp_path)))
    prefix = "workspace-1/" if scope == "workspace" else ""
    (tmp_path / "old.txt").write_bytes(b"original\r\n")
    tool = next(t for t in create_file_tools(access) if t.name == "rename_file")
    result = json.loads(tool.invoke({"path": prefix + "old.txt", "new_name": "new.txt"}))
    assert result["renamed"] is True
    assert result["previous_path"] == prefix + "old.txt"
    assert result["path"] == prefix + "new.txt"
    assert not (tmp_path / "old.txt").exists()
    assert (tmp_path / "new.txt").read_bytes() == b"original\r\n"
    (tmp_path / "taken.txt").write_text("keep")
    assert json.loads(tool.invoke({"path": prefix + "new.txt", "new_name": "taken.txt"}))["ok"] is False
    assert (tmp_path / "taken.txt").read_text() == "keep"
    assert (tmp_path / "new.txt").read_bytes() == b"original\r\n"
    assert json.loads(tool.invoke({"path": prefix + "new.txt", "new_name": "../escape.txt"}))["ok"] is False


@pytest.mark.parametrize("scope", ["workspace", "explicit"])
def test_move_file_between_directories_without_overwriting(tmp_path, scope):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    (source_dir / "item.txt").write_bytes(b"move me\r\n")
    policy = ProjectRootPolicy(allowed_roots=(tmp_path,))
    access = (
        ReadOnlyFileAccess.for_allowed_roots(policy)
        if scope == "workspace"
        else ReadOnlyFileAccess.for_explicit_path(policy, str(tmp_path))
    )
    prefix = "workspace-1/" if scope == "workspace" else ""
    tool = next(t for t in create_file_tools(access) if t.name == "move_file")

    result = json.loads(
        tool.invoke(
            {
                "path": prefix + "source/item.txt",
                "new_path": prefix + "target/item.txt",
            }
        )
    )
    assert result["moved"] is True
    assert result["previous_path"] == prefix + "source/item.txt"
    assert result["path"] == prefix + "target/item.txt"
    assert not (source_dir / "item.txt").exists()
    assert (target_dir / "item.txt").read_bytes() == b"move me\r\n"

    (source_dir / "other.txt").write_text("source", encoding="utf-8")
    denied = json.loads(
        tool.invoke(
            {
                "path": prefix + "source/other.txt",
                "new_path": prefix + "target/item.txt",
            }
        )
    )
    assert denied["error"]["code"] == "file_already_exists"
    assert (source_dir / "other.txt").read_text(encoding="utf-8") == "source"


def test_move_file_rejects_cross_workspace_roots(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "item.txt").write_text("keep", encoding="utf-8")
    access = ReadOnlyFileAccess.for_allowed_roots(
        ProjectRootPolicy(allowed_roots=(first, second))
    )
    tool = next(t for t in create_file_tools(access) if t.name == "move_file")
    result = json.loads(
        tool.invoke(
            {"path": "workspace-1/item.txt", "new_path": "workspace-2/item.txt"}
        )
    )
    assert result["error"]["code"] == "file_access_path_out_of_scope"
    assert (first / "item.txt").read_text(encoding="utf-8") == "keep"
    assert not (second / "item.txt").exists()


@pytest.mark.parametrize("scope", ["workspace", "explicit"])
def test_delete_file_removes_only_regular_file(tmp_path, scope):
    target = tmp_path / "delete-me.txt"
    target.write_text("temporary", encoding="utf-8")
    directory = tmp_path / "keep-directory"
    directory.mkdir()
    (directory / "keep.txt").write_text("keep", encoding="utf-8")
    policy = ProjectRootPolicy(allowed_roots=(tmp_path,))
    access = (
        ReadOnlyFileAccess.for_allowed_roots(policy)
        if scope == "workspace"
        else ReadOnlyFileAccess.for_explicit_path(policy, str(tmp_path))
    )
    prefix = "workspace-1/" if scope == "workspace" else ""
    tool = next(t for t in create_file_tools(access) if t.name == "delete_file")

    result = json.loads(tool.invoke({"path": prefix + "delete-me.txt"}))
    assert result["deleted"] is True
    assert result["path"] == prefix + "delete-me.txt"
    assert result["deleted_content_preview"] == "temporary"
    assert result["deleted_content_truncated"] is False
    assert not target.exists()

    long_target = tmp_path / "delete-long.txt"
    long_target.write_text("旧" * 4001, encoding="utf-8")
    long_result = json.loads(
        tool.invoke({"path": prefix + "delete-long.txt"})
    )
    assert long_result["deleted_content_preview"] == "旧" * 4000
    assert long_result["deleted_content_truncated"] is True

    binary_target = tmp_path / "delete-binary.bin"
    binary_target.write_bytes(b"\x00\x01")
    binary_result = json.loads(
        tool.invoke({"path": prefix + "delete-binary.bin"})
    )
    assert "deleted_content_preview" not in binary_result
    assert not binary_target.exists()

    denied = json.loads(tool.invoke({"path": prefix + "keep-directory"}))
    assert denied["error"]["code"] == "file_delete_unsupported"
    assert (directory / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_explicit_single_file_scope_can_delete_only_selected_file(tmp_path):
    selected = tmp_path / "selected.txt"
    sibling = tmp_path / "sibling.txt"
    selected.write_text("selected", encoding="utf-8")
    sibling.write_text("sibling", encoding="utf-8")
    access = ReadOnlyFileAccess.for_explicit_path(
        ProjectRootPolicy(allowed_roots=(tmp_path,)), str(selected)
    )
    tools = create_file_tools(access)
    assert [tool.name for tool in tools] == [
        "list_files",
        "read_file",
        "glob_files",
        "search_files",
        "str_replace",
        "write_file",
        "delete_file",
    ]
    deleting = tools[-1]
    denied = json.loads(deleting.invoke({"path": "sibling.txt"}))
    assert denied["error"]["code"] == "file_access_path_out_of_scope"
    result = json.loads(deleting.invoke({"path": "selected.txt"}))
    assert result["deleted"] is True
    assert not selected.exists()
    assert sibling.read_text(encoding="utf-8") == "sibling"
