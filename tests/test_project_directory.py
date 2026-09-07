"""保护单层目录列举的边界、预算和刷新语义。"""

from pathlib import Path
import pytest
from mini_deer_agent.workspace.directory import list_directory
from mini_deer_agent.domain.workspaces import ProjectError


def test_list_is_shallow_bounded_and_refreshes(tmp_path: Path):
    """每次只列直接子项；外部新增后再次调用可见，超量明确截断。"""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "nested.py").write_text("secret body")
    (tmp_path / ".env").write_text("secret")
    (tmp_path / "empty.txt").touch()
    result = list_directory(tmp_path, "", limit=100)
    assert len(result["items"]) == 3
    assert (
        next(x for x in result["items"] if x["name"] == ".env")["status"] == "ignored"
    )
    assert "nested.py" not in str(result)
    (tmp_path / "new.txt").touch()
    assert len(list_directory(tmp_path, "", limit=100)["items"]) == 4
    assert list_directory(tmp_path, "", limit=1)["truncated"] is True
    assert (
        list_directory(tmp_path, "src", limit=100)["items"][0]["path"]
        == "src/nested.py"
    )


@pytest.mark.parametrize(
    "path",
    [
        "../x",
        "/tmp",
        "C:/foo",
        "a\\..\\b",
        ".git",
        ".env",
        "a:stream",
        "foo.",
        "CON",
        "a//b",
    ],
)
def test_reject_paths(tmp_path: Path, path: str):
    """不能用路径别名、敏感目录或越界访问绕过树入口。"""
    with pytest.raises(ProjectError):
        list_directory(tmp_path, path, limit=100)


def test_missing_is_not_empty(tmp_path: Path):
    """无法访问不能伪装成空目录。"""
    with pytest.raises(ProjectError):
        list_directory(tmp_path, "missing", limit=100)


def test_link_is_not_followed(tmp_path: Path):
    """链接只展示拒绝状态，不能进一步展开。"""
    (tmp_path / "target").mkdir()
    try:
        (tmp_path / "link").symlink_to(tmp_path / "target", target_is_directory=True)
    except OSError:
        pytest.skip("当前账户没有符号链接权限")
    result = list_directory(tmp_path, "", limit=100)
    assert (
        next(x for x in result["items"] if x["name"] == "link")["status"]
        == "unavailable"
    )
    with pytest.raises(ProjectError):
        list_directory(tmp_path, "link", limit=100)
