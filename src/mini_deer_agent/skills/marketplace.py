"""Skill 市场目录编排与离线缓存。"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Literal
from uuid import uuid4
from zipfile import ZipFile

from mini_deer_agent.skills.registries import (
    RegistrySkill,
    RegistrySkillVersion,
    SkillRegistryProvider,
)
from mini_deer_agent.skills.management import SkillDetailRecord, SkillManagementService
from mini_deer_agent.skills.catalog import SkillCatalogError


_CONFIRMATION_TTL = timedelta(minutes=10)
_MAX_PENDING_CONFIRMATIONS = 32


@dataclass(frozen=True, slots=True)
class MarketChangePreview:
    confirmation_token: str
    action: Literal["install", "update"]
    provider: str
    remote_id: str
    name: str
    current_version: str | None
    target_version: str | None
    content_hash: str
    enabled_after: bool
    allowed_tools_before: tuple[str, ...] | None
    allowed_tools_after: tuple[str, ...] | None
    added_tools: tuple[str, ...]
    removed_tools: tuple[str, ...]
    permission_changed: bool
    description_changed: bool
    instructions_changed: bool
    resources_changed: bool
    risk_warnings: tuple[str, ...]
    expires_at: str


@dataclass(frozen=True, slots=True)
class _PendingMarketChange:
    preview: MarketChangePreview
    content: bytes
    enabled: bool
    settings_revision: int


class SkillMarketplaceService:
    def __init__(
        self,
        cache_path: Path,
        providers: tuple[SkillRegistryProvider, ...],
        management: SkillManagementService | None = None,
        available_tool_names: tuple[str, ...] | None = None,
    ) -> None:
        self._cache_path = cache_path
        self._providers = {provider.name: provider for provider in providers}
        self._lock = Lock()
        self._management = management
        self._available_tool_names = (
            frozenset(available_tool_names)
            if available_tool_names is not None
            else None
        )
        self._pending: dict[str, _PendingMarketChange] = {}

    def providers(self) -> tuple[dict[str, object], ...]:
        cache = self._read_cache()
        return tuple(
            {
                "name": name,
                "available": True,
                "last_synced_at": cache.get("synced_at"),
                "cached": bool(cache.get("items")),
            }
            for name in sorted(self._providers)
        )

    def search(self, query: str, *, refresh: bool = False) -> tuple[tuple[RegistrySkill, ...], str | None, bool]:
        normalized = query.strip()
        cache = self._read_cache()
        if not refresh and cache.get("query") == normalized and cache.get("items"):
            return self._decode(cache), str(cache.get("synced_at")), True
        items: list[RegistrySkill] = []
        try:
            for provider in self._providers.values():
                items.extend(
                    self._project_environment(item)
                    for item in provider.search(normalized)
                )
        except Exception:
            if cache.get("items"):
                cached = self._decode(cache)
                filtered = tuple(
                    item for item in cached
                    if normalized.casefold() in f"{item.name} {item.description} {' '.join(item.tags)}".casefold()
                )
                return filtered, str(cache.get("synced_at")), True
            raise
        synced_at = datetime.now(tz=UTC).isoformat()
        self._write_cache(normalized, tuple(items), synced_at)
        return tuple(items), synced_at, False

    def _project_environment(self, item: RegistrySkill) -> RegistrySkill:
        if self._available_tool_names is None:
            return item
        missing = tuple(
            tool
            for tool in item.required_tools
            if tool not in self._available_tool_names
        )
        if not missing:
            return item
        reason = (
            f"{item.compatibility_reason}；" if item.compatibility_reason else ""
        ) + "当前环境缺少工具：" + "、".join(missing)
        return replace(item, compatible=False, compatibility_reason=reason)

    def _read_cache(self) -> dict[str, object]:
        if not self._cache_path.exists():
            return {}
        try:
            value = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) and value.get("version") == 1 else {}

    def preview_change(
        self,
        provider: str,
        remote_id: str,
        *,
        action: Literal["install", "update"],
        version: str | None = None,
        enabled: bool = True,
    ) -> MarketChangePreview:
        """下载并完整校验候选，生成与精确内容绑定的一次性确认。"""
        if action not in {"install", "update"}:
            raise ValueError(f"Unsupported market change action: {action}")
        if provider not in self._providers:
            raise ValueError(f"Unsupported Skill market provider: {provider}")
        if self._management is None:
            raise RuntimeError("Skill marketplace installation is not configured")
        settings_revision = self._management.manager.revision
        cached_item = self.get_item(provider, remote_id)
        item = self._providers[provider].get(remote_id, version=version)
        if item.remote_id != remote_id or item.name != cached_item.name:
            raise ValueError("Skill market detail identity changed after synchronization")
        if not item.compatible:
            raise ValueError(f"Skill market item is incompatible: {item.compatibility_reason}")
        current: SkillDetailRecord | None = None
        current_version: str | None = None
        if action == "update":
            origin = self._management.manager.market_origin(item.name)
            if (
                origin is None
                or origin.get("provider") != provider
                or origin.get("remote_id") != remote_id
            ):
                raise ValueError(
                    "Market update identity does not match the installed Skill"
                )
            current = self._management.get_detail(item.name)
            current_version = origin.get("version")
        elif any(record.name == item.name for record in self._management.manager.list_all()):
            raise ValueError(f"Skill name is already installed: {item.name}")
        content = self._providers[provider].download(
            remote_id,
            version=item.version,
        )
        raw_hash = hashlib.sha256(content).hexdigest()
        if item.content_hash is not None:
            expected_hash = item.content_hash.removeprefix("sha256:").lower()
            if expected_hash != raw_hash:
                raise ValueError("Downloaded Skill content hash does not match the registry")
        self._verify_file_hashes(content, item.file_hashes)
        inspection = self._management.inspect_archive(
            content,
            expected_name=item.name,
        )
        if self._available_tool_names is not None and inspection.allowed_tools:
            missing_tools = tuple(
                tool
                for tool in inspection.allowed_tools
                if tool not in self._available_tool_names
            )
            if missing_tools:
                raise ValueError(
                    "Skill market item requires unavailable tools: "
                    + ", ".join(missing_tools)
                )
        if self._management.manager.revision != settings_revision:
            raise ValueError(
                "Skill settings changed during market preview; refresh and try again"
            )
        before_tools = current.allowed_tools if current is not None else ()
        after_tools = inspection.allowed_tools
        before_set = set(before_tools or ())
        after_set = set(after_tools or ())
        token = uuid4().hex
        expires = datetime.now(tz=UTC) + _CONFIRMATION_TTL
        preview = MarketChangePreview(
            confirmation_token=token,
            action=action,
            provider=provider,
            remote_id=remote_id,
            name=item.name,
            current_version=current_version,
            target_version=item.version or "latest",
            content_hash=inspection.content_hash,
            enabled_after=current.enabled if current is not None else enabled,
            allowed_tools_before=current.allowed_tools if current is not None else (),
            allowed_tools_after=inspection.allowed_tools,
            added_tools=tuple(sorted(after_set - before_set)),
            removed_tools=tuple(sorted(before_set - after_set)),
            permission_changed=before_tools != after_tools,
            description_changed=(
                current is not None and current.description != inspection.description
            ),
            instructions_changed=(
                current is not None and current.instructions != inspection.instructions
            ),
            resources_changed=(
                current is not None and current.resources != inspection.resources
            ),
            risk_warnings=inspection.risk_warnings,
            expires_at=expires.isoformat(),
        )
        with self._lock:
            now = datetime.now(tz=UTC)
            self._pending = {
                key: value
                for key, value in self._pending.items()
                if datetime.fromisoformat(value.preview.expires_at) > now
            }
            if len(self._pending) >= _MAX_PENDING_CONFIRMATIONS:
                oldest = min(
                    self._pending,
                    key=lambda key: self._pending[key].preview.expires_at,
                )
                self._pending.pop(oldest)
            self._pending[token] = _PendingMarketChange(
                preview,
                content,
                preview.enabled_after,
                settings_revision,
            )
        return preview

    @staticmethod
    def _verify_file_hashes(
        content: bytes,
        expected: tuple[tuple[str, str], ...],
    ) -> None:
        """把 Registry 的逐文件 SHA-256 与将要安装的同一 ZIP 字节比对。"""
        if not expected:
            return
        expected_map = {path: digest.lower() for path, digest in expected}
        with ZipFile(BytesIO(content)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            names = [item.filename for item in members]
            prefix = ""
            if names and all("/" in name for name in names):
                roots = {name.split("/", 1)[0] for name in names}
                if len(roots) == 1:
                    prefix = next(iter(roots)) + "/"
            actual: dict[str, str] = {}
            for member in members:
                path = member.filename.removeprefix(prefix)
                if path in actual:
                    raise ValueError("Downloaded Skill contains duplicate registry paths")
                actual[path] = hashlib.sha256(archive.read(member)).hexdigest()
        if set(actual) != set(expected_map):
            raise ValueError("Downloaded Skill file list does not match the registry")
        if any(actual[path] != expected_map[path] for path in expected_map):
            raise ValueError("Downloaded Skill file hash does not match the registry")

    def apply_change(
        self,
        provider: str,
        remote_id: str,
        *,
        action: Literal["install", "update"],
        confirmation_token: str,
    ) -> SkillDetailRecord:
        """只提交仍有效且身份完全匹配的一次性预检结果。"""
        if self._management is None:
            raise RuntimeError("Skill marketplace installation is not configured")
        with self._lock:
            pending = self._pending.pop(confirmation_token, None)
        if pending is None:
            raise ValueError("Market confirmation is missing, expired, or already used")
        preview = pending.preview
        if (
            preview.provider != provider
            or preview.remote_id != remote_id
            or preview.action != action
        ):
            raise ValueError("Market confirmation does not match the requested change")
        if datetime.fromisoformat(preview.expires_at) <= datetime.now(tz=UTC):
            raise ValueError("Market confirmation has expired")
        replace_existing = action == "update"
        if replace_existing:
            origin = self._management.manager.market_origin(preview.name)
            if (
                origin is None
                or origin.get("provider") != provider
                or origin.get("remote_id") != remote_id
                or origin.get("version") != preview.current_version
            ):
                raise ValueError("Installed Skill changed after the update preview")
        market_origin = {
            "provider": provider,
            "remote_id": remote_id,
            "version": preview.target_version or "latest",
            "canonical_url": self.get_item(provider, remote_id).canonical_url,
            "content_hash": preview.content_hash,
            "installed_at": datetime.now(tz=UTC).isoformat(),
        }
        detail = self._management.import_archive(
            pending.content,
            enabled=pending.enabled,
            author=f"market:{provider}",
            replace_existing=replace_existing,
            expected_name=preview.name,
            market_origin=market_origin,
            history_version=preview.target_version,
            expected_settings_revision=pending.settings_revision,
        )
        return self._management.get_detail(detail.name)

    def install(
        self,
        provider: str,
        remote_id: str,
        *,
        replace_existing: bool = False,
        confirmation_token: str,
    ) -> SkillDetailRecord:
        return self.apply_change(
            provider,
            remote_id,
            action="update" if replace_existing else "install",
            confirmation_token=confirmation_token,
        )

    def get_item(self, provider: str, remote_id: str) -> RegistrySkill:
        item = next(
            (
                candidate
                for candidate in self._decode(self._read_cache())
                if candidate.provider == provider and candidate.remote_id == remote_id
            ),
            None,
        )
        if item is None:
            raise ValueError("Skill market item is not in the synchronized cache")
        return item

    def get_fresh_item(self, provider: str, remote_id: str) -> RegistrySkill:
        if provider not in self._providers:
            raise ValueError(f"Unsupported Skill market provider: {provider}")
        cached = self.get_item(provider, remote_id)
        try:
            fresh = self._providers[provider].get(remote_id)
        except Exception:
            return cached
        return fresh

    def list_versions(
        self,
        provider: str,
        remote_id: str,
    ) -> tuple[RegistrySkillVersion, ...]:
        if provider not in self._providers:
            raise ValueError(f"Unsupported Skill market provider: {provider}")
        self.get_item(provider, remote_id)
        return self._providers[provider].versions(remote_id)

    def uninstall(
        self,
        provider: str,
        remote_id: str,
        *,
        expected_revision: int,
    ) -> None:
        if self._management is None:
            raise RuntimeError("Skill marketplace installation is not configured")
        name = remote_id.rsplit("/", 1)[-1]
        detail = self._management.get_detail(name)
        origin = self._management.manager.market_origin(name)
        if (
            detail.source != "market"
            or origin is None
            or origin.get("provider") != provider
            or origin.get("remote_id") != remote_id
        ):
            raise ValueError(f"Skill is not a market installation: {name}")
        self._management.delete(
            name,
            expected_revision=expected_revision,
            author="market:uninstall",
        )

    def rollback(
        self,
        provider: str,
        remote_id: str,
        history_id: str,
        *,
        expected_revision: int,
    ) -> SkillDetailRecord:
        if self._management is None:
            raise RuntimeError("Skill marketplace installation is not configured")
        name = remote_id.rsplit("/", 1)[-1]
        try:
            detail = self._management.get_detail(name)
        except SkillCatalogError:
            detail = None
        origin = self._management.manager.market_origin(name)
        selected_history = next(
            (
                item
                for item in self._management.list_history(name)
                if item.history_id == history_id
            ),
            None,
        )
        target_origin = (
            selected_history.market_origin
            if selected_history is not None
            else None
        )
        installed_matches = (
            detail is not None
            and detail.source == "market"
            and origin is not None
            and origin.get("provider") == provider
            and origin.get("remote_id") == remote_id
        )
        history_matches = (
            target_origin is not None
            and target_origin.get("provider") == provider
            and target_origin.get("remote_id") == remote_id
        )
        if not installed_matches and not history_matches:
            raise ValueError(f"Skill is not a market installation: {name}")
        return self._management.rollback(
            name,
            history_id,
            author="market:rollback",
            expected_revision=expected_revision,
        )

    def _decode(self, cache: dict[str, object]) -> tuple[RegistrySkill, ...]:
        raw = cache.get("items")
        if not isinstance(raw, list):
            return ()
        return tuple(
            RegistrySkill(
                **{
                    **item,
                    "tags": tuple(item.get("tags", [])),
                    "required_tools": tuple(item.get("required_tools", [])),
                    "runtime_requirements": tuple(item.get("runtime_requirements", [])),
                    "file_paths": tuple(item.get("file_paths", [])),
                    "file_hashes": tuple(
                        (pair[0], pair[1]) for pair in item.get("file_hashes", [])
                    ),
                }
            )
            for item in raw if isinstance(item, dict)
        )

    def _write_cache(self, query: str, items: tuple[RegistrySkill, ...], synced_at: str) -> None:
        with self._lock:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._cache_path.with_name(f".{self._cache_path.name}.{uuid4().hex}.tmp")
            temporary.write_text(
                json.dumps(
                    {"version": 1, "query": query, "synced_at": synced_at, "items": [asdict(item) for item in items]},
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self._cache_path)


__all__ = ["MarketChangePreview", "SkillMarketplaceService"]
