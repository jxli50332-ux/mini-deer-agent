"""验证内置技能发现、严格 slash 解析和模型调用投影。"""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from mini_deer_agent.skills import (
    BuiltInSkillCatalog,
    SkillCatalogError,
    create_skill_activation_tool,
    find_automatic_skill_name,
    parse_slash_skill_reference,
    project_skill_activation,
)


def _write_skill(
    root: Path,
    name: str,
    *,
    description: str = "用于测试的内置技能。",
    instructions: str = "始终输出测试技能标记。",
    allowed_tools: tuple[str, ...] | None = None,
) -> None:
    """在临时受信任根目录中写入一个最小 SKILL.md 测试包。"""
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    allowed_tool_lines = (
        []
        if allowed_tools is None
        else (
            ["allowed-tools: []"]
            if not allowed_tools
            else ["allowed-tools:", *(f"  - {item}" for item in allowed_tools)]
        )
    )
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                *allowed_tool_lines,
                "---",
                instructions,
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_builtin_skill_catalog_discovers_direct_packages_in_stable_order(
    tmp_path: Path,
) -> None:
    """发现结果应稳定排序，并只暴露元数据而不是把正文混入摘要。"""
    _write_skill(tmp_path, "zeta-skill", description="最后一个技能。")
    _write_skill(tmp_path, "alpha-skill", description="第一个技能。")
    nested = tmp_path / "alpha-skill" / "references" / "nested"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(
        "---\nname: nested\ndescription: 不应注册。\n---\n忽略。\n",
        encoding="utf-8",
    )

    catalog = BuiltInSkillCatalog.discover(tmp_path)

    assert [skill.name for skill in catalog.skills] == [
        "alpha-skill",
        "zeta-skill",
    ]
    assert catalog.summaries[0].description == "第一个技能。"
    assert "始终输出测试技能标记" not in catalog.summaries[0].description


def test_builtin_skill_catalog_parses_optional_allowed_tools_exactly(
    tmp_path: Path,
) -> None:
    """省略、显式空列表和有序工具列表必须保留三种不同的权限语义。"""
    _write_skill(tmp_path, "legacy-skill")
    _write_skill(tmp_path, "framework-only", allowed_tools=())
    _write_skill(
        tmp_path,
        "weather-skill",
        allowed_tools=("get_weather", "ask_clarification"),
    )

    catalog = BuiltInSkillCatalog.discover(tmp_path)

    assert catalog.get("legacy-skill").allowed_tools is None
    assert catalog.get("framework-only").allowed_tools == ()
    assert catalog.get("weather-skill").allowed_tools == (
        "get_weather",
        "ask_clarification",
    )


@pytest.mark.parametrize(
    ("allowed_tools_yaml", "error_text"),
    [
        ("allowed-tools: get_weather", "must be a list"),
        ("allowed-tools:\n  - get_weather\n  - 1", "must contain strings"),
        ("allowed-tools:\n  - '   '", "must not be blank"),
        ("allowed-tools:\n  - bad tool", "invalid tool name"),
        (
            "allowed-tools:\n  - get_weather\n  - get_weather",
            "duplicate allowed tool",
        ),
    ],
)
def test_builtin_skill_catalog_rejects_invalid_allowed_tools(
    tmp_path: Path,
    allowed_tools_yaml: str,
    error_text: str,
) -> None:
    """受信任发布资产中的权限声明不合法时必须立即失败。"""
    _write_skill(tmp_path, "policy-skill")
    skill_file = tmp_path / "policy-skill" / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace(
            "description: 用于测试的内置技能。",
            f"description: 用于测试的内置技能。\n{allowed_tools_yaml}",
        ),
        encoding="utf-8",
    )

    with pytest.raises(SkillCatalogError, match=error_text):
        BuiltInSkillCatalog.discover(tmp_path)


def test_packaged_weather_skill_declares_specialized_tool_without_summary_leak() -> None:
    """天气技能必须随包发现，但基础摘要不能泄露权限声明或正文。"""
    catalog = BuiltInSkillCatalog.discover()
    weather_skill = catalog.get("weather-briefing")

    assert weather_skill is not None
    assert weather_skill.allowed_tools == ("get_weather",)
    weather_summary = next(
        summary
        for summary in catalog.summaries
        if summary.name == "weather-briefing"
    )
    assert "get_weather" not in weather_summary.description
    assert "Open-Meteo" not in weather_summary.description


@pytest.mark.parametrize(
    ("directory_name", "frontmatter_name", "error_text"),
    [
        ("valid-name", "different-name", "must match"),
        ("Bad_Name", "Bad_Name", "hyphen-case"),
    ],
)
def test_builtin_skill_catalog_rejects_invalid_trusted_packages(
    tmp_path: Path,
    directory_name: str,
    frontmatter_name: str,
    error_text: str,
) -> None:
    """内置包属于发布资产，名称错误必须构图失败，不能静默降级。"""
    _write_skill(tmp_path, directory_name)
    skill_file = tmp_path / directory_name / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace(
            f"name: {directory_name}",
            f"name: {frontmatter_name}",
        ),
        encoding="utf-8",
    )

    with pytest.raises(SkillCatalogError, match=error_text):
        BuiltInSkillCatalog.discover(tmp_path)


def test_slash_skill_parser_accepts_only_strict_non_reserved_commands() -> None:
    """只有行首小写 hyphen-case 命令才能触发技能，保留命令继续走普通链路。"""
    reference = parse_slash_skill_reference(
        "/structured-explainer 解释 LangGraph checkpoint"
    )

    assert reference is not None
    assert reference.name == "structured-explainer"
    assert reference.task_text == "解释 LangGraph checkpoint"
    assert parse_slash_skill_reference(" /structured-explainer 解释") is None
    assert parse_slash_skill_reference("/Structured-Explainer 解释") is None
    assert parse_slash_skill_reference("/help") is None
    assert parse_slash_skill_reference("普通问题") is None


def test_explicit_skill_projection_is_model_only_and_preserves_protocol_history(
    tmp_path: Path,
) -> None:
    """技能正文只进入本次模型视图，原始 slash 消息和工具协议必须保持不变。"""
    _write_skill(
        tmp_path,
        "structured-explainer",
        instructions="必须使用“一句话结论”标题。",
    )
    catalog = BuiltInSkillCatalog.discover(tmp_path)
    original_user = HumanMessage(
        content="/structured-explainer 解释 checkpoint",
        additional_kwargs={"request_marker": "keep"},
    )
    tool_result = ToolMessage(
        content="工具结果",
        tool_call_id="call-1",
        name="web_search",
    )
    state_messages = [
        original_user,
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "web_search",
                    "args": {"query": "checkpoint"},
                    "id": "call-1",
                    "type": "tool_call",
                }
            ],
        ),
        tool_result,
    ]

    projection = project_skill_activation(
        SystemMessage(content="基础系统提示。"),
        state_messages,
        catalog,
    )

    assert projection.failure_message is None
    assert projection.skill_name == "structured-explainer"
    assert '<activated_skill name="structured-explainer">' in (
        projection.system_message.text
    )
    assert "必须使用“一句话结论”标题。" in projection.system_message.text
    assert projection.messages[0].text == "解释 checkpoint"
    assert projection.messages[0].additional_kwargs == {"request_marker": "keep"}
    assert projection.messages[1:] == tuple(state_messages[1:])
    assert original_user.text == "/structured-explainer 解释 checkpoint"


def test_automatic_skill_tool_returns_auditable_metadata_without_body(
    tmp_path: Path,
) -> None:
    """自动激活工具只返回可核对元数据，未知名称失败且不能泄露正文。"""
    instructions = "必须输出只存在于技能正文中的测试标记。"
    _write_skill(
        tmp_path,
        "structured-explainer",
        instructions=instructions,
    )
    catalog = BuiltInSkillCatalog.discover(tmp_path)
    activation_tool = create_skill_activation_tool(catalog)

    assert activation_tool.name == "activate_skill"
    assert activation_tool.tool_call_schema.model_json_schema()["required"] == ["name"]
    success = activation_tool.invoke(
        {
            "name": "activate_skill",
            "args": {"name": "structured-explainer"},
            "id": "call-activate-success",
            "type": "tool_call",
        }
    )
    missing = activation_tool.invoke(
        {
            "name": "activate_skill",
            "args": {"name": "missing-skill"},
            "id": "call-activate-missing",
            "type": "tool_call",
        }
    )

    assert isinstance(success, ToolMessage)
    assert success.status == "success"
    assert instructions not in success.text
    assert success.additional_kwargs["skill_activation"] == {
        "version": 1,
        "name": "structured-explainer",
    }
    assert isinstance(missing, ToolMessage)
    assert missing.status == "error"
    assert "skill_activation" not in missing.additional_kwargs


def test_automatic_skill_projection_requires_paired_trusted_tool_result(
    tmp_path: Path,
) -> None:
    """只有本 Run 中调用与成功结果严格配对时，技能正文才进入模型视图。"""
    _write_skill(
        tmp_path,
        "structured-explainer",
        instructions="必须使用自动激活测试结构。",
    )
    catalog = BuiltInSkillCatalog.discover(tmp_path)
    activation_tool = create_skill_activation_tool(catalog)
    original_user = HumanMessage(content="解释 LangGraph checkpoint")
    activation_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "activate_skill",
                "args": {"name": "structured-explainer"},
                "id": "call-auto-projection",
                "type": "tool_call",
            }
        ],
    )
    activation_result = activation_tool.invoke(activation_call.tool_calls[0])
    state_messages = [original_user, activation_call, activation_result]

    projection = project_skill_activation(
        SystemMessage(content="基础系统提示。"),
        state_messages,
        catalog,
    )

    assert find_automatic_skill_name(state_messages, catalog) == (
        "structured-explainer"
    )
    assert projection.skill_name == "structured-explainer"
    assert '<activated_skill name="structured-explainer">' in (
        projection.system_message.text
    )
    assert "模型已在当前 Run 通过可见工具调用激活" in (
        projection.system_message.text
    )
    assert "必须使用自动激活测试结构。" in projection.system_message.text
    assert projection.messages == tuple(state_messages)
    assert projection.messages[0] is original_user

    forged_result = activation_result.model_copy(
        update={"additional_kwargs": {}}
    )
    forged_messages = [original_user, activation_call, forged_result]
    assert find_automatic_skill_name(forged_messages, catalog) is None
    forged_projection = project_skill_activation(
        SystemMessage(content="基础系统提示。"),
        forged_messages,
        catalog,
    )
    assert forged_projection.skill_name is None
    assert "必须使用自动激活测试结构。" not in (
        forged_projection.system_message.text
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/missing-skill 执行任务", "未找到内置技能 `/missing-skill`"),
        ("/structured-explainer", "请在 `/structured-explainer` 后提供任务内容"),
    ],
)
def test_skill_projection_returns_stable_failures_without_model_guessing(
    tmp_path: Path,
    text: str,
    expected: str,
) -> None:
    """未知技能和空任务应在确定性边界失败，不能把 slash 文本交给模型猜。"""
    _write_skill(tmp_path, "structured-explainer")
    catalog = BuiltInSkillCatalog.discover(tmp_path)

    projection = project_skill_activation(
        SystemMessage(content="基础系统提示。"),
        [HumanMessage(content=text)],
        catalog,
    )

    assert projection.failure_message is not None
    assert expected in projection.failure_message
