"""从随应用发布的只读目录发现并校验内置 SKILL.md。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from mini_deer_agent.skills.contracts import BuiltInSkill, SkillSummary


SKILL_FILE_NAME = "SKILL.md"
DEFAULT_BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parent / "builtin"
MAX_SKILL_FILE_BYTES = 32 * 1024
MAX_SKILL_NAME_LENGTH = 64
MAX_SKILL_DESCRIPTION_LENGTH = 500
MAX_TOOL_NAME_LENGTH = 128
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOOL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_FRONTMATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)


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


def _parse_skill_file(skill_file: Path, *, directory_name: str) -> BuiltInSkill:
    """解析一个经过路径收敛的内置技能文件，非法发布资产直接失败。"""
    try:
        content = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SkillCatalogError(f"Cannot read built-in skill file: {skill_file}") from exc

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
