"""验证只读源码分段、编码与路径边界，不读取用户真实文件。"""

from pathlib import Path
import pytest
from mini_deer_agent.workspace.files import read_project_file
from mini_deer_agent.domain.workspaces import ProjectError


def test_utf8_bom_crlf_and_pages(tmp_path: Path):
    """去除显示用 BOM，CRLF 行号不漂移，下一段不丢行。"""
    data = "\ufeff第一行\r\n第二行\r\n第三行\r\n".encode()
    file = tmp_path / "main.py"
    file.write_bytes(data)
    first = read_project_file(tmp_path, "main.py", start_line=1, limit=2)
    assert first["lines"] == ["第一行", "第二行"]
    assert first["next_line"] == 3
    second = read_project_file(tmp_path, "main.py", start_line=3, limit=2)
    assert second["lines"] == ["第三行"]
    assert second["next_line"] is None
    assert first["revision"] == second["revision"]
    assert file.read_bytes() == data


def test_empty_binary_and_size(tmp_path: Path):
    """空文本可显示；二进制和超限文件不回传正文。"""
    f = tmp_path / "test.txt"
    f.touch()
    assert read_project_file(tmp_path, "test.txt")["lines"] == []
    f.write_bytes(b"\x00private")
    assert read_project_file(tmp_path, "test.txt")["status"] == "binary"
    f.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    assert read_project_file(tmp_path, "test.txt")["status"] == "too_large"


@pytest.mark.parametrize(
    "path", ["../x", ".env", "node_modules/x", "/x", "C:/x", "a:stream", "", "CON"]
)
def test_reject_path(tmp_path: Path, path: str):
    """读取必须与目录树共享根内路径和忽略约束。"""
    with pytest.raises(ProjectError):
        read_project_file(tmp_path, path)


def test_reject_link_and_directory(tmp_path: Path):
    """即便链接指向根内也拒绝，文件接口不接受目录。"""
    (tmp_path / "folder").mkdir()
    with pytest.raises(ProjectError):
        read_project_file(tmp_path, "folder")
    (tmp_path / "target.txt").write_text("private")
    try:
        (tmp_path / "link.txt").symlink_to(tmp_path / "target.txt")
    except OSError:
        pytest.skip("没有符号链接权限")
    with pytest.raises(ProjectError):
        read_project_file(tmp_path, "link.txt")


def test_character_budget_encoding_and_revision(tmp_path: Path):
    """超长行明确报状态，不静默丢字符；编辑后版本摘要改变。"""
    f = tmp_path / "x.txt"
    f.write_text("x" * 20000 + "\n" + "y" * 20000, encoding="utf-8")
    first = read_project_file(tmp_path, "x.txt")
    assert first["next_line"] == 2
    assert len(first["lines"]) == 1
    f.write_text("x" * 40000, encoding="utf-8")
    second = read_project_file(tmp_path, "x.txt")
    assert second["status"] == "line_too_long"
    assert second["lines"] == []
    assert first["revision"] != second["revision"]
    f.write_bytes(b"\xff")
    assert read_project_file(tmp_path, "x.txt")["status"] == "unsupported_encoding"
