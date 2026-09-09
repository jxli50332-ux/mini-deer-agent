"""管理本地安装、显式启停且只读加载的用户技能包。"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from mini_deer_agent.skills.catalog import (
    DEFAULT_BUILTIN_SKILLS_ROOT,
    BuiltInSkillCatalog,
    SkillCatalogError,
    load_skill_package,
)
from mini_deer_agent.skills.contracts import BuiltInSkill


_STATE_FILE_NAME = ".skill-state.json"
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class UserSkillRecord:
    """面向应用层的已安装用户技能状态。"""

    name: str
    description: str
    enabled: bool
    allowed_tools: tuple[str, ...] | None
    resource_paths: tuple[str, ...]


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
    def _state_path(self) -> Path:
        return self._root / _STATE_FILE_NAME

    def _read_enabled(self) -> set[str]:
        if not self._state_path.exists():
            return set()
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCatalogError("Invalid user skill state file") from exc
        names = payload.get("enabled") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or not isinstance(names, list)
        ):
            raise SkillCatalogError("Invalid user skill state file")
        if any(not isinstance(name, str) or not name for name in names):
            raise SkillCatalogError("Invalid user skill state file")
        return set(names)

    def _write_enabled(self, enabled: set[str]) -> None:
        temporary = self._root / f".{_STATE_FILE_NAME}.{uuid4().hex}.tmp"
        try:
            temporary.write_text(
                json.dumps(
                    {"version": 1, "enabled": sorted(enabled)},
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

    def _installed_skills(self) -> tuple[BuiltInSkill, ...]:
        skills: list[BuiltInSkill] = []
        for path in sorted(self._root.iterdir(), key=lambda item: item.name):
            if path.name.startswith(".") or not path.is_dir():
                continue
            skills.append(load_skill_package(path, source="user"))
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

    def install(self, source_path: Path, *, enabled: bool = True) -> UserSkillRecord:
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
            destination_installed = False
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
                enabled_names = self._read_enabled()
                if enabled:
                    enabled_names.add(skill.name)
                else:
                    enabled_names.discard(skill.name)
                self._write_enabled(enabled_names)
            except Exception:
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

    def catalog(self) -> BuiltInSkillCatalog:
        """合并内置技能与当前启用用户技能，名称冲突时失败关闭。"""
        with self._lock:
            builtins = BuiltInSkillCatalog.discover(self._builtin_root).skills
            enabled = self._read_enabled()
            users = tuple(
                skill for skill in self._installed_skills() if skill.name in enabled
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


__all__ = ["UserSkillManager", "UserSkillRecord"]
