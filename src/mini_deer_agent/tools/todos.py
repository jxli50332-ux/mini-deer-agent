"""提供 write_todos 规划工具，让 Agent 对复杂任列计划并跟踪进度。"""

import json
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

# 单次任务清单的上限，避免模型生成无界的长清单占用上下文。
_MAX_TODOS = 20


class TodoItem(BaseModel):
    """单个待办项：content 描述任务，status 表示当前状态。"""

    content: str = Field(min_length=1, max_length=200, description="任务描述")
    status: Literal["pending", "in_progress", "completed"] = Field(
        description="任务状态：pending 未开始 / in_progress 进行中 / completed 已完成"
    )


class WriteTodosInput(BaseModel):
    """write_todos 的完整参数：一份完整的任务清单快照。"""

    todos: list[TodoItem] = Field(
        min_length=1, max_length=_MAX_TODOS, description="完整的任务清单"
    )


def _render_todos(todos: list[TodoItem]) -> str:
    """把任务清单渲染为稳定的 JSON，供模型读取和前端展示。"""
    payload = {
        "todos": [
            {"content": todo.content, "status": todo.status} for todo in todos
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _write_todos(todos: list[TodoItem]) -> str:
    """创建或更新当前任务清单，用于跟踪 3 步以上的复杂任务。"""
    # args_schema 已在工具边界校验 content/status，这里只做稳定渲染。
    return _render_todos(todos)


write_todos = StructuredTool.from_function(
    func=_write_todos,
    name="write_todos",
    description=(
        "创建或更新任务清单，用于跟踪需要 3 步以上的复杂任务。"
        "每次调用传入完整的清单快照，status 只能是 pending、in_progress、completed。"
    ),
    args_schema=WriteTodosInput,
)
