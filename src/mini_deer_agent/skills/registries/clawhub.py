"""ClawHub 公共只读 API 的容错适配器。"""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

import httpx

from mini_deer_agent.skills.registries.base import RegistrySkill, RegistrySkillVersion


_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ClawHubRegistryProvider:
    name = "clawhub"

    def __init__(
        self,
        *,
        base_url: str = "https://clawhub.ai",
        timeout_seconds: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client

    def search(self, query: str) -> tuple[RegistrySkill, ...]:
        normalized = query.strip()
        if not normalized:
            return ()
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "mini-deer-agent/0.1"},
        )
        close = self._client is None
        try:
            response = client.get(
                f"{self._base_url}/api/v1/search",
                params={"q": normalized, "nonSuspiciousOnly": "true"},
            )
            response.raise_for_status()
            payload = response.json()
        finally:
            if close:
                client.close()
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise ValueError("ClawHub search response is invalid")
        return tuple(self._project(item) for item in results if isinstance(item, dict))

    def get(
        self,
        remote_id: str,
        *,
        version: str | None = None,
    ) -> RegistrySkill:
        """读取发布者限定的详情，解析当前精确版本和安全摘要。"""
        owner, slug = self._split_reference(remote_id)
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "mini-deer-agent/0.1"},
        )
        close = self._client is None
        try:
            response = client.get(
                f"{self._base_url}/api/v1/skills/{slug}",
                params={"owner": owner},
            )
            response.raise_for_status()
            payload = response.json()
            latest_payload = (
                payload.get("latestVersion")
                if isinstance(payload, dict)
                and isinstance(payload.get("latestVersion"), dict)
                else {}
            )
            resolved_version = str(
                version or latest_payload.get("version") or ""
            ).strip()
            version_payload: dict[str, Any] = {}
            if resolved_version:
                version_response = client.get(
                    f"{self._base_url}/api/v1/skills/{slug}/versions/{resolved_version}",
                    params={"owner": owner},
                )
                version_response.raise_for_status()
                raw_version_payload = version_response.json()
                if not isinstance(raw_version_payload, dict) or not isinstance(
                    raw_version_payload.get("version"), dict
                ):
                    raise ValueError("ClawHub skill version response is invalid")
                version_payload = raw_version_payload["version"]
        finally:
            if close:
                client.close()
        if not isinstance(payload, dict) or not isinstance(payload.get("skill"), dict):
            raise ValueError("ClawHub skill detail response is invalid")
        skill = payload["skill"]
        latest = version_payload or (
            payload.get("latestVersion")
            if isinstance(payload.get("latestVersion"), dict)
            else {}
        )
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        moderation = payload.get("moderation") if isinstance(payload.get("moderation"), dict) else {}
        resolved = str(latest.get("version") or "").strip() or None
        systems = metadata.get("systems") if isinstance(metadata.get("systems"), list) else []
        setup = metadata.get("setup") if isinstance(metadata.get("setup"), list) else []
        raw_files = latest.get("files") if isinstance(latest.get("files"), list) else []
        files = [item for item in raw_files if isinstance(item, dict)]
        file_paths = tuple(
            str(item.get("path") or "") for item in files if item.get("path")
        )
        file_hashes = tuple(
            (str(item["path"]), str(item["sha256"]).lower())
            for item in files
            if item.get("path") and item.get("sha256")
        )
        package_size = sum(
            item["size"]
            for item in files
            if isinstance(item.get("size"), int) and item["size"] >= 0
        )
        security = latest.get("security") if isinstance(latest.get("security"), dict) else {}
        scan_status = str(
            security.get("status") or moderation.get("status") or "unreported"
        )
        unsupported_files = tuple(
            path
            for path in file_paths
            if path != "SKILL.md" and not path.startswith("references/")
        )
        compatibility_problems: list[str] = []
        if file_paths and "SKILL.md" not in file_paths:
            compatibility_problems.append("包内没有大小写精确匹配的 SKILL.md")
        if unsupported_files:
            compatibility_problems.append(
                "包含不受支持的文件：" + "、".join(unsupported_files[:4])
            )
        if len(file_paths) > 18 or package_size > 256 * 1024:
            compatibility_problems.append("文件数量或文本总大小超过 Mini Deer 限制")
        if systems or setup:
            compatibility_problems.append("声明了 Mini Deer 第一版不自动安装的运行时要求")
        if scan_status not in {"clean", "unreported"}:
            compatibility_problems.append(f"远程扫描状态为 {scan_status}")
        compatible = not compatibility_problems
        return RegistrySkill(
            provider=self.name,
            remote_id=remote_id,
            name=str(skill.get("slug") or slug),
            version=resolved,
            description=str(skill.get("summary") or ""),
            publisher=owner,
            license=str(latest["license"]) if latest.get("license") else None,
            tags=tuple(str(value) for value in (skill.get("tags") or {}).keys()),
            source_url=None,
            canonical_url=f"{self._base_url}/{owner}/skills/{slug}",
            required_tools=(),
            runtime_requirements=tuple(str(value) for value in [*systems, *setup]),
            download_ref=remote_id,
            # ClawHub 的扫描哈希不保证与生成的 ZIP 字节一致；本地确认令牌
            # 绑定实际下载内容，不能把扫描摘要误当下载校验值。
            content_hash=None,
            scan_status=scan_status,
            changelog=str(latest["changelog"]) if latest.get("changelog") else None,
            published_at=(
                datetime.fromtimestamp(latest["createdAt"] / 1000, tz=UTC).isoformat()
                if isinstance(latest.get("createdAt"), (int, float))
                else None
            ),
            compatible=compatible,
            compatibility_reason=(
                "精确版本的文件清单符合 Mini Deer 文本 Skill 子集；安装前仍会下载并逐文件验哈希。"
                if compatible
                else "；".join(compatibility_problems)
            ),
            file_paths=file_paths,
            package_size=package_size if files else None,
            file_hashes=file_hashes,
        )

    def versions(self, remote_id: str) -> tuple[RegistrySkillVersion, ...]:
        owner, slug = self._split_reference(remote_id)
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "mini-deer-agent/0.1"},
        )
        close = self._client is None
        try:
            raw_items: list[dict[str, Any]] = []
            cursor: str | None = None
            seen_cursors: set[str] = set()
            for _ in range(20):
                response = client.get(
                    f"{self._base_url}/api/v1/skills/{slug}/versions",
                    params={
                        "owner": owner,
                        "limit": 100,
                        **({"cursor": cursor} if cursor is not None else {}),
                    },
                )
                response.raise_for_status()
                payload = response.json()
                items = payload.get("items") if isinstance(payload, dict) else None
                if not isinstance(items, list):
                    raise ValueError("ClawHub skill versions response is invalid")
                raw_items.extend(item for item in items if isinstance(item, dict))
                next_cursor = payload.get("nextCursor")
                if not isinstance(next_cursor, str) or not next_cursor:
                    break
                if next_cursor in seen_cursors:
                    raise ValueError("ClawHub skill versions cursor repeated")
                seen_cursors.add(next_cursor)
                cursor = next_cursor
            else:
                raise ValueError("ClawHub skill versions pagination exceeded the limit")
        finally:
            if close:
                client.close()
        return tuple(
            RegistrySkillVersion(
                version=str(item["version"]),
                changelog=(str(item["changelog"]) if item.get("changelog") else None),
                published_at=(
                    datetime.fromtimestamp(item["createdAt"] / 1000, tz=UTC).isoformat()
                    if isinstance(item.get("createdAt"), (int, float))
                    else None
                ),
            )
            for item in raw_items
            if item.get("version")
        )

    @staticmethod
    def _split_reference(remote_id: str) -> tuple[str, str]:
        parts = remote_id.removeprefix("@").split("/", 1)
        if (
            len(parts) != 2
            or _OWNER_PATTERN.fullmatch(parts[0]) is None
            or _SLUG_PATTERN.fullmatch(parts[1]) is None
        ):
            raise ValueError("Invalid ClawHub download reference")
        return parts[0], parts[1]

    def download(self, remote_id: str, *, version: str | None = None) -> bytes:
        """下载原生 ZIP；GitHub 源交接保持拒绝，避免绕过本地导入检查。"""
        owner, slug = self._split_reference(remote_id)
        client = self._client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
            headers={
                "Accept": "application/zip, application/json",
                "User-Agent": "mini-deer-agent/0.1",
            },
        )
        close = self._client is None
        try:
            response = client.get(
                f"{self._base_url}/api/v1/download",
                params={
                    "slug": slug,
                    "owner": owner,
                    **({"version": version} if version is not None else {}),
                },
            )
            response.raise_for_status()
            if "application/zip" not in response.headers.get(
                "content-type", ""
            ).lower():
                raise ValueError(
                    "该 Skill 使用 Mini Deer 尚不支持的 GitHub 源交接，未执行安装。"
                )
            return response.content
        finally:
            if close:
                client.close()

    def _project(self, item: dict[str, Any]) -> RegistrySkill:
        native = item.get("native") if isinstance(item.get("native"), dict) else {}
        skill = native.get("skill") if isinstance(native.get("skill"), dict) else {}
        owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
        publisher = item.get("publisher") if isinstance(item.get("publisher"), dict) else {}
        trust = item.get("trust") if isinstance(item.get("trust"), dict) else {}
        install = item.get("install") if isinstance(item.get("install"), dict) else {}
        slug = str(item.get("slug") or skill.get("slug") or "").strip()
        handle = str(
            item.get("ownerHandle") or owner.get("handle") or publisher.get("handle") or "unknown"
        ).strip()
        reference = str(install.get("reference") or f"{handle}/{slug}")
        categories = skill.get("categories") if isinstance(skill.get("categories"), list) else []
        topics = skill.get("topics") if isinstance(skill.get("topics"), list) else []
        updated = item.get("updatedAt") or skill.get("updatedAt")
        published_at = None
        if isinstance(updated, (int, float)):
            published_at = datetime.fromtimestamp(updated / 1000, tz=UTC).isoformat()
        suspicious = bool(skill.get("isSuspicious"))
        installability = str(trust.get("installability") or "unknown")
        compatible = not suspicious and installability == "installable"
        return RegistrySkill(
            provider=self.name,
            remote_id=reference,
            name=slug,
            version=(str(item["version"]) if item.get("version") else None),
            description=str(item.get("summary") or skill.get("summary") or ""),
            publisher=handle,
            license=None,
            tags=tuple(dict.fromkeys(str(value) for value in [*categories, *topics])),
            source_url=(str(install["sourceUrl"]) if install.get("sourceUrl") else None),
            canonical_url=f"{self._base_url}/{handle}/skills/{slug}",
            required_tools=(),
            runtime_requirements=(),
            download_ref=reference,
            content_hash=None,
            scan_status="suspicious" if suspicious else str(trust.get("clawHubVerdict") or "unreported"),
            changelog=None,
            published_at=published_at,
            compatible=compatible,
            compatibility_reason=(
                "目录标记为可安装；安装前仍需 Mini Deer 本地静态检查。"
                if compatible
                else f"远程目录状态：{installability}。"
            ),
        )


__all__ = ["ClawHubRegistryProvider"]
