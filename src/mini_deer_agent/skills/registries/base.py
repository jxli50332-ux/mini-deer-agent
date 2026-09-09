"""隔离外部 Skill Registry 协议的统一投影。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RegistrySkill:
    provider: str
    remote_id: str
    name: str
    version: str | None
    description: str
    publisher: str
    license: str | None
    tags: tuple[str, ...]
    source_url: str | None
    canonical_url: str
    required_tools: tuple[str, ...]
    runtime_requirements: tuple[str, ...]
    download_ref: str
    content_hash: str | None
    scan_status: str
    changelog: str | None
    published_at: str | None
    compatible: bool
    compatibility_reason: str
    file_paths: tuple[str, ...] = ()
    package_size: int | None = None
    file_hashes: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RegistrySkillVersion:
    version: str
    changelog: str | None
    published_at: str | None


class SkillRegistryProvider(Protocol):
    name: str

    def search(self, query: str) -> tuple[RegistrySkill, ...]: ...

    def get(self, remote_id: str, *, version: str | None = None) -> RegistrySkill: ...

    def versions(self, remote_id: str) -> tuple[RegistrySkillVersion, ...]: ...

    def download(self, remote_id: str, *, version: str | None = None) -> bytes: ...


__all__ = ["RegistrySkill", "RegistrySkillVersion", "SkillRegistryProvider"]
