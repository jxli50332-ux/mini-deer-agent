"""Skill 草稿、归档导入、详情、历史与回滚应用服务。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import zipfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Literal
from uuid import uuid4

import yaml

from mini_deer_agent.skills.catalog import (
    BuiltInSkillCatalog,
    SkillCatalogError,
    load_skill_package,
)
from mini_deer_agent.skills.contracts import BuiltInSkill
from mini_deer_agent.skills.user import UserSkillManager


MAX_ARCHIVE_BYTES = 256 * 1024
MAX_ARCHIVE_FILES = 18
_AUTHORIZATION_TTL = timedelta(minutes=30)
_MAX_PENDING_AUTHORIZATIONS = 32
_AUTHORIZED_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_WINDOWS_RESERVED_NAMES = {
    "aux", "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "con", "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
    "nul", "prn",
}
_UNSAFE_PATH_CHARACTERS = frozenset('<>:"|?*')
_CONTENT_RISK_PATTERNS = (
    (re.compile(r"(?i)ignore\s+(?:all\s+)?(?:previous\s+)?(?:system\s+)?instructions"), "包含尝试覆盖系统指令的文本"),
    (re.compile(r"(?i)(?:api[-_ ]?key|password|secret|token).{0,80}(?:send|upload|post|exfiltrat)"), "包含可能外传敏感信息的指令"),
    (re.compile(r"(?i)(?:rm\s+-rf|format\s+[a-z]:|remove-item\s+.+-recurse)"), "包含高风险破坏性命令文本"),
)


@dataclass(frozen=True, slots=True)
class SkillDraftPayload:
    name: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...] | None = None
    resources: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class SkillDraftRecord:
    draft_id: str
    revision: int
    payload: SkillDraftPayload
    author: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class SkillCheckResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    content_hash: str | None


@dataclass(frozen=True, slots=True)
class SkillArchiveInspection:
    name: str
    description: str
    instructions: str
    allowed_tools: tuple[str, ...] | None
    resources: tuple[tuple[str, str], ...]
    content_hash: str
    risk_warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillInstallAuthorization:
    token: str
    thread_id: str
    expected_name: str
    requirement_hash: str
    created_at: str
    expires_at: str
    run_id: str | None = None
    draft_id: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True, slots=True)
class SkillAgentSettings:
    creation_enabled: bool
    revision: int


@dataclass(frozen=True, slots=True)
class SkillDetailRecord:
    name: str
    description: str
    source: Literal["builtin", "user", "market"]
    editable: bool
    enabled: bool
    allowed_tools: tuple[str, ...] | None
    instructions: str
    resources: tuple[tuple[str, str], ...]
    revision: int


@dataclass(frozen=True, slots=True)
class SkillHistoryRecord:
    history_id: str
    skill_name: str
    action: Literal["install", "update", "delete", "rollback", "import"]
    author: str
    created_at: str
    description: str
    allowed_tools: tuple[str, ...] | None
    version: str | None = None
    market_origin: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class RecoverableSkillRecord:
    name: str
    history_id: str
    description: str
    source: Literal["user", "market"]
    version: str | None
    deleted_at: str


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _validated_managed_name(value: object) -> str:
    if not isinstance(value, str):
        raise SkillCatalogError("Skill name must be a string")
    name = value.strip()
    if (
        not name
        or len(name) > 64
        or _AUTHORIZED_NAME_PATTERN.fullmatch(name) is None
    ):
        raise SkillCatalogError(
            "Skill name must be lowercase hyphen-case and at most 64 characters"
        )
    return name


def _validate_portable_path(path: PurePosixPath) -> None:
    for part in path.parts:
        if (
            not part
            or part.endswith((" ", "."))
            or any(character in _UNSAFE_PATH_CHARACTERS for character in part)
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        ):
            raise SkillCatalogError(
                f"Skill archive contains a non-portable path: {path.as_posix()}"
            )


def _content_risk_warnings(skill: BuiltInSkill) -> tuple[str, ...]:
    content = "\n".join(
        [skill.instructions, *(resource.content for resource in skill.resources)]
    )
    return tuple(message for pattern, message in _CONTENT_RISK_PATTERNS if pattern.search(content))


class SkillManagementService:
    """只在 UserSkillManager 受管根目录内执行确定性 Skill 变更。"""

    def __init__(self, manager: UserSkillManager) -> None:
        self.manager = manager
        self._drafts_root = manager.root / ".drafts"
        self._history_root = manager.root / ".history"
        self._work_root = manager.root / ".management-work"
        self._settings_path = manager.root / ".skill-management-settings.json"
        self._lock = Lock()
        self._authorizations: dict[str, SkillInstallAuthorization] = {}
        self._drafts_root.mkdir(exist_ok=True)
        self._history_root.mkdir(exist_ok=True)
        self._work_root.mkdir(exist_ok=True)

    def agent_settings(self) -> SkillAgentSettings:
        if not self._settings_path.exists():
            return SkillAgentSettings(True, 0)
        try:
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCatalogError("Invalid Skill Agent settings") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or not isinstance(payload.get("creation_enabled"), bool)
            or not isinstance(payload.get("revision"), int)
            or isinstance(payload.get("revision"), bool)
            or payload["revision"] < 0
        ):
            raise SkillCatalogError("Invalid Skill Agent settings")
        return SkillAgentSettings(payload["creation_enabled"], payload["revision"])

    def update_agent_settings(
        self,
        *,
        creation_enabled: bool,
        expected_revision: int,
    ) -> SkillAgentSettings:
        with self._lock:
            current = self.agent_settings()
            if current.revision != expected_revision:
                raise SkillCatalogError(
                    f"Skill Agent settings revision conflict: expected {expected_revision}, "
                    f"current {current.revision}"
                )
            updated = SkillAgentSettings(creation_enabled, current.revision + 1)
            self._write_json_atomic(
                self._settings_path,
                {
                    "version": 1,
                    "creation_enabled": updated.creation_enabled,
                    "revision": updated.revision,
                },
            )
        return updated

    def require_agent_creation_enabled(self) -> None:
        if not self.agent_settings().creation_enabled:
            raise SkillCatalogError("Agent Skill creation is disabled in settings")

    def _draft_path(self, draft_id: str) -> Path:
        try:
            normalized = str(uuid4()) if not draft_id else str(__import__("uuid").UUID(draft_id))
        except ValueError as exc:
            raise SkillCatalogError("Invalid skill draft id") from exc
        return self._drafts_root / normalized

    def _serialize_draft(self, record: SkillDraftRecord) -> dict[str, object]:
        payload = asdict(record)
        payload["payload"]["allowed_tools"] = (
            list(record.payload.allowed_tools)
            if record.payload.allowed_tools is not None
            else None
        )
        payload["payload"]["resources"] = [
            [path, content] for path, content in record.payload.resources
        ]
        return payload

    def _write_json_atomic(self, path: Path, payload: object) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _read_draft(self, draft_id: str) -> SkillDraftRecord:
        path = self._draft_path(draft_id) / "draft.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            content = payload["payload"]
            return SkillDraftRecord(
                draft_id=payload["draft_id"],
                revision=payload["revision"],
                payload=SkillDraftPayload(
                    name=content["name"],
                    description=content["description"],
                    instructions=content["instructions"],
                    allowed_tools=(
                        tuple(content["allowed_tools"])
                        if content["allowed_tools"] is not None
                        else None
                    ),
                    resources=tuple((item[0], item[1]) for item in content["resources"]),
                ),
                author=payload["author"],
                created_at=payload["created_at"],
                updated_at=payload["updated_at"],
            )
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SkillCatalogError("Skill draft does not exist or is invalid") from exc

    def create_draft(
        self,
        payload: SkillDraftPayload,
        *,
        author: str = "user",
    ) -> SkillDraftRecord:
        draft_id = str(uuid4())
        now = _now()
        record = SkillDraftRecord(draft_id, 1, payload, author, now, now)
        with self._lock:
            draft_dir = self._draft_path(draft_id)
            draft_dir.mkdir()
            self._write_json_atomic(draft_dir / "draft.json", self._serialize_draft(record))
        return record

    def list_drafts(self) -> tuple[SkillDraftRecord, ...]:
        """列出人工与 Agent 草稿，损坏草稿失败关闭而不是静默丢失。"""
        records: list[SkillDraftRecord] = []
        with self._lock:
            for path in sorted(self._drafts_root.iterdir(), key=lambda item: item.name):
                if path.is_dir() and not path.is_symlink():
                    records.append(self._read_draft(path.name))
        return tuple(sorted(records, key=lambda item: item.updated_at, reverse=True))

    def update_draft(
        self,
        draft_id: str,
        payload: SkillDraftPayload,
        *,
        expected_revision: int,
    ) -> SkillDraftRecord:
        with self._lock:
            current = self._read_draft(draft_id)
            if current.revision != expected_revision:
                raise SkillCatalogError(
                    f"Skill draft revision conflict: expected {expected_revision}, "
                    f"current {current.revision}"
                )
            updated = SkillDraftRecord(
                current.draft_id,
                current.revision + 1,
                payload,
                current.author,
                current.created_at,
                _now(),
            )
            self._write_json_atomic(
                self._draft_path(draft_id) / "draft.json",
                self._serialize_draft(updated),
            )
        return updated

    def require_agent_draft(self, draft_id: str) -> None:
        if self._read_draft(draft_id).author != "agent":
            raise SkillCatalogError("Agent cannot modify a user-authored Skill draft")

    def _materialize(self, payload: SkillDraftPayload, root: Path) -> Path:
        name = _validated_managed_name(payload.name)
        package = root / name
        package.mkdir(parents=True)
        metadata: dict[str, object] = {
            "name": name,
            "description": payload.description,
        }
        if payload.allowed_tools is not None:
            metadata["allowed-tools"] = list(payload.allowed_tools)
        frontmatter = yaml.safe_dump(
            metadata,
            allow_unicode=True,
            sort_keys=False,
        ).rstrip()
        (package / "SKILL.md").write_text(
            f"---\n{frontmatter}\n---\n{payload.instructions.rstrip()}\n",
            encoding="utf-8",
        )
        seen_resources: set[str] = set()
        for relative_text, content in payload.resources:
            if "\\" in relative_text:
                raise SkillCatalogError("Skill resource paths must use forward slashes")
            relative = PurePosixPath(relative_text)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not relative.parts
                or relative.parts[0] != "references"
            ):
                raise SkillCatalogError(
                    f"Skill resource must stay under references/: {relative_text}"
                )
            _validate_portable_path(relative)
            normalized_resource = relative.as_posix().casefold()
            if normalized_resource in seen_resources:
                raise SkillCatalogError(
                    f"Duplicate Skill resource path: {relative_text}"
                )
            seen_resources.add(normalized_resource)
            destination = package.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        return package

    def _validated_package_for_draft(self, record: SkillDraftRecord) -> tuple[Path, BuiltInSkill]:
        work = self._work_root / f"draft-{record.draft_id}-{uuid4().hex}"
        try:
            package = self._materialize(record.payload, work)
            return work, load_skill_package(package, source="user")
        except Exception:
            if work.exists():
                shutil.rmtree(work)
            raise

    def check_draft(self, draft_id: str) -> SkillCheckResult:
        record = self._read_draft(draft_id)
        try:
            work, skill = self._validated_package_for_draft(record)
        except (OSError, SkillCatalogError, UnicodeError) as exc:
            return SkillCheckResult(False, (str(exc),), (), None)
        try:
            digest = hashlib.sha256()
            digest.update((work / skill.name / "SKILL.md").read_bytes())
            for resource in skill.resources:
                digest.update(resource.path.encode("utf-8"))
                digest.update(resource.content.encode("utf-8"))
            return SkillCheckResult(
                True,
                (),
                _content_risk_warnings(skill),
                digest.hexdigest(),
            )
        finally:
            shutil.rmtree(work)

    @staticmethod
    def _package_hash(package: Path, skill: BuiltInSkill) -> str:
        digest = hashlib.sha256()
        digest.update((package / "SKILL.md").read_bytes())
        for resource in skill.resources:
            digest.update(resource.path.encode("utf-8"))
            digest.update(resource.content.encode("utf-8"))
        return digest.hexdigest()

    def authorize_automatic_install(
        self,
        *,
        thread_id: str,
        expected_name: str,
        requirement: str,
    ) -> SkillInstallAuthorization:
        """创建只适用于当前 Thread 和一个全新名称的一次性安装授权。"""
        self.require_agent_creation_enabled()
        normalized_thread = thread_id.strip()
        normalized_name = expected_name.strip()
        normalized_requirement = requirement.strip()
        if not normalized_thread:
            raise SkillCatalogError("Automatic install authorization requires a thread id")
        if not normalized_requirement:
            raise SkillCatalogError("Automatic install authorization requires a requirement")
        if (
            not normalized_name
            or len(normalized_name) > 64
            or _AUTHORIZED_NAME_PATTERN.fullmatch(normalized_name) is None
        ):
            raise SkillCatalogError(
                "Authorized Skill name must be lowercase hyphen-case and at most 64 characters"
            )
        if any(item.name == normalized_name for item in self.manager.list_all()):
            raise SkillCatalogError(
                f"Automatic install only permits a new Skill name: {normalized_name}"
            )
        now = datetime.now(tz=UTC)
        authorization = SkillInstallAuthorization(
            token=uuid4().hex,
            thread_id=normalized_thread,
            expected_name=normalized_name,
            requirement_hash=hashlib.sha256(
                normalized_requirement.encode("utf-8")
            ).hexdigest(),
            created_at=now.isoformat(),
            expires_at=(now + _AUTHORIZATION_TTL).isoformat(),
        )
        with self._lock:
            self._authorizations = {
                token: item
                for token, item in self._authorizations.items()
                if datetime.fromisoformat(item.expires_at) > now
            }
            if len(self._authorizations) >= _MAX_PENDING_AUTHORIZATIONS:
                oldest = min(
                    self._authorizations,
                    key=lambda token: self._authorizations[token].expires_at,
                )
                self._authorizations.pop(oldest)
            self._authorizations[authorization.token] = authorization
        return authorization

    def install_authorized_draft(
        self,
        draft_id: str,
        *,
        authorization_token: str,
        thread_id: str,
        run_id: str | None,
    ) -> tuple[SkillDetailRecord, str]:
        """消费一次性授权，安装与授权名称相符的当前 Agent 草稿。"""
        with self._lock:
            authorization = self._authorizations.pop(authorization_token, None)
        if authorization is None:
            raise SkillCatalogError(
                "Automatic install authorization is missing, expired, or already used"
            )
        if datetime.fromisoformat(authorization.expires_at) <= datetime.now(tz=UTC):
            raise SkillCatalogError("Automatic install authorization has expired")
        if authorization.thread_id != thread_id:
            raise SkillCatalogError(
                "Automatic install authorization belongs to a different thread"
            )
        if authorization.run_id is None or authorization.run_id != run_id:
            raise SkillCatalogError(
                "Automatic install authorization belongs to a different run"
            )
        if authorization.draft_id is None or authorization.draft_id != draft_id:
            raise SkillCatalogError(
                "Automatic install authorization belongs to a different draft"
            )
        record = self._read_draft(draft_id)
        if record.author != "agent":
            raise SkillCatalogError("Automatic install requires an Agent-created draft")
        if record.payload.name != authorization.expected_name:
            raise SkillCatalogError(
                "Automatic install draft name does not match the authorization"
            )
        if any(item.name == record.payload.name for item in self.manager.list_all()):
            raise SkillCatalogError(
                "Automatic install cannot replace an existing Skill"
            )
        checked = self.check_draft(draft_id)
        if not checked.valid or checked.content_hash is None:
            raise SkillCatalogError(
                "Automatic install requires a valid current draft: "
                + "; ".join(checked.errors)
            )
        if (
            authorization.content_hash is None
            or authorization.content_hash != checked.content_hash
        ):
            raise SkillCatalogError(
                "Automatic install requires the exact draft content validated with this authorization"
            )
        author = (
            f"agent:auto thread={thread_id} run={run_id or 'unknown'} "
            f"requirement={authorization.requirement_hash} draft={checked.content_hash}"
        )
        detail = self.install_draft(
            draft_id,
            expected_revision=record.revision,
            enabled=True,
            author=author,
        )
        return detail, checked.content_hash

    def bind_automatic_authorization(
        self,
        authorization_token: str,
        *,
        thread_id: str,
        run_id: str,
        expected_name: str,
        draft_id: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        """在首次自动草稿写入前把授权锁定到当前产品 Run。"""
        with self._lock:
            authorization = self._authorizations.get(authorization_token)
            if authorization is None:
                raise SkillCatalogError(
                    "Automatic install authorization is missing, expired, or already used"
                )
            if datetime.fromisoformat(authorization.expires_at) <= datetime.now(tz=UTC):
                self._authorizations.pop(authorization_token, None)
                raise SkillCatalogError("Automatic install authorization has expired")
            if authorization.thread_id != thread_id:
                raise SkillCatalogError(
                    "Automatic install authorization belongs to a different thread"
                )
            if authorization.expected_name != expected_name:
                raise SkillCatalogError(
                    "Automatic install draft name does not match the authorization"
                )
            if authorization.run_id is not None and authorization.run_id != run_id:
                raise SkillCatalogError(
                    "Automatic install authorization belongs to a different run"
                )
            if (
                authorization.draft_id is not None
                and draft_id is not None
                and authorization.draft_id != draft_id
            ):
                raise SkillCatalogError(
                    "Automatic install authorization belongs to a different draft"
                )
            if content_hash is not None and draft_id is None:
                raise SkillCatalogError(
                    "Automatic install content hash requires a bound draft"
                )
            self._authorizations[authorization_token] = replace(
                authorization,
                run_id=run_id,
                draft_id=draft_id or authorization.draft_id,
                content_hash=(
                    content_hash
                    if content_hash is not None
                    else authorization.content_hash
                ),
            )

    def bind_automatic_authorization_to_run(
        self,
        authorization_token: str,
        *,
        thread_id: str,
        run_id: str,
    ) -> None:
        """把请求明确携带的一次性授权绑定到对应的产品 Run。"""
        with self._lock:
            authorization = self._authorizations.get(authorization_token)
            if authorization is None:
                raise SkillCatalogError(
                    "Automatic install authorization is missing, expired, or already used"
                )
            if datetime.fromisoformat(authorization.expires_at) <= datetime.now(tz=UTC):
                self._authorizations.pop(authorization_token, None)
                raise SkillCatalogError("Automatic install authorization has expired")
            if authorization.thread_id != thread_id:
                raise SkillCatalogError(
                    "Automatic install authorization belongs to a different thread"
                )
            if authorization.run_id is not None and authorization.run_id != run_id:
                raise SkillCatalogError(
                    "Automatic install authorization belongs to a different run"
                )
            self._authorizations[authorization_token] = replace(
                authorization,
                run_id=run_id,
            )

    def automatic_authorization_token_for_run(
        self,
        *,
        thread_id: str,
        run_id: str,
        expected_name: str,
        draft_id: str | None = None,
    ) -> str | None:
        """在服务端解析绑定当前 Run、名称及可选草稿的授权令牌。"""
        now = datetime.now(tz=UTC)
        with self._lock:
            for token, item in tuple(self._authorizations.items()):
                if datetime.fromisoformat(item.expires_at) <= now:
                    self._authorizations.pop(token)
                    continue
                if (
                    item.thread_id == thread_id
                    and item.run_id == run_id
                    and item.expected_name == expected_name
                    and (
                        draft_id is None
                        or item.draft_id is None
                        or item.draft_id == draft_id
                    )
                ):
                    return token
        return None

    def _history_index_path(self, name: str) -> Path:
        return self._history_root / _validated_managed_name(name) / "index.json"

    def _read_history(self, name: str) -> list[dict[str, object]]:
        path = self._history_index_path(name)
        if not path.exists():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SkillCatalogError("Invalid skill history index") from exc
        if not isinstance(value, list):
            raise SkillCatalogError("Invalid skill history index")
        return value

    def _record_history(
        self,
        skill: BuiltInSkill,
        *,
        source_dir: Path,
        action: Literal["install", "update", "delete", "rollback", "import"],
        author: str,
        version: str | None = None,
    ) -> SkillHistoryRecord:
        history_id = str(uuid4())
        created_at = _now()
        skill_root = self._history_root / skill.name
        snapshot = skill_root / history_id / skill.name
        skill_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, snapshot)
        record = SkillHistoryRecord(
            history_id,
            skill.name,
            action,
            author,
            created_at,
            skill.description,
            skill.allowed_tools,
            version,
            self.manager.market_origin(skill.name),
        )
        index = self._read_history(skill.name)
        index.append(
            {
                **asdict(record),
                "allowed_tools": (
                    list(record.allowed_tools)
                    if record.allowed_tools is not None
                    else None
                ),
            }
        )
        self._write_json_atomic(self._history_index_path(skill.name), index)
        return record

    def install_draft(
        self,
        draft_id: str,
        *,
        expected_revision: int,
        expected_settings_revision: int | None = None,
        enabled: bool = True,
        author: str = "user",
    ) -> SkillDetailRecord:
        record = self._read_draft(draft_id)
        if record.revision != expected_revision:
            raise SkillCatalogError(
                f"Skill draft revision conflict: expected {expected_revision}, "
                f"current {record.revision}"
            )
        work, skill = self._validated_package_for_draft(record)
        package = work / skill.name
        try:
            existing = self.manager.root / skill.name
            action: Literal["install", "update", "import"] = (
                "update"
                if existing.exists()
                else "import"
                if record.author == "user:archive-import"
                else "install"
            )
            if existing.exists():
                existing_record = next(
                    item for item in self.manager.list_all() if item.name == skill.name
                )
                if existing_record.source != "user":
                    raise SkillCatalogError(
                        f"Only user Skills can be edited: {skill.name}"
                    )
                self.manager.replace(
                    package,
                    enabled=enabled,
                    expected_revision=expected_settings_revision,
                )
            else:
                self.manager.install(
                    package,
                    enabled=enabled,
                    expected_revision=expected_settings_revision,
                )
            self._record_history(
                load_skill_package(self.manager.root / skill.name, source="user"),
                source_dir=self.manager.root / skill.name,
                action=action,
                author=author,
            )
        finally:
            shutil.rmtree(work)
        return self.get_detail(skill.name)

    def _archive_package(self, content: bytes) -> tuple[Path, BuiltInSkill]:
        if not content or len(content) > MAX_ARCHIVE_BYTES:
            raise SkillCatalogError(
                f"Skill archive must contain 1-{MAX_ARCHIVE_BYTES} bytes"
            )
        work = self._work_root / f"import-{uuid4().hex}"
        package_root = work / "package"
        package_root.mkdir(parents=True)
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                files = [item for item in archive.infolist() if not item.is_dir()]
                if len(files) > MAX_ARCHIVE_FILES:
                    raise SkillCatalogError("Skill archive contains too many files")
                if any(item.file_size > MAX_ARCHIVE_BYTES for item in files) or sum(
                    item.file_size for item in files
                ) > MAX_ARCHIVE_BYTES:
                    raise SkillCatalogError("Skill archive expands beyond the size limit")
                names: list[PurePosixPath] = []
                normalized_names: set[str] = set()
                for item in files:
                    if "\\" in item.filename:
                        raise SkillCatalogError("Skill archive paths must use forward slashes")
                    path = PurePosixPath(item.filename)
                    mode = item.external_attr >> 16
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or stat.S_ISLNK(mode)
                    ):
                        raise SkillCatalogError("Skill archive contains unsafe paths")
                    _validate_portable_path(path)
                    normalized = path.as_posix().casefold()
                    if normalized in normalized_names:
                        raise SkillCatalogError(
                            "Skill archive contains duplicate paths"
                        )
                    normalized_names.add(normalized)
                    names.append(path)
                skill_files = [path for path in names if path.name == "SKILL.md"]
                if len(skill_files) != 1:
                    raise SkillCatalogError("Skill archive must contain exactly one SKILL.md")
                skill_file = skill_files[0]
                prefix = skill_file.parts[:-1]
                if len(prefix) > 1:
                    raise SkillCatalogError("Skill archive must use a single package root")
                for item, path in zip(files, names, strict=True):
                    relative_parts = path.parts[len(prefix) :]
                    if not relative_parts:
                        continue
                    relative = PurePosixPath(*relative_parts)
                    if relative.as_posix() != "SKILL.md" and (
                        not relative.parts or relative.parts[0] != "references"
                    ):
                        raise SkillCatalogError(
                            f"Unsupported file in Skill archive: {relative.as_posix()}"
                        )
                    destination = package_root.joinpath(*relative.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    payload = archive.read(item)
                    try:
                        payload.decode("utf-8-sig")
                    except UnicodeError as exc:
                        raise SkillCatalogError(
                            f"Skill archive file must be UTF-8 text: {relative.as_posix()}"
                        ) from exc
                    destination.write_bytes(payload)
            metadata = yaml.safe_load(
                (package_root / "SKILL.md").read_text(encoding="utf-8-sig").split("---", 2)[1]
            )
            if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
                raise SkillCatalogError("Skill archive has invalid frontmatter")
            name = _validated_managed_name(metadata["name"])
            named_package = work / name
            os.replace(package_root, named_package)
            skill = load_skill_package(named_package, source="user")
            return work, skill
        except Exception:
            if work.exists():
                shutil.rmtree(work)
            raise

    def import_archive(
        self,
        content: bytes,
        *,
        enabled: bool = True,
        author: str = "user",
        replace_existing: bool = False,
        expected_name: str | None = None,
        market_origin: dict[str, str] | None = None,
        history_version: str | None = None,
        expected_settings_revision: int | None = None,
    ) -> SkillDetailRecord:
        work, skill = self._archive_package(content)
        try:
            if expected_name is not None and skill.name != expected_name:
                raise SkillCatalogError(
                    f"Skill archive identity mismatch: expected {expected_name}, got {skill.name}"
                )
            if replace_existing:
                self.manager.replace(
                    work / skill.name,
                    enabled=enabled,
                    market_origin=market_origin,
                    expected_revision=expected_settings_revision,
                )
            else:
                self.manager.install(
                    work / skill.name,
                    enabled=enabled,
                    market_origin=market_origin,
                    expected_revision=expected_settings_revision,
                )
            self._record_history(
                load_skill_package(self.manager.root / skill.name, source="user"),
                source_dir=self.manager.root / skill.name,
                action="update" if replace_existing else "import",
                author=author,
                version=history_version,
            )
        finally:
            shutil.rmtree(work)
        return self.get_detail(skill.name)

    def inspect_archive(
        self,
        content: bytes,
        *,
        expected_name: str | None = None,
    ) -> SkillArchiveInspection:
        """完整解压校验但不安装，用于生成绑定精确包内容的确认信息。"""
        work, skill = self._archive_package(content)
        try:
            if expected_name is not None and skill.name != expected_name:
                raise SkillCatalogError(
                    f"Skill archive identity mismatch: expected {expected_name}, got {skill.name}"
                )
            return SkillArchiveInspection(
                name=skill.name,
                description=skill.description,
                instructions=skill.instructions,
                allowed_tools=skill.allowed_tools,
                resources=tuple(
                    (resource.path, resource.content) for resource in skill.resources
                ),
                content_hash=self._package_hash(work / skill.name, skill),
                risk_warnings=_content_risk_warnings(skill),
            )
        finally:
            shutil.rmtree(work)

    def create_draft_from_archive(
        self,
        content: bytes,
        *,
        author: str = "user:archive-import",
    ) -> SkillDraftRecord:
        """安全解包归档并只生成草稿，不改变活动 Skill Catalog。"""
        work, skill = self._archive_package(content)
        try:
            return self.create_draft(
                SkillDraftPayload(
                    name=skill.name,
                    description=skill.description,
                    instructions=skill.instructions,
                    allowed_tools=skill.allowed_tools,
                    resources=tuple(
                        (resource.path, resource.content)
                        for resource in skill.resources
                    ),
                ),
                author=author,
            )
        finally:
            shutil.rmtree(work)

    def get_detail(self, name: str) -> SkillDetailRecord:
        managed = next((item for item in self.manager.list_all() if item.name == name), None)
        if managed is None:
            raise SkillCatalogError(f"Skill does not exist: {name}")
        if managed.source == "builtin":
            skill = BuiltInSkillCatalog.discover(self.manager.builtin_root).get(name)
        else:
            skill = load_skill_package(self.manager.root / name, source=managed.source)
        if skill is None:
            raise SkillCatalogError(f"Skill does not exist: {name}")
        return SkillDetailRecord(
            name=skill.name,
            description=skill.description,
            source=skill.source,
            editable=skill.source == "user",
            enabled=managed.enabled,
            allowed_tools=skill.allowed_tools,
            instructions=skill.instructions,
            resources=tuple((item.path, item.content) for item in skill.resources),
            revision=self.manager.revision,
        )

    def list_history(self, name: str) -> tuple[SkillHistoryRecord, ...]:
        records = self._read_history(name)
        return tuple(
            SkillHistoryRecord(
                history_id=item["history_id"],
                skill_name=item["skill_name"],
                action=item["action"],
                author=item["author"],
                created_at=item["created_at"],
                description=item["description"],
                allowed_tools=(
                    tuple(item["allowed_tools"])
                    if item["allowed_tools"] is not None
                    else None
                ),
                version=(str(item["version"]) if item.get("version") else None),
                market_origin=(
                    {str(key): str(value) for key, value in item["market_origin"].items()}
                    if isinstance(item.get("market_origin"), dict)
                    else None
                ),
            )
            for item in reversed(records)
        )

    def list_recoverable(self) -> tuple[RecoverableSkillRecord, ...]:
        """列出当前已删除、但仍有不可变快照可恢复的 Skill。"""
        installed = {item.name for item in self.manager.list_all()}
        records: list[RecoverableSkillRecord] = []
        for path in sorted(self._history_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir() or path.is_symlink() or path.name in installed:
                continue
            name = _validated_managed_name(path.name)
            history = self.list_history(name)
            if not history or history[0].action != "delete":
                continue
            latest = history[0]
            records.append(
                RecoverableSkillRecord(
                    name=name,
                    history_id=latest.history_id,
                    description=latest.description,
                    source="market" if latest.market_origin is not None else "user",
                    version=latest.version,
                    deleted_at=latest.created_at,
                )
            )
        return tuple(records)

    def get_history_detail(
        self,
        name: str,
        history_id: str,
    ) -> SkillDetailRecord:
        """读取一个不可变历史包，供 UI 展示正文和资源 Diff。"""
        name = _validated_managed_name(name)
        try:
            normalized = str(__import__("uuid").UUID(history_id))
        except ValueError as exc:
            raise SkillCatalogError("Invalid skill history id") from exc
        snapshot = self._history_root / name / normalized / name
        skill = load_skill_package(snapshot, source="user")
        return SkillDetailRecord(
            name=skill.name,
            description=skill.description,
            source="user",
            editable=False,
            enabled=False,
            allowed_tools=skill.allowed_tools,
            instructions=skill.instructions,
            resources=tuple((item.path, item.content) for item in skill.resources),
            revision=self.manager.revision,
        )

    def delete(self, name: str, *, expected_revision: int, author: str = "user") -> None:
        name = _validated_managed_name(name)
        if expected_revision != self.manager.revision:
            raise SkillCatalogError(
                f"Skill settings revision conflict: expected {expected_revision}, "
                f"current {self.manager.revision}"
            )
        source = self.manager.root / name
        skill = load_skill_package(source, source="user")
        market_origin = self.manager.market_origin(name)
        self._record_history(
            skill,
            source_dir=source,
            action="delete",
            author=author,
            version=(market_origin.get("version") if market_origin is not None else None),
        )
        self.manager.delete(name, expected_revision=expected_revision)

    def rollback(
        self,
        name: str,
        history_id: str,
        *,
        author: str = "user",
        expected_revision: int | None = None,
    ) -> SkillDetailRecord:
        name = _validated_managed_name(name)
        try:
            normalized = str(__import__("uuid").UUID(history_id))
        except ValueError as exc:
            raise SkillCatalogError("Invalid skill history id") from exc
        snapshot = self._history_root / name / normalized / name
        skill = load_skill_package(snapshot, source="user")
        history_record = next(
            (
                item
                for item in self.list_history(name)
                if item.history_id == normalized
            ),
            None,
        )
        if history_record is None:
            raise SkillCatalogError("Skill history version does not exist")
        destination = self.manager.root / name
        market_origin = (
            dict(history_record.market_origin)
            if history_record.market_origin is not None
            else None
        )
        if market_origin is not None and history_record.version is not None:
            market_origin["version"] = history_record.version
            market_origin["installed_at"] = _now()
        if destination.exists():
            self.manager.replace(
                snapshot,
                market_origin=market_origin,
                expected_revision=expected_revision,
            )
        else:
            self.manager.install(
                snapshot,
                enabled=True,
                market_origin=market_origin,
                expected_revision=expected_revision,
            )
        self._record_history(
            load_skill_package(destination, source="user"),
            source_dir=destination,
            action="rollback",
            author=author,
            version=history_record.version,
        )
        return self.get_detail(skill.name)


__all__ = [
    "SkillCheckResult",
    "SkillArchiveInspection",
    "SkillDetailRecord",
    "SkillDraftPayload",
    "SkillDraftRecord",
    "SkillHistoryRecord",
    "SkillInstallAuthorization",
    "SkillAgentSettings",
    "RecoverableSkillRecord",
    "SkillManagementService",
]
