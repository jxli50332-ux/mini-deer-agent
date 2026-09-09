"""管理本地安装、显式启停且只读加载的用户技能包。"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4

from mini_deer_agent.skills.catalog import (
    DEFAULT_BUILTIN_SKILLS_ROOT,
    BuiltInSkillCatalog,
    SkillCatalogError,
    load_skill_package,
)
from mini_deer_agent.skills.contracts import BuiltInSkill


_STATE_FILE_NAME = ".skill-state.json"
_MARKET_FILE_NAME = ".market-origins.json"
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class UserSkillRecord:
    """面向应用层的已安装用户技能状态。"""

    name: str
    description: str
    enabled: bool
    allowed_tools: tuple[str, ...] | None
    resource_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ManagedSkillRecord:
    """设置中心使用的统一 Skill 清单项，不暴露正文或宿主路径。"""

    name: str
    description: str
    source: Literal["builtin", "user", "market"]
    enabled: bool
    editable: bool
    allowed_tools: tuple[str, ...] | None
    resource_paths: tuple[str, ...]
    modified_at: str
    check_status: Literal["valid"] = "valid"


@dataclass(frozen=True, slots=True)
class SkillState:
    """持久化启停状态与并发更新 revision。"""

    enabled_users: frozenset[str]
    disabled_builtins: frozenset[str]
    revision: int


class UserSkillManager:
    """在受管目录中原子安装技能，并为每个 Run 生成稳定目录快照。"""

    def __init__(
        self,
        root: Path,
        *,
        builtin_root: Path = DEFAULT_BUILTIN_SKILLS_ROOT,
    ) -> None:
        self._root = root.resolve()
        self._builtin_root = builtin_root.resolve()
        self._lock = Lock()
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink() or not self._root.is_dir():
            raise SkillCatalogError(
                f"User skills root must be a real directory: {self._root}"
            )

    @property
    def root(self) -> Path:
        return self._root

    @property
    def builtin_root(self) -> Path:
        return self._builtin_root

    @property
    def _state_path(self) -> Path:
        return self._root / _STATE_FILE_NAME

    @property
    def _market_path(self) -> Path:
        return self._root / _MARKET_FILE_NAME

    def _read_market_origins(self) -> dict[str, dict[str, str]]:
        if not self._market_path.exists():
            return {}
        try:
            payload = json.loads(self._market_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCatalogError("Invalid market skill origin file") from exc
        origins = payload.get("origins") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(origins, dict):
            raise SkillCatalogError("Invalid market skill origin file")
        return {
            str(name): {str(key): str(value) for key, value in item.items()}
            for name, item in origins.items()
            if isinstance(name, str) and isinstance(item, dict)
        }

    def _write_market_origins(self, origins: dict[str, dict[str, str]]) -> None:
        temporary = self._root / f".{_MARKET_FILE_NAME}.{uuid4().hex}.tmp"
        temporary.write_text(
            json.dumps({"version": 1, "origins": origins}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self._market_path)

    def mark_market(self, name: str, metadata: dict[str, str]) -> None:
        """把已完整校验的包标记为只读市场安装。"""
        with self._lock:
            load_skill_package(self._root / name, source="market")
            origins = self._read_market_origins()
            origins[name] = dict(metadata)
            self._write_market_origins(origins)

    def market_origin(self, name: str) -> dict[str, str] | None:
        """返回市场来源的安全副本，供更新身份校验使用。"""
        with self._lock:
            origin = self._read_market_origins().get(name)
            return dict(origin) if origin is not None else None

    def _read_state(self) -> SkillState:
        if not self._state_path.exists():
            return SkillState(frozenset(), frozenset(), 0)
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCatalogError("Invalid user skill state file") from exc
        if not isinstance(payload, dict):
            raise SkillCatalogError("Invalid user skill state file")
        version = payload.get("version")
        if version == 1:
            enabled = payload.get("enabled")
            if not isinstance(enabled, list):
                raise SkillCatalogError("Invalid user skill state file")
            disabled_builtins: list[object] = []
            revision = 0
        elif version == 2:
            enabled = payload.get("enabled_users")
            disabled_builtins = payload.get("disabled_builtins")
            revision = payload.get("revision")
            if (
                not isinstance(enabled, list)
                or not isinstance(disabled_builtins, list)
                or not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision < 0
            ):
                raise SkillCatalogError("Invalid user skill state file")
        else:
            raise SkillCatalogError("Invalid user skill state file")
        if any(not isinstance(name, str) or not name for name in enabled):
            raise SkillCatalogError("Invalid user skill state file")
        if any(
            not isinstance(name, str) or not name for name in disabled_builtins
        ):
            raise SkillCatalogError("Invalid user skill state file")
        return SkillState(
            enabled_users=frozenset(enabled),
            disabled_builtins=frozenset(disabled_builtins),
            revision=revision,
        )

    def _read_enabled(self) -> set[str]:
        """兼容已有调用点，返回可变的用户 Skill 启用集合。"""
        return set(self._read_state().enabled_users)

    def _write_state(
        self,
        *,
        enabled_users: set[str],
        disabled_builtins: set[str],
        revision: int,
    ) -> None:
        temporary = self._root / f".{_STATE_FILE_NAME}.{uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "revision": revision,
                        "enabled_users": sorted(enabled_users),
                        "disabled_builtins": sorted(disabled_builtins),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self._state_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _write_enabled(self, enabled: set[str]) -> None:
        state = self._read_state()
        self._write_state(
            enabled_users=enabled,
            disabled_builtins=set(state.disabled_builtins),
            revision=state.revision + 1,
        )

    @property
    def revision(self) -> int:
        with self._lock:
            return self._read_state().revision

    def _installed_skills(self) -> tuple[BuiltInSkill, ...]:
        skills: list[BuiltInSkill] = []
        market_names = set(self._read_market_origins())
        for path in sorted(self._root.iterdir(), key=lambda item: item.name):
            if path.name.startswith(".") or not path.is_dir():
                continue
            skills.append(
                load_skill_package(
                    path,
                    source="market" if path.name in market_names else "user",
                )
            )
        return tuple(skills)

    def list(self) -> tuple[UserSkillRecord, ...]:
        """列出安装状态；正文和宿主路径不会进入响应。"""
        with self._lock:
            enabled = self._read_enabled()
            skills = self._installed_skills()
        return tuple(
            UserSkillRecord(
                name=skill.name,
                description=skill.description,
                enabled=skill.name in enabled,
                allowed_tools=skill.allowed_tools,
                resource_paths=tuple(resource.path for resource in skill.resources),
            )
            for skill in skills
        )

    def list_all(self) -> tuple[ManagedSkillRecord, ...]:
        """统一列出内置与用户 Skill，供应用级设置页面只读展示。"""
        with self._lock:
            builtins = BuiltInSkillCatalog.discover(self._builtin_root).skills
            state = self._read_state()
            users = self._installed_skills()

        def project(skill: BuiltInSkill, *, enabled: bool) -> ManagedSkillRecord:
            modified_at = datetime.fromtimestamp(
                skill.source_file.stat().st_mtime,
                tz=UTC,
            ).isoformat()
            return ManagedSkillRecord(
                name=skill.name,
                description=skill.description,
                source=skill.source,
                enabled=enabled,
                editable=skill.source == "user",
                allowed_tools=skill.allowed_tools,
                resource_paths=tuple(resource.path for resource in skill.resources),
                modified_at=modified_at,
            )

        records = [
            project(skill, enabled=skill.name not in state.disabled_builtins)
            for skill in builtins
        ]
        records.extend(
            project(skill, enabled=skill.name in state.enabled_users) for skill in users
        )
        return tuple(sorted(records, key=lambda record: (record.name, record.source)))

    def install(
        self,
        source_path: Path,
        *,
        enabled: bool = True,
        market_origin: dict[str, str] | None = None,
        expected_revision: int | None = None,
    ) -> UserSkillRecord:
        """从用户明确给出的本地目录复制已校验的 SKILL.md 与 references。"""
        source = source_path.resolve(strict=True)
        skill = load_skill_package(source, source="user")
        builtin_names = {
            summary.name
            for summary in BuiltInSkillCatalog.discover(self._builtin_root).summaries
        }
        if skill.name in builtin_names:
            raise SkillCatalogError(
                f"User skill conflicts with built-in skill: {skill.name}"
            )
        destination = self._root / skill.name
        temporary = self._root / f".install-{skill.name}-{uuid4().hex}"
        staged = temporary / skill.name
        with self._lock:
            if destination.exists():
                raise SkillCatalogError(f"User skill is already installed: {skill.name}")
            state = self._read_state()
            if expected_revision is not None and expected_revision != state.revision:
                raise SkillCatalogError(
                    f"Skill settings revision conflict: expected {expected_revision}, "
                    f"current {state.revision}"
                )
            origins = self._read_market_origins()
            destination_installed = False
            state_written = False
            try:
                staged.mkdir(parents=True)
                shutil.copy2(source / "SKILL.md", staged / "SKILL.md")
                if (source / "references").exists():
                    shutil.copytree(
                        source / "references",
                        staged / "references",
                    )
                installed = load_skill_package(staged, source="user")
                if installed.name != skill.name:
                    raise SkillCatalogError("Installed skill identity changed during copy")
                os.replace(staged, destination)
                destination_installed = True
                temporary.rmdir()
                enabled_names = set(state.enabled_users)
                if enabled:
                    enabled_names.add(skill.name)
                else:
                    enabled_names.discard(skill.name)
                self._write_state(
                    enabled_users=enabled_names,
                    disabled_builtins=set(state.disabled_builtins),
                    revision=state.revision + 1,
                )
                state_written = True
                if market_origin is not None:
                    origins[skill.name] = dict(market_origin)
                    self._write_market_origins(origins)
            except Exception:
                if state_written:
                    self._write_state(
                        enabled_users=set(state.enabled_users),
                        disabled_builtins=set(state.disabled_builtins),
                        revision=state.revision,
                    )
                if temporary.exists():
                    shutil.rmtree(temporary)
                if destination_installed and destination.exists():
                    shutil.rmtree(destination)
                raise
        return next(record for record in self.list() if record.name == skill.name)

    def set_enabled(self, name: str, enabled: bool) -> UserSkillRecord:
        """切换一个已安装且仍能通过校验的技能，只影响之后开始的 Run。"""
        if _SKILL_NAME_PATTERN.fullmatch(name) is None:
            raise SkillCatalogError(f"Invalid user skill name: {name!r}")
        destination = self._root / name
        with self._lock:
            skill = load_skill_package(destination, source="user")
            if skill.name != name:
                raise SkillCatalogError("User skill identity does not match requested name")
            enabled_names = self._read_enabled()
            if enabled:
                enabled_names.add(name)
            else:
                enabled_names.discard(name)
            self._write_enabled(enabled_names)
        return next(record for record in self.list() if record.name == name)

    def set_managed_enabled(
        self,
        name: str,
        enabled: bool,
        *,
        expected_revision: int | None = None,
    ) -> ManagedSkillRecord:
        """启停内置或用户 Skill，并用 revision 拒绝陈旧设置页面。"""
        if _SKILL_NAME_PATTERN.fullmatch(name) is None:
            raise SkillCatalogError(f"Invalid skill name: {name!r}")
        with self._lock:
            state = self._read_state()
            if expected_revision is not None and expected_revision != state.revision:
                raise SkillCatalogError(
                    f"Skill settings revision conflict: expected {expected_revision}, "
                    f"current {state.revision}"
                )
            enabled_users = set(state.enabled_users)
            disabled_builtins = set(state.disabled_builtins)
            builtin_names = {
                skill.name
                for skill in BuiltInSkillCatalog.discover(self._builtin_root).skills
            }
            if name in builtin_names:
                if enabled:
                    disabled_builtins.discard(name)
                else:
                    disabled_builtins.add(name)
            else:
                skill = load_skill_package(self._root / name, source="user")
                if skill.name != name:
                    raise SkillCatalogError(
                        "User skill identity does not match requested name"
                    )
                if enabled:
                    enabled_users.add(name)
                else:
                    enabled_users.discard(name)
            self._write_state(
                enabled_users=enabled_users,
                disabled_builtins=disabled_builtins,
                revision=state.revision + 1,
            )
        return next(record for record in self.list_all() if record.name == name)

    def replace(
        self,
        source_path: Path,
        *,
        enabled: bool | None = None,
        market_origin: dict[str, str] | None = None,
        expected_revision: int | None = None,
    ) -> UserSkillRecord:
        """完整校验新包后原子替换同名用户 Skill。"""
        source = source_path.resolve(strict=True)
        skill = load_skill_package(source, source="user")
        destination = self._root / skill.name
        temporary = self._root / f".replace-{skill.name}-{uuid4().hex}"
        staged = temporary / skill.name
        backup = temporary / "previous"
        with self._lock:
            if not destination.exists():
                raise SkillCatalogError(f"User skill is not installed: {skill.name}")
            staged.mkdir(parents=True)
            committed = False
            state_written = False
            state = self._read_state()
            if expected_revision is not None and expected_revision != state.revision:
                raise SkillCatalogError(
                    f"Skill settings revision conflict: expected {expected_revision}, "
                    f"current {state.revision}"
                )
            origins = self._read_market_origins()
            try:
                shutil.copy2(source / "SKILL.md", staged / "SKILL.md")
                if (source / "references").exists():
                    shutil.copytree(source / "references", staged / "references")
                installed = load_skill_package(staged, source="user")
                if installed.name != skill.name:
                    raise SkillCatalogError(
                        "Installed skill identity changed during replacement"
                    )
                os.replace(destination, backup)
                try:
                    os.replace(staged, destination)
                except Exception:
                    os.replace(backup, destination)
                    raise
                enabled_names = set(state.enabled_users)
                if enabled is True:
                    enabled_names.add(skill.name)
                elif enabled is False:
                    enabled_names.discard(skill.name)
                self._write_state(
                    enabled_users=enabled_names,
                    disabled_builtins=set(state.disabled_builtins),
                    revision=state.revision + 1,
                )
                state_written = True
                if market_origin is not None:
                    origins[skill.name] = dict(market_origin)
                    self._write_market_origins(origins)
                committed = True
            except Exception:
                if state_written:
                    self._write_state(
                        enabled_users=set(state.enabled_users),
                        disabled_builtins=set(state.disabled_builtins),
                        revision=state.revision,
                    )
                if backup.exists():
                    if destination.exists():
                        shutil.rmtree(destination)
                    os.replace(backup, destination)
                if temporary.exists():
                    shutil.rmtree(temporary)
                raise
            if committed:
                # 文件与状态已提交后，清理失败不能再回滚目录，否则会让新状态
                # 指向旧内容。残留只会是点号开头的不可发现备份，可在下次清理。
                shutil.rmtree(temporary, ignore_errors=True)
        return next(record for record in self.list() if record.name == skill.name)

    def delete(
        self,
        name: str,
        *,
        expected_revision: int | None = None,
    ) -> None:
        """删除用户 Skill；内置 Skill 永远不能经此入口删除。"""
        if _SKILL_NAME_PATTERN.fullmatch(name) is None:
            raise SkillCatalogError(f"Invalid user skill name: {name!r}")
        destination = self._root / name
        with self._lock:
            state = self._read_state()
            if expected_revision is not None and expected_revision != state.revision:
                raise SkillCatalogError(
                    f"Skill settings revision conflict: expected {expected_revision}, "
                    f"current {state.revision}"
                )
            skill = load_skill_package(destination, source="user")
            if skill.name != name:
                raise SkillCatalogError("User skill identity does not match requested name")
            tombstone = self._root / f".delete-{name}-{uuid4().hex}"
            os.replace(destination, tombstone)
            state_written = False
            try:
                enabled_names = set(state.enabled_users)
                enabled_names.discard(name)
                self._write_state(
                    enabled_users=enabled_names,
                    disabled_builtins=set(state.disabled_builtins),
                    revision=state.revision + 1,
                )
                state_written = True
                origins = self._read_market_origins()
                if name in origins:
                    origins.pop(name)
                    self._write_market_origins(origins)
            except Exception:
                if state_written:
                    self._write_state(
                        enabled_users=set(state.enabled_users),
                        disabled_builtins=set(state.disabled_builtins),
                        revision=state.revision,
                    )
                os.replace(tombstone, destination)
                raise
            shutil.rmtree(tombstone)

    def catalog(self) -> BuiltInSkillCatalog:
        """合并内置技能与当前启用用户技能，名称冲突时失败关闭。"""
        with self._lock:
            state = self._read_state()
            builtins = tuple(
                skill
                for skill in BuiltInSkillCatalog.discover(self._builtin_root).skills
                if skill.name not in state.disabled_builtins
            )
            users = tuple(
                skill
                for skill in self._installed_skills()
                if skill.name in state.enabled_users
            )
        builtin_names = {skill.name for skill in builtins}
        conflicts = sorted(skill.name for skill in users if skill.name in builtin_names)
        if conflicts:
            raise SkillCatalogError(
                "User skill conflicts with built-in skill: " + ", ".join(conflicts)
            )
        return BuiltInSkillCatalog(
            skills=tuple(sorted((*builtins, *users), key=lambda skill: skill.name))
        )


__all__ = [
    "ManagedSkillRecord",
    "SkillState",
    "UserSkillManager",
    "UserSkillRecord",
]
