"""从随应用发布的只读目录发现并校验内置 SKILL.md。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from mini_deer_agent.skills.contracts import BuiltInSkill, SkillResource, SkillSummary


SKILL_FILE_NAME = "SKILL.md"
DEFAULT_BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parent / "builtin"
MAX_SKILL_FILE_BYTES = 32 * 1024
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 500
MAX_TOOL_NAME_LENGTH = 128
MAX_SKILL_RESOURCE_FILES = 16
MAX_SKILL_RESOURCE_FILE_BYTES = 64 * 1024
MAX_SKILL_RESOURCE_TOTAL_BYTES = 128 * 1024
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_FRONTMATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)


def _contains_disallowed_control(value: str) -> bool:
    return any(ord(character) < 32 and character not in "\t\n\r" for character in value)


class SkillCatalogError(RuntimeError):
    """表示受信任的内置技能发布资产不完整或不合法。"""


def _validated_skill_name(value: object, *, source_file: Path) -> str:
    """校验技能名，确保它可安全用于 slash 命令和 Prompt 标识。"""
    if not isinstance(value, str):
        raise SkillCatalogError(f"Skill name in {source_file} must be a string")
    name = value.strip()
    if (
        not name
        or len(name) > MAX_SKILL_NAME_LENGTH
        or _SKILL_NAME_PATTERN.fullmatch(name) is None
    ):
        raise SkillCatalogError(
            f"Skill name in {source_file} must be lowercase hyphen-case and at most "
            f"{MAX_SKILL_NAME_LENGTH} characters"
        )
    return name


def _validated_description(value: object, *, source_file: Path) -> str:
    """校验只会进入基础 Prompt 的有界技能描述。"""
    if not isinstance(value, str):
        raise SkillCatalogError(
            f"Skill description in {source_file} must be a string"
        )
    description = value.strip()
    if not description or len(description) > MAX_SKILL_DESCRIPTION_LENGTH:
        raise SkillCatalogError(
            f"Skill description in {source_file} must contain 1-"
            f"{MAX_SKILL_DESCRIPTION_LENGTH} characters"
        )
    return description


def _validated_allowed_tools(
    metadata: dict[object, object],
    *,
    source_file: Path,
) -> tuple[str, ...] | None:
    """解析可选工具白名单，并保留“省略”与“显式空列表”的差异。"""
    if "allowed-tools" not in metadata:
        return None
    value = metadata["allowed-tools"]
    if not isinstance(value, list):
        raise SkillCatalogError(
            f"allowed-tools in {source_file} must be a list"
        )

    allowed_tools: list[str] = []
    seen_names: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise SkillCatalogError(
                f"allowed-tools in {source_file} must contain strings"
            )
        name = item.strip()
        if not name:
            raise SkillCatalogError(
                f"allowed-tools in {source_file} must not be blank"
            )
        if (
            len(name) > MAX_TOOL_NAME_LENGTH
            or _TOOL_NAME_PATTERN.fullmatch(name) is None
        ):
            raise SkillCatalogError(
                f"invalid tool name in allowed-tools for {source_file}: {name!r}"
            )
        if name in seen_names:
            raise SkillCatalogError(
                f"duplicate allowed tool in {source_file}: {name}"
            )
        seen_names.add(name)
        allowed_tools.append(name)
    return tuple(allowed_tools)


def _load_skill_resources(skill_dir: Path) -> tuple[SkillResource, ...]:
    """读取 references 下的 UTF-8 普通文件，并拒绝链接、越界和过大资源。"""
    resources_root = skill_dir / "references"
    if not resources_root.exists():
        return ()
    if not resources_root.is_dir() or resources_root.is_symlink():
        raise SkillCatalogError(
            f"Skill references must be a real directory: {resources_root}"
        )
    resolved_root = resources_root.resolve()
    files = sorted(resources_root.rglob("*"), key=lambda path: path.as_posix())
    resources: list[SkillResource] = []
    total_bytes = 0
    for path in files:
        if path.is_symlink():
            raise SkillCatalogError(f"Skill resource must not be a symbolic link: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SkillCatalogError(f"Skill resource must be a regular file: {path}")
        if len(resources) >= MAX_SKILL_RESOURCE_FILES:
            raise SkillCatalogError(
                f"Skill resources exceed {MAX_SKILL_RESOURCE_FILES} files: {skill_dir}"
            )
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise SkillCatalogError(f"Skill resource escaped package: {path}") from exc
        size = resolved.stat().st_size
        if size > MAX_SKILL_RESOURCE_FILE_BYTES:
            raise SkillCatalogError(
                f"Skill resource exceeds {MAX_SKILL_RESOURCE_FILE_BYTES} bytes: {path}"
            )
        total_bytes += size
        if total_bytes > MAX_SKILL_RESOURCE_TOTAL_BYTES:
            raise SkillCatalogError(
                f"Skill resources exceed {MAX_SKILL_RESOURCE_TOTAL_BYTES} bytes: {skill_dir}"
            )
        try:
            # Windows PowerShell 5.1 的 UTF-8 输出通常带 BOM；utf-8-sig
            # 同时兼容有 BOM 和无 BOM 文件，并继续严格拒绝非 UTF-8 字节。
            content = resolved.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise SkillCatalogError(f"Cannot read UTF-8 skill resource: {path}") from exc
        if _contains_disallowed_control(content):
            raise SkillCatalogError(
                f"Skill resource contains disallowed control characters: {path}"
            )
        resources.append(
            SkillResource(
                path=f"references/{relative.as_posix()}",
                content=content,
            )
        )
    return tuple(resources)


def load_skill_package(
    skill_dir: Path,
    *,
    source: Literal["builtin", "user", "market"] = "user",
) -> BuiltInSkill:
    """校验并读取单个真实目录中的技能包。"""
    if not skill_dir.exists() or not skill_dir.is_dir() or skill_dir.is_symlink():
        raise SkillCatalogError(f"Skill package must be a real directory: {skill_dir}")
    directory_name = _validated_skill_name(
        skill_dir.name,
        source_file=skill_dir / SKILL_FILE_NAME,
    )
    skill_file = skill_dir / SKILL_FILE_NAME
    if not skill_file.exists() or not skill_file.is_file() or skill_file.is_symlink():
        raise SkillCatalogError(f"Skill package requires a real SKILL.md: {skill_file}")
    return _parse_skill_file(
        skill_file.resolve(),
        directory_name=directory_name,
        source=source,
        resources=_load_skill_resources(skill_dir),
    )


def _parse_skill_file(
    skill_file: Path,
    *,
    directory_name: str,
    source: Literal["builtin", "user", "market"] = "builtin",
    resources: tuple[SkillResource, ...] = (),
) -> BuiltInSkill:
    """解析一个经过路径收敛的内置技能文件，非法发布资产直接失败。"""
    try:
        # 接受 Windows 常见的 UTF-8 BOM，避免隐藏的 U+FEFF 破坏首行
        # frontmatter 标记；无 BOM 的标准 UTF-8 读取行为保持不变。
        content = skill_file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise SkillCatalogError(f"Cannot read built-in skill file: {skill_file}") from exc

    if _contains_disallowed_control(content):
        raise SkillCatalogError(
            f"Skill file contains disallowed control characters: {skill_file}"
        )

    if len(content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
        raise SkillCatalogError(
            f"Built-in skill file exceeds {MAX_SKILL_FILE_BYTES} bytes: {skill_file}"
        )
    match = _FRONTMATTER_PATTERN.match(content)
    if match is None:
        raise SkillCatalogError(
            f"Built-in skill file must start with YAML frontmatter: {skill_file}"
        )
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise SkillCatalogError(
            f"Invalid YAML frontmatter in built-in skill: {skill_file}"
        ) from exc
    if not isinstance(metadata, dict):
        raise SkillCatalogError(
            f"Built-in skill frontmatter must be a mapping: {skill_file}"
        )
    unknown_fields = set(metadata) - {"name", "description", "allowed-tools"}
    if unknown_fields:
        raise SkillCatalogError(
            "Unknown skill frontmatter field(s) in "
            f"{skill_file}: {', '.join(sorted(map(str, unknown_fields)))}"
        )

    name = _validated_skill_name(metadata.get("name"), source_file=skill_file)
    if name != directory_name:
        raise SkillCatalogError(
            f"Skill frontmatter name {name!r} must match directory {directory_name!r}"
        )
    description = _validated_description(
        metadata.get("description"),
        source_file=skill_file,
    )
    allowed_tools = _validated_allowed_tools(
        metadata,
        source_file=skill_file,
    )
    instructions = content[match.end() :].strip()
    if not instructions:
        raise SkillCatalogError(
            f"Built-in skill instructions must not be empty: {skill_file}"
        )
    return BuiltInSkill(
        name=name,
        description=description,
        instructions=instructions,
        source_file=skill_file,
        allowed_tools=allowed_tools,
        resources=resources,
        source=source,
    )


@dataclass(frozen=True, slots=True)
class BuiltInSkillCatalog:
    """保存一次产品 Run 使用的稳定内置技能快照。"""

    skills: tuple[BuiltInSkill, ...]

    @classmethod
    def discover(
        cls,
        root: Path | None = None,
    ) -> BuiltInSkillCatalog:
        """扫描直接子目录中的 SKILL.md，并拒绝符号链接和越界路径。"""
        configured_root = root or DEFAULT_BUILTIN_SKILLS_ROOT
        if not configured_root.exists() or not configured_root.is_dir():
            raise SkillCatalogError(
                f"Built-in skills root does not exist: {configured_root}"
            )
        if configured_root.is_symlink():
            raise SkillCatalogError(
                f"Built-in skills root must not be a symbolic link: {configured_root}"
            )
        resolved_root = configured_root.resolve()
        discovered: list[BuiltInSkill] = []
        seen_names: set[str] = set()

        for skill_dir in sorted(configured_root.iterdir(), key=lambda path: path.name):
            if skill_dir.name.startswith(".") or not skill_dir.is_dir():
                continue
            if skill_dir.is_symlink():
                raise SkillCatalogError(
                    f"Built-in skill directory must not be a symbolic link: {skill_dir}"
                )
            # 目录名也必须先校验，不能只相信 frontmatter 中的名称。
            directory_name = _validated_skill_name(
                skill_dir.name,
                source_file=skill_dir / SKILL_FILE_NAME,
            )
            skill_file = skill_dir / SKILL_FILE_NAME
            if not skill_file.exists():
                continue
            if skill_file.is_symlink():
                raise SkillCatalogError(
                    f"Built-in SKILL.md must not be a symbolic link: {skill_file}"
                )
            resolved_file = skill_file.resolve()
            try:
                resolved_file.relative_to(resolved_root)
            except ValueError as exc:
                raise SkillCatalogError(
                    f"Built-in skill escaped the configured root: {skill_file}"
                ) from exc

            skill = _parse_skill_file(
                resolved_file,
                directory_name=directory_name,
                resources=_load_skill_resources(skill_dir),
            )
            if skill.name in seen_names:
                raise SkillCatalogError(
                    f"Duplicate built-in skill name: {skill.name}"
                )
            seen_names.add(skill.name)
            discovered.append(skill)

        discovered.sort(key=lambda skill: skill.name)
        return cls(skills=tuple(discovered))

    @property
    def summaries(self) -> tuple[SkillSummary, ...]:
        """返回只含名称与描述的稳定发现目录。"""
        return tuple(skill.summary for skill in self.skills)

    def get(self, name: str) -> BuiltInSkill | None:
        """按严格名称查找当前 Run 快照中的技能。"""
        return next((skill for skill in self.skills if skill.name == name), None)
