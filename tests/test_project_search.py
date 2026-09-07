"""验证项目与普通 Thread 共用的有界文件名 glob。"""

import json
from pathlib import Path

from mini_deer_agent.application.workspaces import ReadOnlyFileAccess
from mini_deer_agent.tools.project_files import create_file_tools
from mini_deer_agent.workspace.paths import ProjectRootPolicy
from mini_deer_agent.workspace.search import search_project_files


def test_directory_glob_matches_root_and_nested_files_but_ignores_secrets(
    tmp_path: Path,
) -> None:
    """常用 ** 模式覆盖根文件，且不会进入固定忽略目录。"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "app.py").write_text("root", encoding="utf-8")
    (root / "pkg").mkdir()
    (root / "pkg" / "util.py").write_text("nested", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "secret.py").write_text(
        "secret", encoding="utf-8"
    )
    (root / ".env").write_text("TOKEN=secret", encoding="utf-8")
    access = ReadOnlyFileAccess.for_explicit_path(
        ProjectRootPolicy(allowed_roots=(root,)), str(root)
    )
    globbing = create_file_tools(access)[2]

    result = json.loads(globbing.invoke({"pattern": "**/*.py"}))

    assert result["ok"] is True
    assert result["matches"] == ["app.py", "pkg/util.py"]
    assert result["truncated"] is False
    assert "secret.py" not in str(result)
    assert "TOKEN" not in str(result)


def test_glob_reports_result_limit_and_rejects_scope_changing_patterns(
    tmp_path: Path,
) -> None:
    """结果上限显式标记，绝对路径与父级片段不能改变搜索根。"""
    root = tmp_path / "source"
    root.mkdir()
    for index in range(4):
        (root / f"file-{index}.md").write_text("x", encoding="utf-8")
    access = ReadOnlyFileAccess.for_explicit_path(
        ProjectRootPolicy(allowed_roots=(root,)), str(root)
    )
    globbing = create_file_tools(access)[2]

    limited = json.loads(
        globbing.invoke({"pattern": "*.md", "limit": 2})
    )
    assert limited["matches"] == ["file-0.md", "file-1.md"]
    assert limited["truncated"] is True
    assert limited["truncation_reason"] == "result_limit"
    absolute = json.loads(globbing.invoke({"pattern": "/**/*.md"}))
    parent = json.loads(globbing.invoke({"pattern": "../*.md"}))
    assert absolute["error"]["code"] == "file_glob_pattern_invalid"
    assert parent["error"]["code"] == "file_glob_pattern_invalid"


def test_workspace_glob_searches_all_roots_and_returns_only_virtual_paths(
    tmp_path: Path,
) -> None:
    """普通 Thread 可跨允许根找文件，结果继续使用 workspace-N 前缀。"""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "README.md").write_text("first", encoding="utf-8")
    (second / "README.md").write_text("second", encoding="utf-8")
    access = ReadOnlyFileAccess.for_allowed_roots(
        ProjectRootPolicy(allowed_roots=(first, second))
    )
    globbing = create_file_tools(access)[2]

    result = json.loads(globbing.invoke({"pattern": "README.md"}))

    assert result["matches"] == [
        "workspace-1/README.md",
        "workspace-2/README.md",
    ]
    rendered = json.dumps(result)
    assert str(first) not in rendered
    assert str(second) not in rendered


def test_single_file_glob_never_expands_to_its_parent_directory(
    tmp_path: Path,
) -> None:
    """单文件 Scope 只匹配自身名称，不能借 glob 找到兄弟文件。"""
    selected = tmp_path / "selected.py"
    sibling = tmp_path / "sibling.py"
    selected.write_text("selected", encoding="utf-8")
    sibling.write_text("sibling", encoding="utf-8")
    access = ReadOnlyFileAccess.for_explicit_path(
        ProjectRootPolicy(allowed_roots=(tmp_path,)), str(selected)
    )
    globbing = create_file_tools(access)[2]

    result = json.loads(globbing.invoke({"pattern": "*.py"}))

    assert result["matches"] == ["selected.py"]
    assert "sibling.py" not in str(result)


def test_content_search_returns_virtual_paths_real_lines_and_glob_filter(
    tmp_path: Path,
) -> None:
    """正文搜索按文件模式筛选，并返回可直接引用的真实行号。"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.py").write_text(
        "def greet(name: str):\n    return f'Hello, {name}'\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("GREET is documented\n", encoding="utf-8")
    (root / "pkg").mkdir()
    (root / "pkg" / "use.py").write_text(
        "from main import greet\n\nprint(greet('Mini Deer'))\n",
        encoding="utf-8",
    )
    access = ReadOnlyFileAccess.for_explicit_path(
        ProjectRootPolicy(allowed_roots=(root,)), str(root)
    )
    searching = create_file_tools(access)[3]

    result = json.loads(
        searching.invoke(
            {"query": "GREET", "file_pattern": "**/*.py", "limit": 10}
        )
    )

    assert result["matches"] == [
        {"path": "main.py", "line_number": 1, "line": "def greet(name: str):"},
        {
            "path": "pkg/use.py",
            "line_number": 1,
            "line": "from main import greet",
        },
        {
            "path": "pkg/use.py",
            "line_number": 3,
            "line": "print(greet('Mini Deer'))",
        },
    ]
    assert result["truncated"] is False
    assert result["scanned_files"] == 2
    assert "GREET is documented" not in str(result)


def test_content_search_reports_limits_and_unsupported_content(
    tmp_path: Path,
) -> None:
    """匹配上限与不可搜索文件都显式声明，不能伪装成完整结果。"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.txt").write_text("needle one\nneedle two\n", encoding="utf-8")
    (root / "binary.bin").write_bytes(b"needle\x00secret")
    access = ReadOnlyFileAccess.for_explicit_path(
        ProjectRootPolicy(allowed_roots=(root,)), str(root)
    )
    searching = create_file_tools(access)[3]

    limited = json.loads(searching.invoke({"query": "needle", "limit": 1}))
    assert limited["matches"] == [
        {"path": "a.txt", "line_number": 1, "line": "needle one"}
    ]
    assert limited["truncated"] is True
    assert limited["truncation_reason"] == "result_limit"
    unsupported = json.loads(
        searching.invoke({"query": "absent", "file_pattern": "*.bin"})
    )
    assert unsupported["matches"] == []
    assert unsupported["truncated"] is True
    assert unsupported["truncation_reason"] == "unsupported_content"
    assert unsupported["skipped_files"] == 1
    assert "secret" not in str(unsupported)
    invalid = json.loads(searching.invoke({"query": "bad\nquery"}))
    assert invalid["error"]["code"] == "file_search_query_invalid"


def test_workspace_content_search_uses_aliases_and_single_file_stays_scoped(
    tmp_path: Path,
) -> None:
    """普通 Thread 跨根只返回别名，单文件授权不会搜索兄弟文件。"""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    selected = first / "selected.py"
    sibling = first / "sibling.py"
    selected.write_text("target = 'needle'\n", encoding="utf-8")
    sibling.write_text("other = 'needle'\n", encoding="utf-8")
    (first / "binary.bin").write_bytes(b"needle\x00hidden")
    (second / "main.py").write_text("value = 'needle'\n", encoding="utf-8")
    policy = ProjectRootPolicy(allowed_roots=(first, second))
    workspace = ReadOnlyFileAccess.for_allowed_roots(policy)
    workspace_search = create_file_tools(workspace)[3]

    result = json.loads(workspace_search.invoke({"query": "needle"}))

    assert [match["path"] for match in result["matches"]] == [
        "workspace-1/selected.py",
        "workspace-1/sibling.py",
        "workspace-2/main.py",
    ]
    assert str(first) not in str(result)
    assert str(second) not in str(result)
    assert result["truncated"] is True
    assert result["truncation_reason"] == "unsupported_content"

    file_access = ReadOnlyFileAccess.for_explicit_path(policy, str(selected))
    file_search = create_file_tools(file_access)[3]
    file_result = json.loads(file_search.invoke({"query": "needle"}))
    assert [match["path"] for match in file_result["matches"]] == ["selected.py"]
    assert "sibling.py" not in str(file_result)


def test_content_search_preserves_late_match_in_summary_and_reports_file_budget(
    tmp_path: Path,
) -> None:
    """长行摘要必须包含命中正文，文件预算耗尽要给出稳定原因。"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "a.py").write_text(f"{'x' * 600}needle tail\n", encoding="utf-8")
    (root / "b.py").write_text("needle second\n", encoding="utf-8")

    result = search_project_files(
        root,
        "",
        "needle",
        file_pattern="*.py",
        file_limit=1,
    )

    assert result["matches"][0]["line"].startswith("…")
    assert "needle tail" in result["matches"][0]["line"]
    assert result["truncated"] is True
    assert result["truncation_reason"] == "file_limit"
    assert result["scanned_files"] == 1
