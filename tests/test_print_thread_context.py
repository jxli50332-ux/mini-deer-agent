"""验证线程上下文检查脚本能只读展示摘要与原始消息分界。"""

import sqlite3
import subprocess
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "examples" / "print_thread_context.py"


def _create_application_database(path: Path, thread_id: str) -> None:
    """创建脚本查询所需的最小产品历史库。"""
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE threads (
                thread_id TEXT PRIMARY KEY,
                title TEXT,
                status TEXT,
                updated_at TEXT
            );
            CREATE TABLE timeline_items (
                item_id TEXT PRIMARY KEY,
                thread_id TEXT,
                thread_sequence INTEGER
            );
            CREATE TABLE messages (
                item_id TEXT PRIMARY KEY,
                role TEXT,
                content TEXT,
                hidden_from_ui INTEGER
            );
            """
        )
        connection.execute(
            "INSERT INTO threads VALUES (?, ?, 'idle', '2026-09-01T00:00:00Z')",
            (thread_id, "上下文测试"),
        )
        connection.execute(
            "INSERT INTO timeline_items VALUES ('item-1', ?, 1)",
            (thread_id,),
        )
        connection.execute(
            "INSERT INTO messages VALUES ('item-1', 'user', '完整产品历史', 0)"
        )


def _create_checkpoint_database(path: Path, thread_id: str) -> None:
    """创建含累计摘要与最近原文的最小 LangGraph checkpoint。"""
    serializer = JsonPlusSerializer()
    checkpoint_type, checkpoint_blob = serializer.dumps_typed(
        {
            "channel_values": {
                "summary_text": "旧消息已经压缩到这里。\n第二行摘要。\n第三行摘要。",
                "messages": [
                    HumanMessage(content="最近用户问题。", id="human-latest"),
                    AIMessage(content="最近模型回答。", id="ai-latest"),
                ],
                "delegations": [
                    {
                        "id": "task-1",
                        "turn_id": "human-old",
                        "description": "核对资料",
                        "subagent_type": "research",
                        "status": "completed",
                        "result_brief": "资料已经核对。",
                        "result_sha256": "abc123",
                    }
                ],
                "skill_context": [
                    {
                        "name": "structured-explainer",
                        "description": "分层解释技术概念。",
                        "path": "builtin://structured-explainer/SKILL.md",
                        "source": "automatic",
                        "turn_id": "human-old",
                    }
                ],
                "todos": {
                    "turn_id": "human-old",
                    "items": [
                        {"content": "整理结论", "status": "in_progress"}
                    ],
                },
            }
        }
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL DEFAULT '',
                checkpoint_id TEXT NOT NULL,
                parent_checkpoint_id TEXT,
                type TEXT,
                checkpoint BLOB,
                metadata BLOB,
                PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
            )
            """
        )
        connection.execute(
            "INSERT INTO checkpoints VALUES (?, '', 'checkpoint-1', NULL, ?, ?, NULL)",
            (thread_id, checkpoint_type, checkpoint_blob),
        )


def test_script_prints_summary_and_retained_boundary(tmp_path: Path) -> None:
    """按标题检查时应打印完整摘要、近期原文和产品历史计数。"""
    thread_id = "thread-context-test"
    application_database = tmp_path / "application.sqlite"
    checkpoint_database = tmp_path / "checkpoints.sqlite"
    _create_application_database(application_database, thread_id)
    _create_checkpoint_database(checkpoint_database, thread_id)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "上下文测试",
            "--application-db",
            str(application_database),
            "--checkpoint-db",
            str(checkpoint_database),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "thread-context-test" in result.stdout
    assert "产品可见消息数: 1" in result.stdout
    assert "旧消息已经压缩到这里。" in result.stdout
    assert "第二行摘要。\n第三行摘要。" in result.stdout
    assert "压缩分界后的第一条原文: human | 最近用户问题。" in result.stdout
    assert "保留原始消息数: 2" in result.stdout
    assert "Durable 委派数: 1" in result.stdout
    assert "Durable 技能引用数: 1" in result.stdout
    assert "Durable Todo 项数: 1" in result.stdout
    assert "核对资料" in result.stdout
    assert "structured-explainer" in result.stdout
    assert "整理结论" in result.stdout
    assert "最近模型回答。" in result.stdout


def test_summary_only_prints_complete_summary_without_retained_messages(
    tmp_path: Path,
) -> None:
    """摘要专用模式应完整打印多行摘要，并跳过大量原始消息。"""
    thread_id = "thread-summary-only-test"
    application_database = tmp_path / "application.sqlite"
    checkpoint_database = tmp_path / "checkpoints.sqlite"
    _create_application_database(application_database, thread_id)
    _create_checkpoint_database(checkpoint_database, thread_id)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "上下文测试",
            "--summary-only",
            "--application-db",
            str(application_database),
            "--checkpoint-db",
            str(checkpoint_database),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "旧消息已经压缩到这里。\n第二行摘要。\n第三行摘要。" in result.stdout
    assert "summary_text 结束（已打印 25 个字符）" in result.stdout
    assert "retained messages" not in result.stdout
    assert "最近用户问题。" not in result.stdout
