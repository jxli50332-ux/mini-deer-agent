"""以真实主图和临时项目验证工具执行、证据回传及普通聊天隔离。"""

import asyncio
import json
import runpy
from importlib import import_module
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from test_agent import ToolAwareFakeModel
from mini_deer_agent.agents import AgentPromptContext, build_agent_graph
from mini_deer_agent.agents.subagent import SubagentExecutionResult
from mini_deer_agent.application.run_stream import RunStreamService
from mini_deer_agent.application.workspaces import (
    ProjectFileAccessResolver,
    ProjectService,
    ReadOnlyFileAccess,
)
from mini_deer_agent.domain.workspaces import ProjectError
from mini_deer_agent.persistence.conversations import (
    open_sqlite_conversation_repository,
)
from mini_deer_agent.skills import BuiltInSkill, BuiltInSkillCatalog
from mini_deer_agent.tools import execution_environment, project_sandbox
from mini_deer_agent.workspace.paths import ProjectRootPolicy


@pytest.fixture
def project(tmp_path: Path):
    """使用真实文件和临时登记库，不读取用户数据或调用在线模型。"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.py").write_text("# 示例\nanswer = 42\n", encoding="utf-8")
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repo:
        service = ProjectService(
            repo.projects, ProjectRootPolicy(allowed_roots=(root,))
        )
        record = service.register(name="样例", root_path=str(root))
        yield service, record


def call(name: str, args: dict, identity: str) -> AIMessage:
    """生成可追踪的模型工具请求，实际执行仍由主图完成。"""
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": identity}]
    )


@pytest.mark.parametrize("asynchronous", [False, True])
def test_project_graph_reads_real_evidence(project, asynchronous):
    """模型请求、ToolNode 执行和下一次模型输入使用同一绑定项目。"""
    service, record = project
    model = ToolAwareFakeModel(
        responses=[
            call("list_files", {}, "list-1"),
            call(
                "read_file",
                {"path": "main.py", "start_line": 2, "limit": 1},
                "read-1",
            ),
            AIMessage(content="main.py:2 定义了 answer。"),
        ]
    )
    graph = build_agent_graph(
        model, project_service=service, project_id=record.project_id
    )
    state = {"messages": [HumanMessage(content="解释项目的 main.py")]}
    result = asyncio.run(graph.ainvoke(state)) if asynchronous else graph.invoke(state)
    evidence = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in evidence] == ["list-1", "read-1"]
    assert json.loads(evidence[0].text)["items"][0]["path"] == "main.py"
    source = json.loads(evidence[1].text)
    assert source["project_id"] == record.project_id
    assert source["lines"] == ["answer = 42"]
    assert source["line_numbers"] == [2]
    assert source["start_line"] == 2
    assert any(m == evidence[1] for m in model.received_histories[-1])
    prompt = model.received_histories[0][0].text
    assert record.project_id in prompt and "read_write" in prompt
    assert record.root_path not in prompt
    assert "<project_root_overview>" in prompt
    assert "[file] main.py" in prompt
    assert "用户无需手动引用文件" in prompt
    # 完整性只能由工具的结构化字段决定，不能由正文结尾形式猜测。
    assert "`read_file.next_line = null` 表示文件已读到末尾" in prompt
    assert "不得根据正文是否以标点或换行结尾猜测截断" in prompt
    assert {"list_files", "read_file"}.issubset(model.bound_tool_names)


def test_project_reader_inherits_frozen_scope_and_active_skill_intersection(
    project,
    tmp_path: Path,
) -> None:
    """project-reader 只能看到父 Run 项目只读工具，且不能读取根外文件。"""
    service, record = project
    access = ReadOnlyFileAccess.for_project(service, record.project_id)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("不得读取", encoding="utf-8")
    catalog = BuiltInSkillCatalog(
        skills=(
            BuiltInSkill(
                name="reader-skill",
                description="允许项目委派读取。",
                instructions="委派 project-reader 查找真实证据。",
                source_file=Path("reader-skill/SKILL.md"),
                allowed_tools=("task", "read_file"),
            ),
        )
    )
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": "读取项目证据",
                            "prompt": "读取 main.py，并确认根外文件不可访问。",
                            "subagent_type": "project-reader",
                        },
                        "id": "call-project-reader",
                        "type": "tool_call",
                    }
                ],
            ),
            call("read_file", {"path": "main.py"}, "child-read-project"),
            call(
                "read_file",
                {"path": str(outside)},
                "child-read-outside",
            ),
            AIMessage(content="项目文件可读，根外文件被拒绝。"),
            AIMessage(content="已核验 project-reader 的只读结果。"),
        ]
    )

    result = build_agent_graph(
        model,
        file_access=access,
        skill_catalog=catalog,
    ).invoke(
        {
            "messages": [
                HumanMessage(content="/reader-skill 检查项目与根外访问边界。")
            ]
        }
    )

    assert ["read_file"] in model.bound_tool_name_histories
    assert "`project-reader` 只继承本 Run 冻结范围" in (
        model.received_histories[0][0].text
    )
    child_histories = [
        history
        for history in model.received_histories
        if "project-reader 子 Agent" in history[0].text
    ]
    child_results = {
        message.tool_call_id: json.loads(message.text)
        for message in child_histories[-1]
        if isinstance(message, ToolMessage)
    }
    assert child_results["child-read-project"]["project_id"] == record.project_id
    assert child_results["child-read-project"]["lines"][1] == "answer = 42"
    assert child_results["child-read-outside"]["ok"] is False
    assert child_results["child-read-outside"]["error"]["code"] == (
        "project_path_invalid"
    )
    task_result = next(
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == "task"
    )
    assert json.loads(task_result.text)["subagent_type"] == "project-reader"
    assert result["messages"][-1].text == "已核验 project-reader 的只读结果。"


def test_test_runner_executes_only_in_parent_project_sandbox(
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """test-runner 继承冻结项目命令工具，但看不到任何文件写工具。"""
    service, record = project
    access = ReadOnlyFileAccess.for_project(service, record.project_id)
    executions: list[tuple[Path, str]] = []

    def run_check(
        path: Path,
        command: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        executions.append((path, command))
        return {
            "command_completed": True,
            "exit_code": 0,
            "stdout": "1 test passed\n",
            "stderr": "",
            "released": True,
        }

    monkeypatch.setattr(
        project_sandbox,
        "run_docker_project_command",
        run_check,
    )

    async def run_check_async(
        path: Path,
        command: str,
        **kwargs: object,
    ) -> dict[str, object]:
        return run_check(path, command, **kwargs)

    monkeypatch.setattr(
        project_sandbox,
        "run_docker_project_command_async",
        run_check_async,
    )
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": "运行聚焦测试",
                            "prompt": "运行 python -m unittest 并返回证据。",
                            "subagent_type": "test-runner",
                        },
                        "id": "call-test-runner",
                        "type": "tool_call",
                    }
                ],
            ),
            call(
                "run_project_command",
                {
                    "description": "运行聚焦测试",
                    "command": "python -m unittest",
                },
                "child-run-tests",
            ),
            AIMessage(content="测试 exit 0，1 test passed。"),
            AIMessage(content="已核验测试通过。"),
        ]
    )

    result = build_agent_graph(model, file_access=access).invoke(
        {"messages": [HumanMessage(content="委派测试并汇总结论。")]}
    )

    expected_tools = [
        "inspect_execution_environment",
        "inspect_project_sandbox",
        "run_project_command",
    ]
    assert expected_tools in model.bound_tool_name_histories
    child_history = next(
        history
        for history in reversed(model.received_histories)
        if "test-runner 子 Agent" in history[0].text
        and any(isinstance(message, ToolMessage) for message in history)
    )
    tool_result = next(
        message for message in child_history if isinstance(message, ToolMessage)
    )
    assert json.loads(tool_result.text)["exit_code"] == 0
    assert executions == [(Path(record.root_path), "python -m unittest")]
    task_result = next(
        message
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == "task"
    )
    assert json.loads(task_result.text)["subagent_type"] == "test-runner"
    assert all(
        "write_file" not in names and "str_replace" not in names
        for names in model.bound_tool_name_histories
        if names == expected_tools
    )


def test_main_parallel_reader_and_runner_then_serially_fixes_project(
    project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主 Agent 可并行取得读/测证据，但只有主图执行修改和最终检查。"""
    service, record = project
    access = ReadOnlyFileAccess.for_project(service, record.project_id)
    subagent_module = import_module("mini_deer_agent.agents.subagent")
    started_roles: set[str] = set()
    selected_tools: dict[str, set[str]] = {}
    both_started = asyncio.Event()

    async def run_specialist(
        _model,
        prompt: str,
        **options: object,
    ) -> SubagentExecutionResult:
        config = options["config"]
        tools = options["available_tools"]
        role = config.name
        started_roles.add(role)
        selected_tools[role] = {tool.name for tool in tools}
        if len(started_roles) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        if role == "project-reader":
            assert "定位" in prompt
            return SubagentExecutionResult("main.py:2 的 answer 应改为 43。")
        assert role == "test-runner"
        assert "测试" in prompt
        return SubagentExecutionResult("检查预期 answer == 43，当前失败。")

    monkeypatch.setattr(
        subagent_module,
        "async_run_subagent",
        run_specialist,
    )
    commands: list[str] = []

    def run_check(
        path: Path,
        command: str,
        **_kwargs: object,
    ) -> dict[str, object]:
        commands.append(command)
        passed = "answer = 43" in (path / "main.py").read_text(encoding="utf-8")
        return {
            "command_completed": True,
            "exit_code": 0 if passed else 1,
            "stdout": "1 test passed\n" if passed else "",
            "stderr": "answer mismatch\n" if not passed else "",
            "released": True,
        }

    monkeypatch.setattr(
        project_sandbox,
        "run_docker_project_command",
        run_check,
    )
    async def run_parallel_check_async(
        path: Path,
        command: str,
        **kwargs: object,
    ) -> dict[str, object]:
        return run_check(path, command, **kwargs)

    monkeypatch.setattr(
        project_sandbox,
        "run_docker_project_command_async",
        run_parallel_check_async,
    )
    model = ToolAwareFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "args": {
                            "description": "定位缺陷",
                            "prompt": "只读定位 answer 缺陷和修改位置。",
                            "subagent_type": "project-reader",
                        },
                        "id": "call-reader-parallel",
                        "type": "tool_call",
                    },
                    {
                        "name": "task",
                        "args": {
                            "description": "诊断测试",
                            "prompt": "运行或分析相关测试失败证据。",
                            "subagent_type": "test-runner",
                        },
                        "id": "call-runner-parallel",
                        "type": "tool_call",
                    },
                ],
            ),
            call(
                "str_replace",
                {
                    "path": "main.py",
                    "old_str": "answer = 42",
                    "new_str": "answer = 43",
                },
                "main-fix",
            ),
            call(
                "run_project_command",
                {
                    "description": "主 Agent 最终回归",
                    "command": "python -m unittest",
                },
                "main-final-check",
            ),
            AIMessage(content="已根据并行证据修复，并完成最终检查。"),
        ]
    )

    result = asyncio.run(
        build_agent_graph(model, file_access=access).ainvoke(
            {"messages": [HumanMessage(content="定位并修复 answer 测试失败。")]}
        )
    )

    assert started_roles == {"project-reader", "test-runner"}
    assert selected_tools["project-reader"] == {
        "list_files",
        "glob_files",
        "search_files",
        "read_file",
    }
    assert selected_tools["test-runner"] == {
        "inspect_execution_environment",
        "inspect_project_sandbox",
        "run_project_command",
    }
    assert all(
        "str_replace" not in names and "write_file" not in names
        for names in selected_tools.values()
    )
    assert (Path(record.root_path) / "main.py").read_text(encoding="utf-8") == (
        "# 示例\nanswer = 43\n"
    )
    assert commands == ["python -m unittest"]
    task_results = [
        json.loads(message.text)["subagent_type"]
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == "task"
    ]
    assert task_results == ["project-reader", "test-runner"]
    assert result["messages"][-1].text == (
        "已根据并行证据修复，并完成最终检查。"
    )


def test_project_file_scope_exposes_fixed_sandbox_mount_tool(project) -> None:
    """只有冻结的 Project 目录 Scope 才把无参数挂载诊断交给模型。"""
    service, record = project
    access = ReadOnlyFileAccess.for_project(service, record.project_id)
    model = ToolAwareFakeModel(responses=[AIMessage(content="已了解。")])

    build_agent_graph(model, file_access=access).invoke(
        {"messages": [HumanMessage(content="说明可用工具。")]}
    )

    assert {"inspect_project_sandbox", "run_project_command"}.issubset(
        model.bound_tool_names
    )
    prompt = model.received_histories[0][0].text
    assert "本 Run 已冻结的 Project 根" in prompt


def test_project_graph_repairs_failed_check_and_reruns_same_command(
    project, monkeypatch
) -> None:
    """主图保留失败证据，允许模型读取、修正并重跑同一检查。"""
    service, record = project
    access = ReadOnlyFileAccess.for_project(service, record.project_id)
    commands: list[str] = []

    monkeypatch.setattr(
        execution_environment,
        "inspect_docker_environment",
        lambda: {
            "ok": True,
            "provider": "docker",
            "available": True,
            "server_version": "test",
            "diagnostic_only": True,
            "message": "Docker 可用。",
        },
    )

    def run_check(path: Path, command: str, **_kwargs: object) -> dict[str, object]:
        commands.append(command)
        fixed = "answer = 43" in (path / "main.py").read_text(encoding="utf-8")
        return {
            "command_completed": True,
            "exit_code": 0 if fixed else 1,
            "stdout": "检查通过\n" if fixed else "",
            "stderr": "期望 answer = 43，实际为 42\n" if not fixed else "",
            "released": True,
        }

    monkeypatch.setattr(
        project_sandbox,
        "run_docker_project_command",
        run_check,
    )
    model = ToolAwareFakeModel(
        responses=[
            call("inspect_execution_environment", {}, "environment"),
            call(
                "run_project_command",
                {"description": "运行回归检查", "command": "python check.py"},
                "check-failed",
            ),
            call("read_file", {"path": "main.py"}, "read-failure-source"),
            call(
                "str_replace",
                {"path": "main.py", "old_str": "answer = 42", "new_str": "answer = 43"},
                "repair",
            ),
            call(
                "run_project_command",
                {"description": "重跑回归检查", "command": "python check.py"},
                "check-passed",
            ),
            AIMessage(content="已修复 main.py，并用同一命令重跑通过。"),
        ]
    )

    result = build_agent_graph(model, file_access=access).invoke(
        {"messages": [HumanMessage(content="修复失败检查并验证")]}
    )

    evidence = {
        message.tool_call_id: json.loads(message.text)
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    }
    assert evidence["check-failed"]["exit_code"] == 1
    assert evidence["check-failed"]["stderr"]
    assert evidence["repair"]["replaced"] is True
    assert evidence["check-passed"]["exit_code"] == 0
    assert commands == ["python check.py", "python check.py"]
    assert (Path(record.root_path) / "main.py").read_text(encoding="utf-8") == (
        "# 示例\nanswer = 43\n"
    )
    prompt = model.received_histories[0][0].text
    assert "不要在首次失败后立即结束" in prompt
    assert "再用同一检查命令重跑" in prompt


def test_project_graph_implements_behavior_with_focused_test(
    project, monkeypatch
) -> None:
    """新功能闭环可读取现有测试、修改实现和测试，再运行真实结果工具。"""
    service, record = project
    root = Path(record.root_path)
    tests_directory = root / "tests"
    tests_directory.mkdir()
    test_file = tests_directory / "test_main.py"
    test_file.write_text(
        "import unittest\n\n"
        "from main import answer\n\n\n"
        "class MainTests(unittest.TestCase):\n"
        "    def test_answer(self) -> None:\n"
        "        self.assertEqual(answer, 42)\n",
        encoding="utf-8",
    )
    access = ReadOnlyFileAccess.for_project(service, record.project_id)
    commands: list[str] = []

    monkeypatch.setattr(
        execution_environment,
        "inspect_docker_environment",
        lambda: {
            "ok": True,
            "provider": "docker",
            "available": True,
            "server_version": "test",
            "diagnostic_only": True,
            "message": "Docker 可用。",
        },
    )

    def run_tests(path: Path, command: str, **_kwargs: object) -> dict[str, object]:
        commands.append(command)
        source = (path / "main.py").read_text(encoding="utf-8")
        tests = (path / "tests" / "test_main.py").read_text(encoding="utf-8")
        passed = "def double(value: int) -> int:" in source and (
            "self.assertEqual(double(3), 6)" in tests
        )
        return {
            "command_completed": True,
            "exit_code": 0 if passed else 1,
            "stdout": "2 tests passed\n" if passed else "",
            "stderr": "new behavior is not covered\n" if not passed else "",
            "released": True,
        }

    monkeypatch.setattr(
        project_sandbox,
        "run_docker_project_command",
        run_tests,
    )
    original_test = test_file.read_text(encoding="utf-8")
    updated_test = original_test.replace(
        "from main import answer",
        "from main import answer, double",
    ).replace(
        "        self.assertEqual(answer, 42)\n",
        "        self.assertEqual(answer, 42)\n\n"
        "    def test_double(self) -> None:\n"
        "        self.assertEqual(double(3), 6)\n",
    )
    model = ToolAwareFakeModel(
        responses=[
            call("read_file", {"path": "main.py"}, "read-implementation"),
            call("read_file", {"path": "tests/test_main.py"}, "read-tests"),
            call(
                "str_replace",
                {
                    "path": "main.py",
                    "old_str": "answer = 42",
                    "new_str": (
                        "answer = 42\n\n\n"
                        "def double(value: int) -> int:\n"
                        "    return value * 2"
                    ),
                },
                "implement-feature",
            ),
            call(
                "write_file",
                {"path": "tests/test_main.py", "content": updated_test},
                "add-focused-test",
            ),
            call("inspect_execution_environment", {}, "environment-feature"),
            call(
                "run_project_command",
                {
                    "description": "运行项目测试",
                    "command": "python -m unittest discover -s tests -v",
                },
                "verify-feature",
            ),
            AIMessage(content="已实现新行为并补充测试，检查 exit 0。"),
        ]
    )

    result = build_agent_graph(model, file_access=access).invoke(
        {"messages": [HumanMessage(content="实现 double 并补测试验证")]}
    )

    evidence = {
        message.tool_call_id: json.loads(message.text)
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    }
    assert evidence["implement-feature"]["replaced"] is True
    assert evidence["add-focused-test"]["changed"] is True
    assert evidence["verify-feature"]["exit_code"] == 0
    assert commands == ["python -m unittest discover -s tests -v"]
    assert "def double(value: int) -> int:" in (root / "main.py").read_text(
        encoding="utf-8"
    )
    assert "self.assertEqual(double(3), 6)" in test_file.read_text(
        encoding="utf-8"
    )
    prompt = model.received_histories[0][0].text
    assert "为新行为新增或更新最小聚焦测试" in prompt


def test_project_graph_creates_and_reads_new_file(project) -> None:
    """主 Agent 可在项目根创建新文本文件，并通过读取结果核对落盘内容。"""
    service, record = project
    model = ToolAwareFakeModel(
        responses=[
            call(
                "create_file",
                {"path": "agent-created.txt", "content": "created by agent\n"},
                "create-1",
            ),
            call("read_file", {"path": "agent-created.txt"}, "verify-create-1"),
            AIMessage(content="已创建并核对 agent-created.txt。"),
        ]
    )

    result = build_agent_graph(
        model, project_service=service, project_id=record.project_id
    ).invoke({"messages": [HumanMessage(content="创建 agent-created.txt")]})

    evidence = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    created, verified = (json.loads(message.text) for message in evidence)
    assert created["created"] is True
    assert created["path"] == "agent-created.txt"
    assert verified["lines"] == ["created by agent"]
    assert (Path(record.root_path) / "agent-created.txt").read_text(
        encoding="utf-8"
    ) == "created by agent\n"
    assert "create_file" in model.bound_tool_names
    assert "目标已存在时会失败" in model.received_histories[0][0].text


def test_project_graph_precisely_edits_and_reads_existing_file(project) -> None:
    """主 Agent 可精确编辑已有文件，并读回确认实际内容。"""
    service, record = project
    model = ToolAwareFakeModel(
        responses=[
            call(
                "str_replace",
                {
                    "path": "main.py",
                    "old_str": "answer = 42",
                    "new_str": "answer = 43",
                },
                "replace-1",
            ),
            call("read_file", {"path": "main.py", "start_line": 2}, "verify-1"),
            AIMessage(content="已编辑并核对 main.py。"),
        ]
    )

    result = build_agent_graph(
        model, project_service=service, project_id=record.project_id
    ).invoke({"messages": [HumanMessage(content="把 answer 改成 43")]})

    evidence = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    replaced, verified = (json.loads(message.text) for message in evidence)
    assert replaced["replaced"] is True
    assert verified["lines"] == ["answer = 43"]
    assert (Path(record.root_path) / "main.py").read_text(encoding="utf-8") == (
        "# 示例\nanswer = 43\n"
    )
    assert "str_replace" in model.bound_tool_names
    assert "恰好出现一次" in model.received_histories[0][0].text


def test_project_graph_writes_and_reads_complete_existing_file(project) -> None:
    """主 Agent 可重写已有文件的完整正文，并读回确认。"""
    service, record = project
    model = ToolAwareFakeModel(
        responses=[
            call("read_file", {"path": "main.py"}, "read-before-write"),
            call(
                "write_file",
                {"path": "main.py", "content": "# rewritten\nanswer = 100\n"},
                "write-1",
            ),
            call("read_file", {"path": "main.py"}, "verify-write-1"),
            AIMessage(content="已完整更新并核对 main.py。"),
        ]
    )

    result = build_agent_graph(
        model, project_service=service, project_id=record.project_id
    ).invoke({"messages": [HumanMessage(content="完整重写 main.py")]})

    evidence = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    written = json.loads(evidence[1].text)
    verified = json.loads(evidence[2].text)
    assert written["written"] is True
    assert written["created"] is False
    assert verified["lines"] == ["# rewritten", "answer = 100"]
    assert (Path(record.root_path) / "main.py").read_text(encoding="utf-8") == (
        "# rewritten\nanswer = 100\n"
    )
    assert "write_file" in model.bound_tool_names
    assert "局部修改优先使用 `str_replace`" in model.received_histories[0][0].text


def test_normal_chat_cannot_gain_project_tools_via_prompt(project):
    """伪造 Prompt 项目字段不会授予文件工具；图以真实构造参数覆盖该字段。"""
    _, record = project
    model = ToolAwareFakeModel(responses=[AIMessage(content="普通聊天")])
    build_agent_graph(
        model,
        prompt_context=AgentPromptContext(
            readonly_project_id=record.project_id,
            readonly_file_access_source="explicit",
            readonly_file_target_kind="file",
            readonly_project_root_entries=(("forged.py", "file"),),
            readonly_project_root_truncated=True,
        ),
    ).invoke({"messages": [HumanMessage(content="你好")]})
    assert {
        "list_files",
        "read_file",
        "inspect_project_sandbox",
        "run_project_command",
    }.isdisjoint(model.bound_tool_names)
    assert "<readonly_project>" not in model.received_histories[0][0].text
    assert "<readonly_file_access>" not in model.received_histories[0][0].text
    assert "forged.py" not in model.received_histories[0][0].text


def test_project_root_overview_is_bounded_and_marks_truncation(tmp_path: Path) -> None:
    """大型项目根只注入固定数量的路径，模型必须再调用目录工具。"""
    root = tmp_path / "wide-project"
    root.mkdir()
    for index in range(41):
        (root / f"file-{index:02}.txt").write_text("data\n", encoding="utf-8")
    with open_sqlite_conversation_repository(tmp_path / "wide.sqlite") as repo:
        service = ProjectService(
            repo.projects,
            ProjectRootPolicy(allowed_roots=(root,)),
        )
        project = service.register(name="宽项目", root_path=str(root))
        model = ToolAwareFakeModel(responses=[AIMessage(content="完成。")])

        build_agent_graph(
            model,
            project_service=service,
            project_id=project.project_id,
        ).invoke({"messages": [HumanMessage(content="理解项目")]})

    prompt = model.received_histories[0][0].text
    assert prompt.count("- [file] file-") == 40
    assert "根目录快照已截断" in prompt
    assert str(root) not in prompt


def test_explicit_file_scope_enables_normal_graph_without_project(
    tmp_path: Path,
) -> None:
    """普通主图可读用户明确文件，Prompt 不暴露绝对路径或伪造 Project。"""
    selected = tmp_path / "notes.md"
    selected.write_text("第一行\n第二行\n", encoding="utf-8")
    access = ReadOnlyFileAccess.for_explicit_path(
        ProjectRootPolicy(allowed_roots=(tmp_path,)), str(selected)
    )
    model = ToolAwareFakeModel(
        responses=[
            call("list_files", {}, "explicit-list"),
            call("read_file", {"path": "notes.md"}, "explicit-read"),
            AIMessage(content="notes.md:2 是第二行。"),
        ]
    )

    result = build_agent_graph(model, file_access=access).invoke(
        {"messages": [HumanMessage(content="读取这个文件的第二行")]}
    )

    evidence = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    listing, source = (json.loads(message.text) for message in evidence)
    assert listing["items"][0]["path"] == "notes.md"
    assert source["lines"] == ["第一行", "第二行"]
    assert source["line_numbers"] == [1, 2]
    assert source["access_source"] == "explicit"
    assert "project_id" not in source
    prompt = model.received_histories[0][0].text
    assert "<readonly_file_access>" in prompt
    assert "明确授权的单文件范围" in prompt
    assert "必须使用对应的 line_numbers 值" in prompt
    assert str(selected) not in prompt
    assert {"list_files", "read_file"}.issubset(model.bound_tool_names)


def test_graph_rejects_project_and_explicit_scope_combination(project) -> None:
    """一个 Run 不能同时接受 Project 和另一份明确路径，避免范围身份含糊。"""
    service, record = project
    access = ReadOnlyFileAccess.for_explicit_path(
        ProjectRootPolicy(allowed_roots=(Path(record.root_path),)),
        str(Path(record.root_path) / "main.py"),
    )
    with pytest.raises(ValueError, match="cannot be combined"):
        build_agent_graph(
            ToolAwareFakeModel(responses=[AIMessage(content="不会调用")]),
            project_service=service,
            project_id=record.project_id,
            file_access=access,
        )


def test_web_stream_resolves_project_scope_from_persisted_thread(
    tmp_path: Path,
) -> None:
    """Web 构图只读持久 Thread.project_id，不接收请求或模型提供的项目身份。"""
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.py").write_text("answer = 42\n", encoding="utf-8")
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repo:
        projects = ProjectService(
            repo.projects, ProjectRootPolicy(allowed_roots=(root,))
        )
        project = projects.register(name="样例", root_path=str(root))
        thread_id = "55555555-5555-4555-8555-555555555555"
        repo.create_project_thread(
            thread_id=thread_id, project_id=project.project_id
        )
        model = ToolAwareFakeModel(
            responses=[
                call("read_file", {"path": "main.py"}, "web-read"),
                AIMessage(content="main.py:1 定义了 answer。"),
            ]
        )
        stream = RunStreamService(
            InMemorySaver(),
            graph_factory=lambda saver, file_access: build_agent_graph(
                model,
                checkpointer=saver,
                file_access=file_access,
            ),
            file_access_resolver=ProjectFileAccessResolver(repo, projects),
        )

        async def collect() -> list:
            return [
                event
                async for event in stream.astream_messages(
                    "读取项目 main.py", thread_id
                )
            ]

        asyncio.run(collect())

        prompt = model.received_histories[0][0].text
        assert project.project_id in prompt
        assert str(root) not in prompt
        evidence = next(
            message
            for message in model.received_histories[-1]
            if isinstance(message, ToolMessage)
        )
        payload = json.loads(evidence.text)
        assert payload["project_id"] == project.project_id
        assert payload["lines"] == ["answer = 42"]
        assert payload["line_numbers"] == [1]


def test_web_stream_gives_ordinary_thread_persistent_allowed_roots(
    tmp_path: Path,
) -> None:
    """普通网页 Thread 无需逐 Run 传路径，也始终取得允许根只读工具。"""
    root = tmp_path / "ordinary"
    root.mkdir()
    (root / "README.md").write_text("ordinary evidence\n", encoding="utf-8")
    policy = ProjectRootPolicy(allowed_roots=(root,))
    with open_sqlite_conversation_repository(tmp_path / "app.sqlite") as repo:
        projects = ProjectService(repo.projects, policy)
        model = ToolAwareFakeModel(
            responses=[
                call("list_files", {}, "ordinary-roots"),
                call("list_files", {"path": "workspace-1"}, "ordinary-list"),
                call(
                    "read_file",
                    {"path": "workspace-1/README.md"},
                    "ordinary-read",
                ),
                AIMessage(content="workspace-1/README.md:1 提供了证据。"),
            ]
        )
        stream = RunStreamService(
            InMemorySaver(),
            graph_factory=lambda saver, file_access: build_agent_graph(
                model,
                checkpointer=saver,
                file_access=file_access,
            ),
            file_access_resolver=ProjectFileAccessResolver(
                repo, projects, policy
            ),
        )

        async def collect() -> list:
            return [
                event
                async for event in stream.astream_messages(
                    "读取允许目录里的 README", "ordinary-thread"
                )
            ]

        asyncio.run(collect())

        prompt = model.received_histories[0][0].text
        assert "<readonly_workspace>" in prompt
        assert "<project_root_overview>" not in prompt
        assert str(root) not in prompt
        payload = json.loads(
            next(
                message
                for message in model.received_histories[-1]
                if isinstance(message, ToolMessage)
                and message.tool_call_id == "ordinary-read"
            ).text
        )
        assert payload["lines"] == ["ordinary evidence"]
        assert payload["path"] == "workspace-1/README.md"


def test_project_run_adds_only_explicit_external_path_from_message(
    tmp_path: Path,
) -> None:
    """项目默认保持相对根；本轮明确写出的根外文件才可按原路径读取。"""
    project_root = tmp_path / "project"
    external_root = tmp_path / "external"
    project_root.mkdir()
    external_root.mkdir()
    (project_root / "main.py").write_text("inside\n", encoding="utf-8")
    external = external_root / "shared notes.txt"
    external.write_text("outside\n", encoding="utf-8")
    policy = ProjectRootPolicy(allowed_roots=(project_root,))
    with open_sqlite_conversation_repository(tmp_path / "paths.sqlite") as repo:
        projects = ProjectService(repo.projects, policy)
        project = projects.register(name="样例", root_path=str(project_root))
        thread_id = "66666666-6666-4666-8666-666666666666"
        repo.create_project_thread(thread_id=thread_id, project_id=project.project_id)
        resolver = ProjectFileAccessResolver(repo, projects, policy)

        default_access = resolver(thread_id, "请理解项目")
        assert default_access is not None
        assert default_access.read_file(path="main.py")["lines"] == ["inside"]
        with pytest.raises(ProjectError, match="project_path_invalid"):
            default_access.read_file(path=str(external))

        explicit_access = resolver(thread_id, f"请读取 `{external}` 并和项目比较")
        assert explicit_access is not None
        result = explicit_access.read_file(path=str(external))
        assert result["lines"] == ["outside"]
        assert Path(result["path"]) == external
        listing = explicit_access.list_files(path=str(external))
        assert [Path(item["path"]) for item in listing["items"]] == [external]
        globbed = explicit_access.glob_files(
            path=str(external), pattern="*.txt"
        )
        assert [Path(path) for path in globbed["matches"]] == [external]
        searched = explicit_access.search_files(
            path=str(external), query="outside"
        )
        assert [Path(match["path"]) for match in searched["matches"]] == [
            external
        ]
        replaced = explicit_access.str_replace(
            path=str(external), old_str="outside", new_str="external edit"
        )
        assert Path(replaced["path"]) == external
        assert external.read_text(encoding="utf-8") == "external edit\n"
        assert explicit_access.read_file(path="main.py")["lines"] == ["inside"]

        directory_access = resolver(thread_id, f"请查看目录 `{external_root}`")
        assert directory_access is not None
        assert directory_access.read_file(path=str(external))["lines"] == [
            "external edit"
        ]
        assert [
            Path(item["path"])
            for item in directory_access.list_files(path=str(external_root))["items"]
        ] == [external]
        external_created = external_root / "created outside.txt"
        created = directory_access.create_file(
            path=str(external_created), content="created outside\n"
        )
        assert Path(created["path"]) == external_created
        assert external_created.read_text(encoding="utf-8") == "created outside\n"


def test_web_stream_passes_current_message_to_external_path_resolver(
    tmp_path: Path,
) -> None:
    """Web Run 只按当前消息扩充 Project 范围，并把绝对路径结果交回模型。"""
    project_root = tmp_path / "project"
    external_root = tmp_path / "outside"
    project_root.mkdir()
    external_root.mkdir()
    (project_root / "main.py").write_text("inside\n", encoding="utf-8")
    external = external_root / "reference.txt"
    external.write_text("outside\n", encoding="utf-8")
    policy = ProjectRootPolicy(allowed_roots=(project_root,))
    with open_sqlite_conversation_repository(tmp_path / "stream.sqlite") as repo:
        projects = ProjectService(repo.projects, policy)
        project = projects.register(name="样例", root_path=str(project_root))
        thread_id = "77777777-7777-4777-8777-777777777777"
        repo.create_project_thread(thread_id=thread_id, project_id=project.project_id)
        model = ToolAwareFakeModel(
            responses=[
                call("read_file", {"path": str(external)}, "external-read"),
                AIMessage(content="已读取外部文件。"),
            ]
        )
        stream = RunStreamService(
            InMemorySaver(),
            graph_factory=lambda saver, file_access: build_agent_graph(
                model,
                checkpointer=saver,
                file_access=file_access,
            ),
            file_access_resolver=ProjectFileAccessResolver(repo, projects, policy),
        )

        async def collect() -> list:
            return [
                event
                async for event in stream.astream_messages(
                    f"请读取 `{external}`", thread_id
                )
            ]

        asyncio.run(collect())

    evidence = next(
        message
        for message in model.received_histories[-1]
        if isinstance(message, ToolMessage)
    )
    payload = json.loads(evidence.text)
    assert payload["lines"] == ["outside"]
    assert Path(payload["path"]) == external


def test_project_graph_excludes_mcp_and_normal_chat_only_lists_summary(project):
    """项目图排除 MCP；普通聊天也只列摘要，不默认绑定完整 Schema。"""
    service, record = project
    executed = []

    def external() -> str:
        """记录意外调用，测试中不做外部操作。"""
        executed.append(True)
        return "external"

    mcp = StructuredTool.from_function(external, name="external_mcp")
    model = ToolAwareFakeModel(
        responses=[
            call("external_mcp", {}, "forbidden"),
            AIMessage(content="工具不可用"),
        ]
    )
    result = build_agent_graph(
        model,
        mcp_tools=(mcp,),
        project_service=service,
        project_id=record.project_id,
    ).invoke({"messages": [HumanMessage(content="解释项目")]})
    assert not executed
    assert "external_mcp" not in model.bound_tool_names
    assert any(
        isinstance(m, ToolMessage) and m.tool_call_id == "forbidden"
        for m in result["messages"]
    )
    ordinary = ToolAwareFakeModel(responses=[AIMessage(content="你好")])
    build_agent_graph(ordinary, mcp_tools=(mcp,)).invoke(
        {"messages": [HumanMessage(content="你好")]}
    )
    assert "external_mcp" not in ordinary.bound_tool_names
    assert "external_mcp" in ordinary.received_histories[0][0].text


def test_project_graph_still_enforces_skill_policy(project):
    """技能白名单同时约束模型注册和执行，不能因项目读取工具常驻而绕过。"""
    service, record = project
    catalog = BuiltInSkillCatalog(
        skills=(
            BuiltInSkill(
                name="no-files",
                description="只回答，不读文件。",
                instructions="直接回答。",
                source_file=Path("no-files/SKILL.md"),
                allowed_tools=(),
            ),
        )
    )
    model = ToolAwareFakeModel(
        responses=[
            call("read_file", {"path": "main.py"}, "denied"),
            AIMessage(content="无读取权限"),
        ]
    )
    result = build_agent_graph(
        model,
        skill_catalog=catalog,
        project_service=service,
        project_id=record.project_id,
    ).invoke({"messages": [HumanMessage(content="/no-files 解释项目")]})
    assert "read_file" not in model.bound_tool_names
    evidence = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert json.loads(evidence.text)["reason"] == "skill_tool_not_allowed"
    assert "answer = 42" not in evidence.text


def test_project_graph_fails_before_model_when_binding_invalid(project):
    """缺少成对参数或项目失效时在构图阶段拒绝，不进入模型循环。"""
    service, record = project
    model = ToolAwareFakeModel(responses=[AIMessage(content="不应调用")])
    with pytest.raises(ValueError, match="provided together"):
        build_agent_graph(model, project_id=record.project_id)
    with pytest.raises(ValueError, match="provided together"):
        build_agent_graph(model, project_service=service)
    service.unregister(record.project_id)
    with pytest.raises(ProjectError):
        build_agent_graph(model, project_service=service, project_id=record.project_id)
    assert not model.received_histories


def test_project_file_tool_result_uses_existing_event_projection(project):
    """项目工具结果复用现有消息流投影，后续 Web 可直接展示通用工具卡。"""
    from mini_deer_agent.streaming import astream_agent_messages
    from mini_deer_agent.streaming.projector import aproject_run_events

    service, record = project
    model = ToolAwareFakeModel(
        responses=[
            call("read_file", {"path": "main.py"}, "read-event"),
            AIMessage(content="读取完成"),
        ]
    )
    graph = build_agent_graph(
        model, project_service=service, project_id=record.project_id
    )

    async def collect():
        """沿用正式流投影，但不写入产品 Event Store。"""
        return [
            event
            async for event in aproject_run_events(
                astream_agent_messages(graph, [HumanMessage(content="读 main.py")]),
                run_id="project-test-run",
                thread_id="project-test-thread",
            )
        ]

    events = asyncio.run(collect())
    event = next(event for event in events if event.event == "tool_result")
    assert event.payload["tool_call_id"] == "read-event"
    assert event.payload["name"] == "read_file"
    assert json.loads(event.payload["content"])["lines"] == ["# 示例", "answer = 42"]


def test_project_graph_globs_paths_before_reading_content(project) -> None:
    """主图可调用共用 glob，返回路径事实但不把文件正文混入结果。"""
    service, record = project
    model = ToolAwareFakeModel(
        responses=[
            call("glob_files", {"pattern": "**/*.py"}, "glob-event"),
            AIMessage(content="找到 main.py，尚未读取正文。"),
        ]
    )

    result = build_agent_graph(
        model, project_service=service, project_id=record.project_id
    ).invoke({"messages": [HumanMessage(content="查找 Python 文件")]})

    evidence = next(
        message for message in result["messages"] if isinstance(message, ToolMessage)
    )
    payload = json.loads(evidence.text)
    assert payload["matches"] == ["main.py"]
    assert "answer = 42" not in evidence.text
    assert "glob_files" in model.bound_tool_names
    assert "glob 结果只证明路径存在" in model.received_histories[0][0].text


def test_project_graph_searches_content_with_real_line_evidence(project) -> None:
    """主图正文搜索结果包含真实路径与行号，且工具已进入可信文件 Scope。"""
    service, record = project
    model = ToolAwareFakeModel(
        responses=[
            call("search_files", {"query": "answer", "file_pattern": "*.py"}, "search-event"),
            AIMessage(content="main.py:2 定义了 answer。"),
        ]
    )

    result = build_agent_graph(
        model, project_service=service, project_id=record.project_id
    ).invoke({"messages": [HumanMessage(content="查找 answer 的定义")]})

    evidence = next(
        message for message in result["messages"] if isinstance(message, ToolMessage)
    )
    payload = json.loads(evidence.text)
    assert payload["matches"] == [
        {"path": "main.py", "line_number": 2, "line": "answer = 42"}
    ]
    assert "search_files" in model.bound_tool_names
    assert "query 是单行字面量" in model.received_histories[0][0].text


def test_inspection_script_prints_real_graph_updates(project, monkeypatch, capsys):
    """验证用户终端入口确实经过工具节点，避免示例只打印预设结果。"""
    service, record = project
    model = ToolAwareFakeModel(
        responses=[
            call("read_file", {"path": "main.py"}, "cli-read"),
            AIMessage(content="完成"),
        ]
    )
    script = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "examples"
            / "inspect_project_tools.py"
        )
    )
    ask = script["ask_project"]
    monkeypatch.setitem(
        ask.__globals__,
        "build_agent_graph",
        lambda **kwargs: build_agent_graph(model, **kwargs),
    )
    asyncio.run(ask(service, record.project_id, "读取 main.py"))
    output = capsys.readouterr().out
    assert "[tools/tool]" in output
    assert "cli-read" in output and "answer = 42" in output
    assert "完成" in output


def test_project_graph_creates_directory_and_file(project):
    service, record = project
    model = ToolAwareFakeModel(responses=[
        call("create_directory", {"path": "generated"}, "mkdir"),
        call("create_file", {"path": "generated/hello.txt", "content": "hello"}, "create"),
        call("read_file", {"path": "generated/hello.txt"}, "read"),
        AIMessage(content="已创建并读回。"),
    ])
    result = asyncio.run(build_agent_graph(
        model, project_service=service, project_id=record.project_id
    ).ainvoke({"messages": [HumanMessage(content="创建目录和 hello.txt")]}))
    evidence = [json.loads(m.text) for m in result["messages"] if isinstance(m, ToolMessage)]
    assert evidence[0]["created"] is True
    assert evidence[2]["lines"] == ["hello"]
    assert (Path(record.root_path) / "generated/hello.txt").read_text() == "hello"


def test_project_graph_renames_and_reads_file(project):
    service, record = project
    model = ToolAwareFakeModel(responses=[
        call("rename_file", {"path": "main.py", "new_name": "app.py"}, "rename"),
        call("read_file", {"path": "app.py"}, "read"),
        AIMessage(content="已改名并核对内容。"),
    ])
    result = asyncio.run(build_agent_graph(
        model, project_service=service, project_id=record.project_id
    ).ainvoke({"messages": [HumanMessage(content="把 main.py 改名为 app.py")]}))
    evidence = [json.loads(m.text) for m in result["messages"] if isinstance(m, ToolMessage)]
    assert evidence[0]["renamed"] is True
    assert evidence[1]["lines"] == ["# 示例", "answer = 42"]
    assert not (Path(record.root_path) / "main.py").exists()


def test_project_graph_moves_and_reads_file(project):
    service, record = project
    target_dir = Path(record.root_path) / "src"
    target_dir.mkdir()
    model = ToolAwareFakeModel(responses=[
        call(
            "move_file",
            {"path": "main.py", "new_path": "src/main.py"},
            "move",
        ),
        call("read_file", {"path": "src/main.py"}, "read"),
        AIMessage(content="已移动并核对内容。"),
    ])
    result = asyncio.run(build_agent_graph(
        model, project_service=service, project_id=record.project_id
    ).ainvoke({"messages": [HumanMessage(content="把 main.py 移动到 src")]}))
    evidence = [
        json.loads(message.text)
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    ]
    assert evidence[0]["moved"] is True
    assert evidence[0]["previous_path"] == "main.py"
    assert evidence[0]["path"] == "src/main.py"
    assert evidence[1]["lines"] == ["# 示例", "answer = 42"]
    assert not (Path(record.root_path) / "main.py").exists()


def test_project_graph_deletes_file_and_lists_directory(project):
    service, record = project
    target = Path(record.root_path) / "delete-me.txt"
    target.write_text("temporary", encoding="utf-8")
    model = ToolAwareFakeModel(responses=[
        call("delete_file", {"path": "delete-me.txt"}, "delete"),
        call("list_files", {}, "list"),
        AIMessage(content="已删除并确认文件不存在。"),
    ])
    result = asyncio.run(build_agent_graph(
        model, project_service=service, project_id=record.project_id
    ).ainvoke({"messages": [HumanMessage(content="删除 delete-me.txt")] }))
    evidence = [
        json.loads(message.text)
        for message in result["messages"]
        if isinstance(message, ToolMessage)
    ]
    assert evidence[0]["deleted"] is True
    assert all(item["path"] != "delete-me.txt" for item in evidence[1]["items"])
    assert not target.exists()
