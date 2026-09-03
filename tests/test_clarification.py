"""验证 ask_clarification 的模型契约和稳定结果结构。"""

import json

import pytest
from langchain_core.messages import ToolMessage

from mini_deer_agent.tools import ask_clarification


def test_ask_clarification_exposes_bounded_model_contract() -> None:
    """模型只能提供问题业务字段，tool_call_id 必须由运行时注入。"""
    schema = ask_clarification.tool_call_schema.model_json_schema()

    assert ask_clarification.name == "ask_clarification"
    assert "结束当前 Run" in ask_clarification.description
    assert schema["required"] == ["question", "clarification_type"]
    assert set(schema["properties"]) == {
        "question",
        "clarification_type",
        "context",
        "options",
        "fields",
    }


def test_ask_clarification_returns_stable_human_input_request() -> None:
    """工具结果应携带稳定 request_id，并能先由通用工具卡直接展示。"""
    result = ask_clarification.invoke(
        {
            "name": "ask_clarification",
            "args": {
                "question": "报告主要给谁阅读？",
                "clarification_type": "missing_info",
                "context": "受众会影响内容深度和表达方式。",
                "options": ["管理层", "技术团队"],
            },
            "id": "call-clarification-1",
            "type": "tool_call",
        }
    )

    assert isinstance(result, ToolMessage)
    assert result.id == "clarification:call-clarification-1"
    assert result.tool_call_id == "call-clarification-1"
    assert result.name == "ask_clarification"
    assert json.loads(result.text) == {
        "version": 1,
        "kind": "human_input_request",
        "source": "ask_clarification",
        "request_id": "clarification:call-clarification-1",
        "clarification_type": "missing_info",
        "question": "报告主要给谁阅读？",
        "input_mode": "choice_with_other",
        "context": "受众会影响内容深度和表达方式。",
        "options": [
            {"id": "option-1", "label": "管理层", "value": "管理层"},
            {"id": "option-2", "label": "技术团队", "value": "技术团队"},
        ],
    }


def test_ask_clarification_rejects_empty_question() -> None:
    """空问题无法形成用户可回答的请求，必须在工具边界失败关闭。"""
    with pytest.raises(Exception):
        ask_clarification.invoke(
            {
                "name": "ask_clarification",
                "args": {
                    "question": "   ",
                    "clarification_type": "missing_info",
                },
                "id": "call-empty-question",
                "type": "tool_call",
            }
        )


def test_ask_clarification_rejects_duplicate_options() -> None:
    """重复 value 无法稳定关联结构化选项，必须在写入历史前拒绝。"""
    with pytest.raises(Exception):
        ask_clarification.invoke(
            {
                "name": "ask_clarification",
                "args": {
                    "question": "请选择报告受众。",
                    "clarification_type": "approach_choice",
                    "options": ["管理层", "管理层"],
                },
                "id": "call-duplicate-options",
                "type": "tool_call",
            }
        )


def test_ask_clarification_returns_v2_form_request() -> None:
    """多个相关值应由一个 v2 form 收集，fields 优先于旧 options。"""
    result = ask_clarification.invoke(
        {
            "name": "ask_clarification",
            "args": {
                "question": "请补充发布说明参数。",
                "clarification_type": "missing_info",
                "options": ["这个旧选项不应进入 form", "另一个旧选项"],
                "fields": [
                    {
                        "name": "project_name",
                        "label": "项目名",
                        "type": "text",
                        "required": True,
                        "placeholder": "例如 Mini Deer",
                    },
                    {
                        "name": "format",
                        "label": "输出格式",
                        "type": "select",
                        "required": True,
                        "options": ["Markdown", "纯文本"],
                    },
                    {
                        "name": "notes",
                        "label": "补充说明",
                        "type": "textarea",
                    },
                ],
            },
            "id": "call-form-1",
            "type": "tool_call",
        }
    )

    assert isinstance(result, ToolMessage)
    assert json.loads(result.text) == {
        "version": 2,
        "kind": "human_input_request",
        "source": "ask_clarification",
        "request_id": "clarification:call-form-1",
        "clarification_type": "missing_info",
        "question": "请补充发布说明参数。",
        "input_mode": "form",
        "fields": [
            {
                "name": "project_name",
                "label": "项目名",
                "type": "text",
                "required": True,
                "placeholder": "例如 Mini Deer",
            },
            {
                "name": "format",
                "label": "输出格式",
                "type": "select",
                "required": True,
                "options": [
                    {
                        "id": "format-option-1",
                        "label": "Markdown",
                        "value": "Markdown",
                    },
                    {
                        "id": "format-option-2",
                        "label": "纯文本",
                        "value": "纯文本",
                    },
                ],
            },
            {
                "name": "notes",
                "label": "补充说明",
                "type": "textarea",
                "required": False,
            },
        ],
    }


def test_ask_clarification_returns_all_extended_form_field_types() -> None:
    """扩展字段应保留类型，并只为 multi_select 生成稳定选项。"""
    result = ask_clarification.invoke(
        {
            "name": "ask_clarification",
            "args": {
                "question": "请补充活动参数。",
                "clarification_type": "missing_info",
                "fields": [
                    {
                        "name": "budget",
                        "label": "预算",
                        "type": "number",
                        "required": True,
                    },
                    {
                        "name": "due_date",
                        "label": "截止日期",
                        "type": "date",
                        "required": True,
                    },
                    {
                        "name": "channels",
                        "label": "发布渠道",
                        "type": "multi_select",
                        "required": True,
                        "options": ["网站", "邮件"],
                    },
                    {
                        "name": "urgent",
                        "label": "是否加急",
                        "type": "checkbox",
                    },
                ],
            },
            "id": "call-extended-form",
            "type": "tool_call",
        }
    )

    assert json.loads(result.text)["fields"] == [
        {
            "name": "budget",
            "label": "预算",
            "type": "number",
            "required": True,
        },
        {
            "name": "due_date",
            "label": "截止日期",
            "type": "date",
            "required": True,
        },
        {
            "name": "channels",
            "label": "发布渠道",
            "type": "multi_select",
            "required": True,
            "options": [
                {
                    "id": "channels-option-1",
                    "label": "网站",
                    "value": "网站",
                },
                {
                    "id": "channels-option-2",
                    "label": "邮件",
                    "value": "邮件",
                },
            ],
        },
        {
            "name": "urgent",
            "label": "是否加急",
            "type": "checkbox",
            "required": False,
        },
    ]


@pytest.mark.parametrize(
    "fields",
    [
        [
            {"name": "duplicate", "type": "text"},
            {"name": "duplicate", "type": "textarea"},
        ],
        [{"name": "constructor", "type": "text"}],
        [{"name": "format", "type": "select", "options": []}],
        [{"name": "channels", "type": "multi_select", "options": []}],
        [{"name": "urgent", "type": "checkbox", "options": ["是", "否"]}],
        [
            {
                "name": "format",
                "type": "select",
                "options": ["Markdown", "Markdown"],
            }
        ],
    ],
)
def test_ask_clarification_rejects_unsafe_form_fields(
    fields: list[dict[str, object]],
) -> None:
    """字段名冲突或 select 选项不完整时，不能发布看似可用但缺字段的表单。"""
    with pytest.raises(Exception):
        ask_clarification.invoke(
            {
                "name": "ask_clarification",
                "args": {
                    "question": "请补充参数。",
                    "clarification_type": "missing_info",
                    "fields": fields,
                },
                "id": "call-invalid-form",
                "type": "tool_call",
            }
        )
