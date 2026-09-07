"""编排项目登记和可查询状态，不依赖 FastAPI、模型或 LangGraph。"""

from dataclasses import replace
from datetime import UTC, datetime
from collections.abc import Callable
import re
from typing import Protocol
from uuid import uuid4
from pathlib import Path
from mini_deer_agent.workspace.directory import ignored, list_directory
from mini_deer_agent.workspace.files import read_project_file
from mini_deer_agent.workspace.search import (
    MAX_SCANNED_ENTRIES,
    MAX_SEARCH_BYTES,
    MAX_SEARCH_FILES,
    MAX_SEARCH_OUTPUT_CHARS,
    SEARCH_TIME_BUDGET_SECONDS,
    glob_project_files,
    matches_glob_pattern,
    search_project_files,
    validate_glob_query,
)
from mini_deer_agent.workspace.writes import (
    create_directory,
    create_text_file,
    delete_file,
    move_file,
    overwrite_text_file,
    rename_file,
    replace_text,
)

from mini_deer_agent.domain.conversations import ThreadRecord
from mini_deer_agent.domain.workspaces import (
    FileAccessRoot,
    FileAccessScope,
    ProjectError,
    ProjectRecord,
    ProjectStatus,
)
from mini_deer_agent.workspace.paths import ProjectRootPolicy


class ProjectRepository(Protocol):
    """定义独立项目仓储端口，与对话仓储共享数据库属于适配器选择。"""

    def insert(self, project: ProjectRecord) -> None:
        """保存新项目，重复根路径必须原子拒绝。"""

    def get(self, project_id: str) -> ProjectRecord | None:
        """查询已登记项目，缺失时返回 None。"""

    def list(self, *, limit: int, offset: int) -> tuple[ProjectRecord, ...]:
        """返回有界、稳定排序的项目记录。"""

    def update_status(self, project: ProjectRecord) -> None:
        """只更新可用状态，不能通过状态刷新替换登记身份。"""

    def remove(self, project_id: str) -> None:
        """幂等移除登记元数据，不访问项目目录或删除会话。"""


class ProjectRepositoryProvider(Protocol):
    """由应用数据库资源暴露项目子仓储，避免 HTTP 访问连接和锁。"""

    projects: ProjectRepository


class ThreadProjectConflictError(RuntimeError):
    """表示已有 Thread 被请求绑定到另一个 Project。"""


class ProjectThreadRepository(Protocol):
    """定义 Project 与 Thread 归属所需的最小持久化端口。"""

    def create_project_thread(self, *, thread_id: str, project_id: str) -> ThreadRecord:
        """创建或幂等读回同归属 Thread，禁止重绑已有身份。"""

    def list_project_threads(
        self, project_id: str, *, limit: int
    ) -> tuple[ThreadRecord, ...]:
        """按最近活动时间返回指定 Project 的 Thread。"""


class ThreadFileAccessRepository(Protocol):
    """只暴露从持久 Thread 解析文件 Scope 所需的查询。"""

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        """返回持久 Thread 元数据；不存在时返回 None。"""


class ProjectService:
    """登记已有目录并复核状态；此用例没有创建或修改项目文件的路径。"""

    def __init__(
        self, repository: ProjectRepository, policy: ProjectRootPolicy
    ) -> None:
        """保存仓储与可信目录策略，不从模型参数解析运行配置。"""
        self._repository = repository
        self._policy = policy

    def register(self, *, name: str, root_path: str) -> ProjectRecord:
        """验证根目录后生成独立 Project ID，唯一性由持久化约束保护。"""
        normalized_name = " ".join(name.split())
        if not 1 <= len(normalized_name) <= 80:
            raise ProjectError("project_name_invalid", "项目名称应为 1—80 个字符。")
        root = self._policy.inspect(root_path)
        now = datetime.now(UTC).isoformat()
        project = ProjectRecord(
            project_id=str(uuid4()),
            name=normalized_name,
            root_path=str(root.path),
            root_identity=root.identity,
            status="available",
            status_reason=None,
            created_at=now,
            updated_at=now,
        )
        self._repository.insert(project)
        return project

    def get(self, project_id: str) -> ProjectRecord | None:
        """保留失效登记，并返回真实状态，让用户能够识别外部目录变化。"""
        project = self._repository.get(project_id)
        return self._refresh(project) if project is not None else None

    def unregister(self, project_id: str) -> None:
        """解除登记不检查目录可用性，原目录失效时仍可清理登记。"""
        self._repository.remove(project_id)

    def directory(self, project_id: str, *, path: str = "", limit: int = 200) -> dict:
        """每次展开复核登记根，枚举后再次确认身份，拒绝失效项目。"""
        project = self.get(project_id)
        if project is None:
            raise ProjectError("project_not_found", "项目尚未登记。")
        if project.status != "available":
            raise ProjectError("project_unavailable", "项目目录当前不可用。")
        result = list_directory(Path(project.root_path), path, limit=limit)
        current = self.get(project_id)
        if current is None or current.status != "available":
            raise ProjectError("project_unavailable", "项目在列举期间发生变化。")
        return {"project_id": project_id, **result}

    def list(self, *, limit: int = 20, offset: int = 0) -> tuple[ProjectRecord, ...]:
        """限制单次 IO；额外一条用于 HTTP 返回下一页信息。"""
        if not 1 <= limit <= 101 or not 0 <= offset <= 10000:
            raise ProjectError("project_page_invalid", "项目分页范围无效。")
        return tuple(
            self._refresh(project)
            for project in self._repository.list(limit=limit, offset=offset)
        )

    def read_file(
        self, project_id: str, *, path: str, start_line: int = 1, limit: int = 200
    ) -> dict:
        """只读预览前后复核项目，失效根不能返回文件正文。"""
        project = self.get(project_id)
        if project is None:
            raise ProjectError("project_not_found", "项目尚未登记。")
        if project.status != "available":
            raise ProjectError("project_unavailable", "项目目录当前不可用。")
        result = read_project_file(
            Path(project.root_path), path, start_line=start_line, limit=limit
        )
        current = self.get(project_id)
        if current is None or current.status != "available":
            raise ProjectError("project_unavailable", "项目在读取期间发生变化。")
        return {"project_id": project_id, **result}

    def _refresh(self, project: ProjectRecord) -> ProjectRecord:
        """复核目录身份但不接受替换后的根，状态改变才落盘。"""
        status: ProjectStatus = "available"
        reason = None
        try:
            root = self._policy.inspect(project.root_path)
            if root.identity != project.root_identity:
                status, reason = "changed", "project_root_changed"
        except ProjectError as exc:
            status = (
                "missing"
                if exc.code == "project_root_missing"
                else "changed" if exc.code == "project_root_changed" else "unavailable"
            )
            reason = exc.code
        if status == project.status and reason == project.status_reason:
            return project
        refreshed = replace(
            project,
            status=status,
            status_reason=reason,
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._repository.update_status(refreshed)
        return refreshed


class FileAccess:
    """把 Project、明确路径或普通根冻结为同一种文件访问上下文。"""

    def __init__(
        self, scope: FileAccessScope, validate: Callable[[], None]
    ) -> None:
        """保存可信 Scope 和复核函数；模型只能传 Scope 内相对路径。"""
        self.scope = scope
        self._validate_binding = validate

    @classmethod
    def for_project(
        cls, service: ProjectService, project_id: str
    ) -> "FileAccess":
        """把已登记 Project 转成通用目录 Scope，并保留解除登记复核。"""
        snapshot = service.get(project_id)
        if snapshot is None or snapshot.status != "available":
            raise ProjectError(
                "project_unavailable", "项目当前不可用，不能创建读取工具。"
            )
        scope = FileAccessScope(
            source="project",
            target_path=snapshot.root_path,
            target_identity=snapshot.root_identity,
            target_kind="directory",
            project_id=snapshot.project_id,
        )

        def validate() -> None:
            current = service.get(snapshot.project_id)
            if (
                current is None
                or current.status != "available"
                or current.root_path != snapshot.root_path
                or current.root_identity != snapshot.root_identity
                or current.access_mode != snapshot.access_mode
            ):
                raise ProjectError(
                    "project_binding_changed",
                    "项目授权状态或根目录已变化，请重新开始。",
                )

        return cls(scope, validate)

    @classmethod
    def for_explicit_path(
        cls,
        policy: ProjectRootPolicy,
        target_path: str,
        *,
        require_allowed_root: bool = True,
    ) -> "FileAccess":
        """授权用户明确指定的单文件或目录，不创建隐式 Project。"""
        inspect = (
            policy.inspect_target
            if require_allowed_root
            else policy.inspect_explicit_target
        )
        target = inspect(target_path)
        if target.kind == "file" and ignored(target.path.name):
            raise ProjectError(
                "project_path_invalid", "文件路径无效或已被忽略。"
            )
        scope = FileAccessScope(
            source="explicit",
            target_path=str(target.path),
            target_identity=target.identity,
            target_kind=target.kind,
        )

        def validate() -> None:
            current = inspect(scope.target_path)
            if (
                current.path != Path(scope.target_path)
                or current.identity != scope.target_identity
                or current.kind != scope.target_kind
                or (current.kind == "file" and ignored(current.path.name))
            ):
                raise ProjectError(
                    "file_access_binding_changed",
                    "文件访问目标或授权状态已变化，请重新指定。",
                )

        return cls(scope, validate)

    @classmethod
    def for_allowed_roots(
        cls, policy: ProjectRootPolicy
    ) -> "FileAccess":
        """把配置允许根映射成普通 Thread 始终可用的虚拟只读根。"""
        inspected = policy.inspect_allowed_roots()
        roots = tuple(
            FileAccessRoot(
                alias=f"workspace-{index}",
                path=str(root.path),
                identity=root.identity,
            )
            for index, root in enumerate(inspected, start=1)
        )
        scope = FileAccessScope(
            source="workspace",
            target_path="",
            target_identity="",
            target_kind="roots",
            roots=roots,
        )

        def validate() -> None:
            current = policy.inspect_allowed_roots()
            current_identity = tuple(
                (str(root.path), root.identity) for root in current
            )
            frozen_identity = tuple(
                (root.path, root.identity) for root in scope.roots
            )
            if current_identity != frozen_identity:
                raise ProjectError(
                    "file_access_binding_changed",
                    "允许文件范围已变化，请重新开始。",
                )

        return cls(scope, validate)

    def _identity_fields(self) -> dict:
        """只返回模型需要的来源事实，不泄露宿主绝对路径或文件身份。"""
        result = {"access_source": self.scope.source}
        if self.scope.project_id is not None:
            result["project_id"] = self.scope.project_id
        return result

    def list_files(self, *, path: str = "", limit: int = 200) -> dict:
        """列目录；单文件 Scope 的根只暴露被明确授权的那一个文件。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            result = self._list_allowed_roots(path=path, limit=limit)
        elif self.scope.target_kind == "directory":
            result = list_directory(
                Path(self.scope.target_path), path, limit=limit
            )
        else:
            if path or not 1 <= limit <= 500:
                raise ProjectError(
                    "project_path_invalid", "目录路径无效或已被忽略。"
                )
            name = Path(self.scope.target_path).name
            result = {
                "path": "",
                "items": [
                    {
                        "name": name,
                        "path": name,
                        "kind": "file",
                        "status": "available",
                        "reason": None,
                    }
                ],
                "truncated": False,
                "truncation_reason": None,
                "limit": limit,
            }
        self._validate_binding()
        return {**self._identity_fields(), **result}

    def _split_allowed_root(self, path: str) -> tuple[FileAccessRoot, str]:
        """把虚拟路径解析为已冻结允许根与其内部相对路径。"""
        alias, separator, relative = path.partition("/")
        root = next(
            (candidate for candidate in self.scope.roots if candidate.alias == alias),
            None,
        )
        if root is None or (separator and not relative):
            raise ProjectError(
                "file_access_path_out_of_scope",
                "该路径不在普通 Thread 的允许文件范围内。",
            )
        return root, relative

    def _list_allowed_roots(self, *, path: str, limit: int) -> dict:
        """在虚拟根列出配置入口，进入入口后复用目录读取策略。"""
        if not path:
            if not 1 <= limit <= 500:
                raise ProjectError(
                    "project_path_invalid", "目录路径无效或已被忽略。"
                )
            items = [
                {
                    "name": Path(root.path).name or root.alias,
                    "path": root.alias,
                    "kind": "directory",
                    "status": "available",
                    "reason": None,
                }
                for root in self.scope.roots[:limit]
            ]
            truncated = len(self.scope.roots) > limit
            return {
                "path": "",
                "items": items,
                "truncated": truncated,
                "truncation_reason": "entry_limit" if truncated else None,
                "limit": limit,
            }
        root, relative = self._split_allowed_root(path)
        result = list_directory(Path(root.path), relative, limit=limit)
        return {
            **result,
            "path": root.alias if not result["path"] else f'{root.alias}/{result["path"]}',
            "items": [
                {**item, "path": f'{root.alias}/{item["path"]}'}
                for item in result["items"]
            ],
        }

    def read_file(
        self, *, path: str, start_line: int = 1, limit: int = 200
    ) -> dict:
        """读取 Scope 内文件；单文件 Scope 不能借相对路径访问兄弟文件。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            selected_root, selected_path = self._split_allowed_root(path)
            if not selected_path:
                raise ProjectError(
                    "project_path_invalid", "文件路径无效或已被忽略。"
                )
            root = Path(selected_root.path)
            read_path = selected_path
        elif self.scope.target_kind == "directory":
            root = Path(self.scope.target_path)
            read_path = path
        else:
            target = Path(self.scope.target_path)
            if path != target.name:
                raise ProjectError(
                    "file_access_path_out_of_scope",
                    "该文件不在本次明确授权范围内。",
                )
            root = target.parent
            read_path = path
        result = read_project_file(
            root, read_path, start_line=start_line, limit=limit
        )
        if self.scope.target_kind == "roots":
            result = {**result, "path": path}
        self._validate_binding()
        # 明确返回每条文本对应的真实行号，避免模型因空行自行计数出错。
        line_numbers = list(
            range(result["start_line"], result["start_line"] + len(result["lines"]))
        )
        return {
            **self._identity_fields(),
            **result,
            "line_numbers": line_numbers,
        }

    def glob_files(
        self, *, pattern: str, path: str = "", limit: int = 100
    ) -> dict:
        """在 Scope 内按文件名模式递归查找，不读取候选文件正文。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            result = self._glob_allowed_roots(
                path=path, pattern=pattern, limit=limit
            )
        elif self.scope.target_kind == "directory":
            result = glob_project_files(
                Path(self.scope.target_path), path, pattern, limit=limit
            )
        else:
            target = Path(self.scope.target_path)
            validate_glob_query(pattern, limit)
            if path:
                raise ProjectError(
                    "file_access_path_out_of_scope",
                    "该路径不在本次明确授权范围内。",
                )
            matches = (
                [target.name]
                if matches_glob_pattern(pattern, target.name)
                else []
            )
            result = {
                "path": "",
                "pattern": pattern,
                "matches": matches,
                "truncated": False,
                "truncation_reason": None,
                "limit": limit,
                "scanned_entries": 1,
            }
        self._validate_binding()
        return {**self._identity_fields(), **result}

    def search_files(
        self,
        *,
        query: str,
        path: str = "",
        file_pattern: str | None = None,
        case_sensitive: bool = False,
        limit: int = 100,
    ) -> dict:
        """在 Scope 内搜索字面量正文，返回虚拟路径和真实行号。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            result = self._search_allowed_roots(
                query=query,
                path=path,
                file_pattern=file_pattern,
                case_sensitive=case_sensitive,
                limit=limit,
            )
        elif self.scope.target_kind == "directory":
            result = search_project_files(
                Path(self.scope.target_path),
                path,
                query,
                file_pattern=file_pattern,
                case_sensitive=case_sensitive,
                limit=limit,
            )
        else:
            target = Path(self.scope.target_path)
            if path not in {"", target.name}:
                raise ProjectError(
                    "file_access_path_out_of_scope",
                    "该路径不在本次明确授权范围内。",
                )
            result = search_project_files(
                target.parent,
                target.name,
                query,
                file_pattern=file_pattern,
                case_sensitive=case_sensitive,
                limit=limit,
            )
            result = {**result, "path": path}
        self._validate_binding()
        return {**self._identity_fields(), **result}

    def create_file(self, *, path: str, content: str) -> dict:
        """在目录 Scope 中创建新文本文件，已有目标保持不变。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            selected_root, selected_path = self._split_allowed_root(path)
            if not selected_path:
                raise ProjectError("file_create_invalid", "请指定新文件路径。")
            root = Path(selected_root.path)
            create_path = selected_path
        elif self.scope.target_kind == "directory":
            root = Path(self.scope.target_path)
            create_path = path
        else:
            raise ProjectError(
                "file_access_path_out_of_scope",
                "单文件范围不能创建其他文件。",
            )
        result = create_text_file(root, create_path, content)
        if self.scope.target_kind == "roots":
            result = {**result, "path": path}
        self._validate_binding()
        return {**self._identity_fields(), **result}

    def str_replace(self, *, path: str, old_str: str, new_str: str) -> dict:
        """在 Scope 内已有文本文件中执行唯一精确替换。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            selected_root, selected_path = self._split_allowed_root(path)
            if not selected_path:
                raise ProjectError("file_replace_invalid", "请指定要编辑的文件。")
            root = Path(selected_root.path)
            replace_path = selected_path
        elif self.scope.target_kind == "directory":
            root = Path(self.scope.target_path)
            replace_path = path
        else:
            target = Path(self.scope.target_path)
            if path != target.name:
                raise ProjectError(
                    "file_access_path_out_of_scope",
                    "该文件不在本次明确授权范围内。",
                )
            root = target.parent
            replace_path = path
        result = replace_text(root, replace_path, old_str, new_str)
        if self.scope.target_kind == "roots":
            result = {**result, "path": path}
        self._validate_binding()
        return {**self._identity_fields(), **result}

    def write_file(self, *, path: str, content: str) -> dict:
        """在 Scope 内使用完整文本覆盖已有文件。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            selected_root, selected_path = self._split_allowed_root(path)
            if not selected_path:
                raise ProjectError("file_write_invalid", "请指定要更新的文件。")
            root = Path(selected_root.path)
            write_path = selected_path
        elif self.scope.target_kind == "directory":
            root = Path(self.scope.target_path)
            write_path = path
        else:
            target = Path(self.scope.target_path)
            if path != target.name:
                raise ProjectError(
                    "file_access_path_out_of_scope",
                    "该文件不在本次明确授权范围内。",
                )
            root = target.parent
            write_path = path
        result = overwrite_text_file(root, write_path, content)
        if self.scope.target_kind == "roots":
            result = {**result, "path": path}
        self._validate_binding()
        return {**self._identity_fields(), **result}

    def create_directory(self, *, path: str) -> dict:
        """在目录 Scope 内建立一个子目录。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            selected, relative = self._split_allowed_root(path)
            root = Path(selected.path)
        elif self.scope.target_kind == "directory":
            root, relative = Path(self.scope.target_path), path
        else:
            raise ProjectError("file_access_path_out_of_scope", "单文件范围不能创建目录。")
        result = create_directory(root, relative)
        self._validate_binding()
        return {**self._identity_fields(), **result, "path": path}

    def rename_file(self, *, path: str, new_name: str) -> dict:
        """在目录 Scope 中重命名普通文件。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            selected, relative = self._split_allowed_root(path)
            root = Path(selected.path)
        elif self.scope.target_kind == "directory":
            root, relative = Path(self.scope.target_path), path
        else:
            raise ProjectError("file_access_path_out_of_scope", "重命名需要指定所在目录范围。")
        result = rename_file(root, relative, new_name)
        if self.scope.target_kind == "roots":
            result = {**result, "path": f'{selected.alias}/{result["path"]}',
                      "previous_path": path}
        self._validate_binding()
        return {**self._identity_fields(), **result}

    def move_file(self, *, path: str, new_path: str) -> dict:
        """在同一目录 Scope 内移动普通文件。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            source_root, source_relative = self._split_allowed_root(path)
            target_root, target_relative = self._split_allowed_root(new_path)
            if source_root != target_root:
                raise ProjectError(
                    "file_access_path_out_of_scope", "文件不能跨允许根移动。"
                )
            root = Path(source_root.path)
        elif self.scope.target_kind == "directory":
            root = Path(self.scope.target_path)
            source_relative, target_relative = path, new_path
        else:
            raise ProjectError(
                "file_access_path_out_of_scope", "移动文件需要指定所在目录范围。"
            )
        result = move_file(root, source_relative, target_relative)
        if self.scope.target_kind == "roots":
            result = {
                **result,
                "path": f'{source_root.alias}/{result["path"]}',
                "previous_path": path,
            }
        self._validate_binding()
        return {**self._identity_fields(), **result}

    def delete_file(self, *, path: str) -> dict:
        """删除 Scope 中的一个普通文件，不接受目录。"""
        self._validate_binding()
        if self.scope.target_kind == "roots":
            selected, relative = self._split_allowed_root(path)
            root = Path(selected.path)
        elif self.scope.target_kind == "directory":
            root, relative = Path(self.scope.target_path), path
        else:
            target = Path(self.scope.target_path)
            if path != target.name:
                raise ProjectError(
                    "file_access_path_out_of_scope",
                    "该文件不在本次明确授权范围内。",
                )
            root, relative = target.parent, path
        result = delete_file(root, relative)
        if self.scope.target_kind == "roots":
            result = {**result, "path": path}
        if self.scope.target_kind != "file":
            self._validate_binding()
        return {**self._identity_fields(), **result}

    def _glob_allowed_roots(
        self, *, path: str, pattern: str, limit: int
    ) -> dict:
        """跨普通 Thread 虚拟根聚合匹配，并维持全局结果预算。"""
        if path:
            root, relative = self._split_allowed_root(path)
            result = glob_project_files(
                Path(root.path), relative, pattern, limit=limit
            )
            return {
                **result,
                "path": root.alias if not relative else path,
                "matches": [f'{root.alias}/{match}' for match in result["matches"]],
            }

        matches: list[str] = []
        scanned_entries = 0
        truncation_reason: str | None = None
        root_count = len(self.scope.roots)
        for root in self.scope.roots:
            result = glob_project_files(
                Path(root.path),
                "",
                pattern,
                limit=limit,
                time_budget_seconds=SEARCH_TIME_BUDGET_SECONDS / root_count,
                scan_limit=max(1, MAX_SCANNED_ENTRIES // root_count),
            )
            scanned_entries += result["scanned_entries"]
            matches.extend(
                f'{root.alias}/{match}' for match in result["matches"]
            )
            if result["truncated"] and truncation_reason is None:
                truncation_reason = result["truncation_reason"]
            if len(matches) > limit:
                matches = matches[:limit]
                truncation_reason = "result_limit"
                break
        return {
            "path": "",
            "pattern": pattern,
            "matches": matches,
            "truncated": truncation_reason is not None,
            "truncation_reason": truncation_reason,
            "limit": limit,
            "scanned_entries": scanned_entries,
        }

    def _search_allowed_roots(
        self,
        *,
        query: str,
        path: str,
        file_pattern: str | None,
        case_sensitive: bool,
        limit: int,
    ) -> dict:
        """跨普通 Thread 虚拟根聚合正文结果，并维持全局预算。"""
        if path:
            root, relative = self._split_allowed_root(path)
            result = search_project_files(
                Path(root.path),
                relative,
                query,
                file_pattern=file_pattern,
                case_sensitive=case_sensitive,
                limit=limit,
            )
            return {
                **result,
                "path": root.alias if not relative else path,
                "matches": [
                    {**match, "path": f'{root.alias}/{match["path"]}'}
                    for match in result["matches"]
                ],
            }

        matches: list[dict] = []
        totals = {
            "scanned_entries": 0,
            "scanned_files": 0,
            "scanned_bytes": 0,
            "skipped_files": 0,
            "skipped_lines": 0,
            "output_chars": 0,
        }
        truncation_reason: str | None = None
        root_count = len(self.scope.roots)
        for index, root in enumerate(self.scope.roots):
            remaining = limit - len(matches)
            if remaining <= 0:
                truncation_reason = "result_limit"
                break
            result = search_project_files(
                Path(root.path),
                "",
                query,
                file_pattern=file_pattern,
                case_sensitive=case_sensitive,
                limit=remaining,
                time_budget_seconds=SEARCH_TIME_BUDGET_SECONDS / root_count,
                scan_limit=max(1, MAX_SCANNED_ENTRIES // root_count),
                file_limit=max(1, MAX_SEARCH_FILES // root_count),
                byte_budget=max(1, MAX_SEARCH_BYTES // root_count),
                output_budget=max(1, MAX_SEARCH_OUTPUT_CHARS // root_count),
            )
            matches.extend(
                {**match, "path": f'{root.alias}/{match["path"]}'}
                for match in result["matches"]
            )
            for key in totals:
                totals[key] += result[key]
            if result["truncated"] and result["truncation_reason"] != (
                "unsupported_content"
            ):
                truncation_reason = result["truncation_reason"]
                break
            if result["truncated"] and truncation_reason is None:
                truncation_reason = result["truncation_reason"]
            if len(matches) >= limit and index + 1 < root_count:
                truncation_reason = "result_limit"
                break
        return {
            "path": "",
            "query": query,
            "file_pattern": file_pattern,
            "case_sensitive": case_sensitive,
            "matches": matches,
            "truncated": truncation_reason is not None,
            "truncation_reason": truncation_reason,
            "limit": limit,
            **totals,
        }


_QUOTED_WINDOWS_PATH = re.compile(
    r"(?:`([^`\r\n]+)`|\"([^\"\r\n]+)\"|'([^'\r\n]+)')"
)
_BARE_WINDOWS_PATH = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z]:[\\/][^\s，。；;！？!?\"'`\r\n]+)"
)


def _explicit_windows_paths(message: str) -> tuple[str, ...]:
    """提取用户本轮明确写出的 Windows 绝对路径；含空格时要求引号。"""
    candidates = [
        value
        for match in _QUOTED_WINDOWS_PATH.finditer(message)
        if (value := next((part for part in match.groups() if part), ""))
        and re.match(r"^[A-Za-z]:[\\/]", value)
    ]
    candidates.extend(match.group(1) for match in _BARE_WINDOWS_PATH.finditer(message))
    return tuple(dict.fromkeys(value.rstrip(".,") for value in candidates))


ReadOnlyFileAccess = FileAccess


class ProjectRunFileAccess(FileAccess):
    """保留项目相对范围，并附加用户本轮明确写出的根外目标。"""

    def __init__(
        self,
        project: FileAccess,
        explicit: tuple[FileAccess, ...],
    ) -> None:
        self.scope = project.scope
        self._project = project
        self._explicit = explicit

    def _target(
        self, path: str
    ) -> tuple[FileAccess, str, str | None]:
        """绝对路径只匹配本轮冻结目标；其他路径继续解释为项目相对路径。"""
        candidate = Path(path)
        if not candidate.is_absolute():
            return self._project, path, None
        normalized = candidate.resolve(strict=False)
        for access in self._explicit:
            target = Path(access.scope.target_path)
            if access.scope.target_kind == "file" and normalized == target:
                return access, target.name, str(target.parent)
            if access.scope.target_kind == "directory" and normalized.is_relative_to(
                target
            ):
                relative_path = normalized.relative_to(target)
                relative = "" if relative_path == Path(".") else relative_path.as_posix()
                return access, relative, str(target)
        raise ProjectError(
            "file_access_path_out_of_scope",
            "该绝对路径未在本轮用户消息中明确指定。",
        )

    @staticmethod
    def _restore_path(result: dict, absolute: str | None, relative: str) -> dict:
        """外部目标的工具结果沿用用户给出的绝对路径，项目结果保持相对路径。"""
        if absolute is None:
            return result
        base = Path(absolute)
        return {
            **result,
            "path": str(base if not relative else base / relative),
            **(
                {
                    "items": [
                        {**item, "path": str(base / item["path"])}
                        for item in result["items"]
                    ]
                }
                if "items" in result
                else {}
            ),
            **(
                {
                    "matches": [
                        (
                            {**item, "path": str(base / item["path"])}
                            if isinstance(item, dict)
                            else str(base / item)
                        )
                        for item in result["matches"]
                    ]
                }
                if "matches" in result
                else {}
            ),
        }

    def list_files(self, *, path: str = "", limit: int = 200) -> dict:
        access, relative, absolute = self._target(path)
        listed_path = (
            ""
            if absolute is not None and access.scope.target_kind == "file"
            else relative
        )
        return self._restore_path(
            access.list_files(path=listed_path, limit=limit), absolute, listed_path
        )

    def read_file(
        self, *, path: str, start_line: int = 1, limit: int = 200
    ) -> dict:
        access, relative, absolute = self._target(path)
        return self._restore_path(
            access.read_file(path=relative, start_line=start_line, limit=limit),
            absolute,
            relative,
        )

    def glob_files(
        self, *, pattern: str, path: str = "", limit: int = 100
    ) -> dict:
        access, relative, absolute = self._target(path)
        glob_path = (
            ""
            if absolute is not None and access.scope.target_kind == "file"
            else relative
        )
        return self._restore_path(
            access.glob_files(pattern=pattern, path=glob_path, limit=limit),
            absolute,
            glob_path,
        )

    def search_files(
        self,
        *,
        query: str,
        path: str = "",
        file_pattern: str | None = None,
        case_sensitive: bool = False,
        limit: int = 100,
    ) -> dict:
        access, relative, absolute = self._target(path)
        return self._restore_path(
            access.search_files(
                query=query,
                path=relative,
                file_pattern=file_pattern,
                case_sensitive=case_sensitive,
                limit=limit,
            ),
            absolute,
            relative,
        )

    def create_file(self, *, path: str, content: str) -> dict:
        access, relative, absolute = self._target(path)
        return self._restore_path(
            access.create_file(path=relative, content=content),
            absolute,
            relative,
        )

    def str_replace(self, *, path: str, old_str: str, new_str: str) -> dict:
        access, relative, absolute = self._target(path)
        return self._restore_path(
            access.str_replace(path=relative, old_str=old_str, new_str=new_str),
            absolute,
            relative,
        )

    def write_file(self, *, path: str, content: str) -> dict:
        access, relative, absolute = self._target(path)
        return self._restore_path(
            access.write_file(path=relative, content=content),
            absolute,
            relative,
        )

    def create_directory(self, *, path: str) -> dict:
        access, relative, absolute = self._target(path)
        return self._restore_path(
            access.create_directory(path=relative), absolute, relative
        )

    def rename_file(self, *, path: str, new_name: str) -> dict:
        access, relative, absolute = self._target(path)
        result = access.rename_file(path=relative, new_name=new_name)
        if absolute is not None:
            result = {**result, "path": str(Path(absolute) / result["path"]),
                      "previous_path": str(Path(absolute) / relative)}
        return result

    def move_file(self, *, path: str, new_path: str) -> dict:
        source_access, source_relative, source_absolute = self._target(path)
        target_access, target_relative, target_absolute = self._target(new_path)
        if source_access is not target_access:
            raise ProjectError(
                "file_access_path_out_of_scope", "文件不能跨文件范围移动。"
            )
        result = source_access.move_file(
            path=source_relative, new_path=target_relative
        )
        if source_absolute is not None and target_absolute is not None:
            result = {
                **result,
                "path": str(Path(target_absolute) / target_relative),
                "previous_path": str(Path(source_absolute) / source_relative),
            }
        return result

    def delete_file(self, *, path: str) -> dict:
        access, relative, absolute = self._target(path)
        return self._restore_path(
            access.delete_file(path=relative), absolute, relative
        )


class ProjectFileAccessResolver:
    """按持久 Thread 归属解析项目范围或普通 Thread 常驻允许根。"""

    def __init__(
        self,
        threads: ThreadFileAccessRepository,
        projects: ProjectService | None,
        workspace_policy: ProjectRootPolicy | None = None,
    ) -> None:
        self._threads = threads
        self._projects = projects
        self._workspace_policy = workspace_policy

    def __call__(self, thread_id: str, message: str = "") -> FileAccess | None:
        """项目 Thread 冻结项目根；其余 Thread 使用配置允许根。"""
        thread = self._threads.get_thread(thread_id)
        if thread is None or thread.project_id is None:
            return (
                FileAccess.for_allowed_roots(self._workspace_policy)
                if self._workspace_policy is not None
                else None
            )
        if self._projects is None:
            raise ProjectError(
                "project_unavailable", "项目文件访问当前不可用。"
            )
        project_access = FileAccess.for_project(
            self._projects, thread.project_id
        )
        if self._workspace_policy is None:
            return project_access
        project_root = Path(project_access.scope.target_path)
        explicit: list[FileAccess] = []
        for path in _explicit_windows_paths(message):
            try:
                target = self._workspace_policy.inspect_explicit_target(path)
            except ProjectError:
                continue
            if target.path.is_relative_to(project_root):
                continue
            explicit.append(
                FileAccess.for_explicit_path(
                    self._workspace_policy,
                    path,
                    require_allowed_root=False,
                )
            )
        return (
            ProjectRunFileAccess(project_access, tuple(explicit))
            if explicit
            else project_access
        )


class ProjectThreadService:
    """校验 Project 事实后创建和查询不可重绑的 Thread 归属。"""

    def __init__(
        self, projects: ProjectService, threads: ProjectThreadRepository
    ) -> None:
        """复用项目状态校验，并通过对话仓储端口原子写入归属。"""
        self._projects = projects
        self._threads = threads

    def create(self, *, project_id: str, thread_id: str) -> ThreadRecord:
        """只允许可用且仍登记的 Project 创建新 Thread。"""
        project = self._require_project(project_id)
        if project.status != "available":
            raise ProjectError(
                "project_unavailable", "项目目录当前不可用，不能创建项目会话。"
            )
        return self._threads.create_project_thread(
            thread_id=thread_id, project_id=project_id
        )

    def list(self, *, project_id: str, limit: int = 20) -> tuple[ThreadRecord, ...]:
        """查询归属列表前确认 Project 仍登记，避免跨身份猜测关系。"""
        if not 1 <= limit <= 100:
            raise ProjectError("project_thread_page_invalid", "项目会话数量范围无效。")
        self._require_project(project_id)
        return self._threads.list_project_threads(project_id, limit=limit)

    def _require_project(self, project_id: str) -> ProjectRecord:
        """返回当前 Project 事实；解除登记后的旧身份不能再创建或枚举会话。"""
        project = self._projects.get(project_id)
        if project is None:
            raise ProjectError("project_not_found", "项目尚未登记。")
        return project
