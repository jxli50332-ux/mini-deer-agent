"""提供 ask_clarification 工具，让 Agent 在关键条件缺失时请求用户输入。"""

import json
from typing import Annotated, Literal, Required, TypedDict

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from pydantic import AfterValidator, Field, StringConstraints


type ClarificationType = Literal[
    "missing_info",
    "ambiguous_requirement",
    "approach_choice",
    "risk_confirmation",
    "suggestion",
]

type ClarificationQuestion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
type ClarificationContext = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
type ClarificationOption = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
type ClarificationFieldName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    ),
]
type ClarificationFormFieldType = Literal[
    "text",
    "textarea",
    "number",
    "select",
    "multi_select",
    "checkbox",
    "date",
]


class ClarificationFormField(TypedDict, total=False):
    """模型可声明的最小表单字段集合。"""

    name: Required[ClarificationFieldName]
    label: ClarificationOption
    type: ClarificationFormFieldType
    required: bool
    options: list[ClarificationOption]
    placeholder: ClarificationOption


def _require_unique_options(options: list[str]) -> list[str]:
    """拒绝重复选项，避免未来结构化控件产生无法区分的 value。"""
    if len(set(options)) != len(options):
        raise ValueError("clarification options must be unique")
    return options


type ClarificationOptions = Annotated[
    list[ClarificationOption],
    Field(min_length=2, max_length=8),
    AfterValidator(_require_unique_options),
]

_RESERVED_FIELD_NAMES = {
    "__proto__",
    "constructor",
    "prototype",
    "toString",
    "toLocaleString",
    "valueOf",
    "hasOwnProperty",
    "isPrototypeOf",
    "propertyIsEnumerable",
    "__defineGetter__",
    "__defineSetter__",
    "__lookupGetter__",
    "__lookupSetter__",
}
_OPTION_FIELD_TYPES = {"select", "multi_select"}


def _normalize_form_fields(
    fields: list[ClarificationFormField],
) -> list[ClarificationFormField]:
    """规范表单字段，并拒绝会让前端映射产生歧义的声明。"""
    normalized: list[ClarificationFormField] = []
    names: set[str] = set()
    for field in fields:
        name = field["name"]
        if name in names or name in _RESERVED_FIELD_NAMES:
            raise ValueError("clarification field names must be unique and safe")
        names.add(name)

        field_type = field.get("type", "text")
        raw_options = field.get("options")
        item: ClarificationFormField = {
            "name": name,
            "label": field.get("label", name),
            "type": field_type,
            "required": field.get("required", False),
        }
        placeholder = field.get("placeholder")
        if placeholder is not None:
            item["placeholder"] = placeholder

        if field_type in _OPTION_FIELD_TYPES:
            if raw_options is None or not 2 <= len(raw_options) <= 8:
                raise ValueError("option fields require 2 to 8 options")
            if len(set(raw_options)) != len(raw_options):
                raise ValueError("option field options must be unique")
            item["options"] = raw_options
        elif raw_options is not None:
            raise ValueError("only select and multi_select fields may declare options")
        normalized.append(item)
    return normalized


type ClarificationFormFields = Annotated[
    list[ClarificationFormField],
    Field(min_length=1, max_length=8),
    AfterValidator(_normalize_form_fields),
]


def _render_human_input_request(
    *,
    question: str,
    clarification_type: ClarificationType,
    tool_call_id: str,
    context: str | None,
    options: list[str] | None,
    fields: list[ClarificationFormField] | None,
) -> str:
    """渲染稳定的人类输入请求 JSON。"""
    request_id = f"clarification:{tool_call_id}"
    payload: dict[str, object] = {
        "version": 2 if fields else 1,
        "kind": "human_input_request",
        "source": "ask_clarification",
        "request_id": request_id,
        "clarification_type": clarification_type,
        "question": question,
        "input_mode": (
            "form" if fields else "choice_with_other" if options else "free_text"
        ),
    }
    if context is not None:
        payload["context"] = context
    if fields:
        rendered_fields: list[dict[str, object]] = []
        for field in fields:
            rendered: dict[str, object] = {
                "name": field["name"],
                "label": field["label"],
                "type": field["type"],
                "required": field["required"],
            }
            if "placeholder" in field:
                rendered["placeholder"] = field["placeholder"]
            if field["type"] in _OPTION_FIELD_TYPES:
                rendered["options"] = [
                    {
                        "id": f"{field['name']}-option-{index}",
                        "label": option,
                        "value": option,
                    }
                    for index, option in enumerate(field["options"], 1)
                ]
            rendered_fields.append(rendered)
        payload["fields"] = rendered_fields
    elif options:
        payload["options"] = [
            {"id": f"option-{index}", "label": option, "value": option}
            for index, option in enumerate(options, 1)
        ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("ask_clarification", return_direct=True)
def ask_clarification(
    question: ClarificationQuestion,
    clarification_type: ClarificationType,
    tool_call_id: Annotated[str, InjectedToolCallId],
    context: ClarificationContext | None = None,
    options: ClarificationOptions | None = None,
    fields: ClarificationFormFields | None = None,
) -> ToolMessage:
    """向用户提出一个澄清问题，并结束当前 Run 等待用户在下一 Run 回答。

    仅在缺少会影响正确执行的关键信息、存在高影响歧义、需要用户选择方案，
    或风险操作需要明确确认时使用。简单明确的问题不要调用此工具。

    需要一次收集多个相关值时传 fields；支持 text、textarea、number、select、
    multi_select、checkbox、date。checkbox 默认表示“否”，仅在必须同意时设为
    required；select 和 multi_select 必须提供 options。每个字段使用稳定且唯一的
    英文 name。传入 fields 时优先生成一张表单，并忽略顶层 options；单个问题仍使用
    options 或自由文本。
    """
    request_id = f"clarification:{tool_call_id}"
    return ToolMessage(
        id=request_id,
        content=_render_human_input_request(
            question=question,
            clarification_type=clarification_type,
            tool_call_id=tool_call_id,
            context=context,
            options=options,
            fields=fields,
        ),
        tool_call_id=tool_call_id,
        name="ask_clarification",
    )
