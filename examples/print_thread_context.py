"""只读打印线程摘要、Durable Context 与 LangGraph 原始消息窗口。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from mini_deer_agent.core import Settings


@dataclass(frozen=True, slots=True)
class ThreadRecord:
    """保存从产品历史库定位到的线程元数据。"""

    thread_id: str
    title: str | None
    status: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CheckpointContext:
    """保存最新 checkpoint 中影响后续模型调用的压缩状态。"""

    checkpoint_id: str
    summary_text: str
    messages: tuple[Any, ...]
    delegations: tuple[Any, ...]
    skill_context: tuple[Any, ...]
    todos: Any | None


def _open_readonly(database_path: Path) -> sqlite3.Connection:
    """以 SQLite 只读 URI 打开现有数据库，避免检查操作产生任何写入。"""
    resolved_path = database_path.resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"数据库不存在: {resolved_path}")
    connection = sqlite3.connect(
        f"{resolved_path.as_uri()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    return connection


def _find_thread(
    connection: sqlite3.Connection,
    *,
    title: str | None,
    thread_id: str | None,
) -> ThreadRecord:
    """按精确标题或 ID 定位线程，并拒绝不确定的同名匹配。"""
    if thread_id is not None:
        rows = connection.execute(
            """
            SELECT thread_id, title, status, updated_at
            FROM threads
            WHERE thread_id = ?
            """,
            (thread_id,),
        ).fetchall()
    else:
        if title is None or not title.strip():
            raise ValueError("必须提供线程标题或 --thread-id")
        rows = connection.execute(
            """
            SELECT thread_id, title, status, updated_at
            FROM threads
            WHERE title = ?
            ORDER BY updated_at DESC, thread_id DESC
            """,
            (title.strip(),),
        ).fetchall()
    if not rows:
        target = thread_id if thread_id is not None else title
        raise LookupError(f"未找到线程: {target}")
    if len(rows) > 1:
        choices = ", ".join(str(row["thread_id"]) for row in rows)
        raise LookupError(f"存在多个同名线程，请改用 --thread-id: {choices}")
    row = rows[0]
    return ThreadRecord(
        thread_id=str(row["thread_id"]),
        title=str(row["title"]) if row["title"] is not None else None,
        status=str(row["status"]),
        updated_at=str(row["updated_at"]),
    )


def _visible_message_count(
    connection: sqlite3.Connection,
    thread_id: str,
) -> int:
    """统计页面历史中的可见消息，说明它与 checkpoint 压缩彼此独立。"""
    row = connection.execute(
        """
        SELECT COUNT(*) AS message_count
        FROM timeline_items AS timeline
        JOIN messages AS message ON message.item_id = timeline.item_id
        WHERE timeline.thread_id = ? AND message.hidden_from_ui = 0
        """,
        (thread_id,),
    ).fetchone()
    return int(row["message_count"])


def _load_latest_checkpoint(
    connection: sqlite3.Connection,
    thread_id: str,
) -> CheckpointContext:
    """解码主命名空间的最新 checkpoint，不构建 Agent 图或触发模型。"""
    row = connection.execute(
        """
        SELECT checkpoint_id, type, checkpoint
        FROM checkpoints
        WHERE thread_id = ? AND checkpoint_ns = ''
        ORDER BY checkpoint_id DESC
        LIMIT 1
        """,
        (thread_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"线程没有 checkpoint: {thread_id}")
    checkpoint = JsonPlusSerializer().loads_typed(
        (str(row["type"]), bytes(row["checkpoint"]))
    )
    channel_values = checkpoint.get("channel_values", {})
    summary_text = channel_values.get("summary_text") or ""
    messages = channel_values.get("messages") or []
    delegations = channel_values.get("delegations") or []
    skill_context = channel_values.get("skill_context") or []
    return CheckpointContext(
        checkpoint_id=str(row["checkpoint_id"]),
        summary_text=str(summary_text),
        messages=tuple(messages),
        delegations=tuple(delegations),
        skill_context=tuple(skill_context),
        todos=channel_values.get("todos"),
    )


def _message_content(message: Any) -> str:
    """把字符串或内容块统一渲染为可复制的 UTF-8 文本。"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=2, default=str)


def _preview(text: str, max_chars: int) -> str:
    """生成保留头尾的单条消息预览，完整模式不会调用此函数。"""
    normalized = text.replace("\r", " ").replace("\n", " ")
    if len(normalized) <= max_chars:
        return normalized
    marker = " ...[省略]... "
    remaining = max_chars - len(marker)
    if remaining <= 0:
        return normalized[:max_chars]
    head = remaining * 2 // 3
    return f"{normalized[:head]}{marker}{normalized[-(remaining - head):]}"


def _message_label(message: Any) -> str:
    """生成消息角色与工具名标签。"""
    role = str(getattr(message, "type", type(message).__name__))
    name = getattr(message, "name", None)
    return f"{role}:{name}" if name else role


def _print_context(
    thread: ThreadRecord,
    visible_message_count: int,
    checkpoint: CheckpointContext,
    *,
    full: bool,
    summary_only: bool,
    preview_chars: int,
) -> None:
    """打印产品历史计数、压缩摘要、分界以及保留原始消息。"""
    print("===== 线程 =====")
    print(f"标题: {thread.title or '[无标题]'}")
    print(f"thread_id: {thread.thread_id}")
    print(f"状态: {thread.status}")
    print(f"更新时间: {thread.updated_at}")
    print(f"产品可见消息数: {visible_message_count}")
    print(f"checkpoint_id: {checkpoint.checkpoint_id}")
    print(f"摘要字符数: {len(checkpoint.summary_text)}")
    print(f"保留原始消息数: {len(checkpoint.messages)}")
    print(f"Durable 委派数: {len(checkpoint.delegations)}")
    print(f"Durable 技能引用数: {len(checkpoint.skill_context)}")
    todo_items = (
        checkpoint.todos.get("items")
        if isinstance(checkpoint.todos, dict)
        else None
    )
    print(
        "Durable Todo 项数: "
        f"{len(todo_items) if isinstance(todo_items, list) else 0}"
    )

    if not summary_only:
        if checkpoint.messages:
            first_message = checkpoint.messages[0]
            first_preview = _preview(_message_content(first_message), 160)
            print(
                "压缩分界后的第一条原文: "
                f"{_message_label(first_message)} | {first_preview}"
            )
        else:
            print("压缩分界后的第一条原文: [无]")

    print("\n===== summary_text（此前内容已压缩到这里） =====")
    print(checkpoint.summary_text or "[尚未生成摘要]")
    if summary_only:
        print(
            "\n===== summary_text 结束"
            f"（已打印 {len(checkpoint.summary_text)} 个字符） ====="
        )
        return

    print("\n===== durable context（摘要不会覆盖的结构化状态） =====")
    durable_payload = {
        "delegations": checkpoint.delegations,
        "skill_context": checkpoint.skill_context,
        "todos": checkpoint.todos,
    }
    print(
        json.dumps(
            durable_payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    print("\n===== retained messages（分界后仍保留原文） =====")
    for index, message in enumerate(checkpoint.messages, start=1):
        content = _message_content(message)
        rendered_content = content if full else _preview(content, preview_chars)
        message_id = getattr(message, "id", None)
        print(
            f"\n[{index:03d}] {_message_label(message)} "
            f"id={message_id} chars={len(content)}"
        )
        print(rendered_content)
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            rendered_calls = json.dumps(
                tool_calls,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            if not full:
                rendered_calls = _preview(rendered_calls, preview_chars)
            print("tool_calls:")
            print(rendered_calls)


def _build_parser(settings: Settings) -> argparse.ArgumentParser:
    """创建命令行参数，并复用应用当前数据库路径配置。"""
    parser = argparse.ArgumentParser(
        description="只读打印线程摘要、Durable Context 和 checkpoint 原始消息窗口。"
    )
    parser.add_argument("title", nargs="?", help="精确线程标题")
    parser.add_argument("--thread-id", help="线程 ID；标题重复时优先使用")
    parser.add_argument(
        "--application-db",
        type=Path,
        default=settings.application_database_path,
        help="产品历史 SQLite 路径",
    )
    parser.add_argument(
        "--checkpoint-db",
        type=Path,
        default=settings.checkpoint_database_path,
        help="LangGraph checkpoint SQLite 路径",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="打印完整工具结果；默认只显示每条消息的头尾预览",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="只打印线程元数据和完整摘要，不打印分界后的原始消息",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=320,
        help="精简模式下每条消息最多显示的字符数",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析参数并执行一次完全只读的线程上下文检查。"""
    if hasattr(sys.stdout, "reconfigure"):
        # Windows 默认代码页可能破坏中文 checkpoint；显式输出 UTF-8。
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = _build_parser(Settings())
    args = parser.parse_args(argv)
    if args.title is not None and args.thread_id is not None:
        parser.error("线程标题和 --thread-id 只能选择一个")
    if args.preview_chars < 1:
        parser.error("--preview-chars 必须为正整数")
    try:
        with _open_readonly(args.application_db) as application_connection:
            thread = _find_thread(
                application_connection,
                title=args.title,
                thread_id=args.thread_id,
            )
            visible_count = _visible_message_count(
                application_connection,
                thread.thread_id,
            )
        with _open_readonly(args.checkpoint_db) as checkpoint_connection:
            checkpoint = _load_latest_checkpoint(
                checkpoint_connection,
                thread.thread_id,
            )
    except (FileNotFoundError, LookupError, sqlite3.Error, ValueError) as exc:
        print(f"检查失败: {exc}", file=sys.stderr)
        return 1
    _print_context(
        thread,
        visible_count,
        checkpoint,
        full=args.full,
        summary_only=args.summary_only,
        preview_chars=args.preview_chars,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
