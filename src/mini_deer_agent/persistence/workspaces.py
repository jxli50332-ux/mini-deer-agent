"""使用业务数据库的同一连接与锁保存项目，迁移统一由业务库管理。"""

import os
import sqlite3
from threading import RLock
from typing import cast

from mini_deer_agent.domain.workspaces import ProjectError, ProjectRecord, ProjectStatus


PROJECT_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE projects (
        project_id TEXT PRIMARY KEY,
        name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
        root_path TEXT NOT NULL,
        root_key TEXT NOT NULL UNIQUE,
        root_identity TEXT NOT NULL,
        access_mode TEXT NOT NULL CHECK (access_mode = 'read_write'),
        status TEXT NOT NULL CHECK (status IN ('available', 'missing', 'unavailable', 'changed')),
        status_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_projects_created ON projects(created_at DESC, project_id DESC)",
)


def _from_row(row: sqlite3.Row) -> ProjectRecord:
    """适配器内部字段不进入公开响应，保持目录身份校验的职责边界。"""
    return ProjectRecord(
        project_id=row["project_id"],
        name=row["name"],
        root_path=row["root_path"],
        root_identity=row["root_identity"],
        status=cast(ProjectStatus, row["status"]),
        status_reason=row["status_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        access_mode="read_write",
    )


class SqliteProjectRepository:
    """保存独立项目，不定义 Thread 外键或任何文件系统删除行为。"""

    def __init__(self, connection: sqlite3.Connection, lock: RLock) -> None:
        """连接生命周期由业务库拥有，共享锁避免并发事务互相提交。"""
        self._connection = connection
        self._lock = lock

    def insert(self, project: ProjectRecord) -> None:
        """唯一根约束处理并发；Windows 大小写变体不能创建重复授权记录。"""
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    """INSERT INTO projects (
                        project_id, name, root_path, root_key, root_identity, access_mode,
                        status, status_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project.project_id,
                        project.name,
                        project.root_path,
                        os.path.normcase(project.root_path),
                        project.root_identity,
                        project.access_mode,
                        project.status,
                        project.status_reason,
                        project.created_at,
                        project.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "projects.root_key" not in str(exc):
                raise
            raise ProjectError(
                "project_already_registered", "该项目目录已登记。"
            ) from None

    def get(self, project_id: str) -> ProjectRecord | None:
        """使用参数化查询读取单个项目，不拼接外部 ID。"""
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM projects WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list(self, *, limit: int, offset: int) -> tuple[ProjectRecord, ...]:
        """按创建时间和 ID 排序，状态刷新不会让分页顺序跳动。"""
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM projects ORDER BY created_at DESC, project_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return tuple(_from_row(row) for row in rows)

    def update_status(self, project: ProjectRecord) -> None:
        """只写状态和时间，不能重绑目录或修改权限。"""
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE projects SET status = ?, status_reason = ?, updated_at = ? WHERE project_id = ?",
                (
                    project.status,
                    project.status_reason,
                    project.updated_at,
                    project.project_id,
                ),
            )

    def remove(self, project_id: str) -> None:
        """只删除指定项目行；重复解除没有副作用，不触及原目录或 Thread 表。"""
        with self._lock, self._connection:
            self._connection.execute(
                "DELETE FROM projects WHERE project_id = ?", (project_id,)
            )
