"""验证 write_todos 规划工具的契约和稳定渲染。"""

import json

import pytest

from mini_deer_agent.tools import write_todos


def test_write_todos_exposes_model_visible_contract() -> None:
    """工具名、描述和参数 schema 必须让模型能正确调用。"""
    schema = write_todos.args_schema.model_json_schema()

    assert write_todos.name == "write_todos"
    assert "3 步以上" in write_todos.description
    assert schema["required"] == ["todos"]
    assert schema["properties"]["todos"]["type"] == "array"


def test_write_todos_renders_stable_json() -> None:
    """任务清单渲染为稳定的 JSON，供模型读取和前端展示。"""
    result = write_todos.invoke(
        {
            "todos": [
                {"content": "分析需求", "status": "completed"},
                {"content": "实现功能", "status": "in_progress"},
                {"content": "验证结果", "status": "pending"},
            ]
        }
    )

    assert json.loads(result) == {
        "todos": [
            {"content": "分析需求", "status": "completed"},
            {"content": "实现功能", "status": "in_progress"},
            {"content": "验证结果", "status": "pending"},
        ]
    }


def test_write_todos_rejects_invalid_status() -> None:
    """status 只能是 pending/in_progress/completed，非法值失败关闭。"""
    with pytest.raises(Exception):
        write_todos.invoke({"todos": [{"content": "任务", "status": "done"}]})
