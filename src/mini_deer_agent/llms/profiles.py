"""可信模型 Profile 解析、非敏感投影、默认选择与连接检查。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Literal, cast
from urllib.parse import urlsplit

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr

from mini_deer_agent.core import Settings
from mini_deer_agent.llms.factory import create_chat_model


_PROFILE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ModelProfileError(RuntimeError):
    """表示可信模型配置或默认选择无效。"""


class ModelSelectionConflictError(ModelProfileError):
    """表示设置页面携带的选择 revision 已过期。"""


@dataclass(frozen=True, slots=True)
class ModelProfile:
    name: str
    display_name: str
    provider: Literal["openai", "openai-compatible"]
    model: str
    api_key_env: str
    base_url: str | None = None
    supports_tools: bool = True
    supports_reasoning: bool = False
    source: Literal["environment", "file"] = "file"


@dataclass(frozen=True, slots=True)
class ModelProfileView:
    name: str
    display_name: str
    provider: str
    model: str
    base_url: str | None
    api_key_env: str
    api_key_configured: bool
    supports_tools: bool
    supports_reasoning: bool
    source: Literal["environment", "file"]


@dataclass(frozen=True, slots=True)
class ModelSelection:
    primary_model: str
    goal_model: str | None
    revision: int


@dataclass(frozen=True, slots=True)
class ModelSnapshot:
    profile_name: str
    profile_revision: str
    selection_revision: int
    model: BaseChatModel
    profile: ModelProfile | None = None

    @property
    def metadata(self) -> dict[str, str | int]:
        return {
            "model_profile": self.profile_name,
            "model_profile_revision": self.profile_revision,
            "model_selection_revision": self.selection_revision,
        }


@dataclass(frozen=True, slots=True)
class ModelProbeResult:
    ok: bool
    category: Literal[
        "success", "missing_key", "authentication", "network", "capability", "unknown"
    ]
    message: str


class ModelProfileCatalog:
    """从受信任 YAML 和旧环境配置构建不可执行的 Profile 目录。"""

    def __init__(self, profiles: tuple[ModelProfile, ...], revision: str) -> None:
        if not profiles:
            raise ModelProfileError("At least one model profile is required")
        self.profiles = profiles
        self.revision = revision
        self._by_name = {profile.name: profile for profile in profiles}

    def get(self, name: str) -> ModelProfile:
        profile = self._by_name.get(name)
        if profile is None:
            raise ModelProfileError(f"Unknown model profile: {name}")
        return profile

    @classmethod
    def load(cls, path: Path, settings: Settings) -> "ModelProfileCatalog":
        profiles: list[ModelProfile] = []
        environment_model = (settings.model_name or "").strip()
        if environment_model:
            provider = settings.model_provider.strip().lower()
            if provider not in {"openai", "openai-compatible"}:
                raise ModelProfileError(f"Unsupported model provider: {provider}")
            profiles.append(
                ModelProfile(
                    name="environment-default",
                    display_name="环境默认",
                    provider=cast(Literal["openai", "openai-compatible"], provider),
                    model=environment_model,
                    api_key_env="MINI_DEER_API_KEY",
                    base_url=str(settings.api_base_url) if settings.api_base_url else None,
                    supports_reasoning=True,
                    source="environment",
                )
            )
            goal_model = (settings.goal_evaluator_model_name or "").strip()
            if goal_model:
                profiles.append(
                    ModelProfile(
                        name="environment-goal",
                        display_name="环境 Goal 评估",
                        provider=cast(
                            Literal["openai", "openai-compatible"], provider
                        ),
                        model=goal_model,
                        api_key_env="MINI_DEER_API_KEY",
                        base_url=(
                            str(settings.api_base_url)
                            if settings.api_base_url
                            else None
                        ),
                        supports_tools=False,
                        supports_reasoning=True,
                        source="environment",
                    )
                )
        if path.exists():
            try:
                document = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                raise ModelProfileError(f"Cannot load models config: {path}") from exc
            if not isinstance(document, dict) or document.get("version") != 1:
                raise ModelProfileError("models config must use version: 1")
            items = document.get("models")
            if not isinstance(items, list):
                raise ModelProfileError("models config requires a models list")
            profiles.extend(cls._parse_profile(item) for item in items)
        if not profiles:
            # 允许无模型配置启动健康检查与设置页，但真正创建模型时仍失败关闭。
            profiles.append(
                ModelProfile(
                    name="environment-default",
                    display_name="环境默认（未配置）",
                    provider="openai",
                    model="not-configured",
                    api_key_env="MINI_DEER_API_KEY",
                    source="environment",
                )
            )
        names = [profile.name for profile in profiles]
        if len(set(names)) != len(names):
            raise ModelProfileError("Model profile names must be unique")
        canonical = json.dumps(
            [
                {
                    "name": p.name,
                    "display_name": p.display_name,
                    "provider": p.provider,
                    "model": p.model,
                    "api_key_env": p.api_key_env,
                    "base_url": p.base_url,
                    "supports_tools": p.supports_tools,
                    "supports_reasoning": p.supports_reasoning,
                    "source": p.source,
                }
                for p in profiles
            ],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
        return cls(tuple(profiles), hashlib.sha256(canonical).hexdigest())

    @staticmethod
    def _parse_profile(value: object) -> ModelProfile:
        if not isinstance(value, dict):
            raise ModelProfileError("Each model profile must be a mapping")
        allowed = {
            "name", "display_name", "provider", "model", "api_key_env",
            "base_url", "supports_tools", "supports_reasoning",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ModelProfileError(
                "Unknown model profile field(s): " + ", ".join(sorted(map(str, unknown)))
            )
        required = ("name", "display_name", "provider", "model", "api_key_env")
        if any(not isinstance(value.get(key), str) or not value[key].strip() for key in required):
            raise ModelProfileError("Model profile string fields must not be blank")
        name = str(value["name"]).strip()
        provider = str(value["provider"]).strip().lower()
        if _PROFILE_NAME.fullmatch(name) is None:
            raise ModelProfileError(f"Invalid model profile name: {name}")
        if provider not in {"openai", "openai-compatible"}:
            raise ModelProfileError(f"Unsupported model provider: {provider}")
        base_url = value.get("base_url")
        if provider == "openai-compatible" and (
            not isinstance(base_url, str) or not base_url.strip()
        ):
            raise ModelProfileError(f"openai-compatible profile {name} requires base_url")
        if base_url is not None and not isinstance(base_url, str):
            raise ModelProfileError(f"base_url for {name} must be a string")
        if isinstance(base_url, str):
            parsed_url = urlsplit(base_url.strip())
            if (
                parsed_url.scheme not in {"http", "https"}
                or not parsed_url.hostname
                or parsed_url.username is not None
                or parsed_url.password is not None
                or parsed_url.query
                or parsed_url.fragment
            ):
                raise ModelProfileError(
                    f"base_url for {name} must be a credential-free HTTP(S) origin/path"
                )
        api_key_env = str(value["api_key_env"]).strip()
        if _ENVIRONMENT_NAME.fullmatch(api_key_env) is None:
            raise ModelProfileError(f"Invalid api_key_env for {name}")
        tools = value.get("supports_tools", True)
        reasoning = value.get("supports_reasoning", False)
        if not isinstance(tools, bool) or not isinstance(reasoning, bool):
            raise ModelProfileError("Model capability flags must be booleans")
        return ModelProfile(
            name=name,
            display_name=str(value["display_name"]).strip(),
            provider=cast(Literal["openai", "openai-compatible"], provider),
            model=str(value["model"]).strip(),
            api_key_env=api_key_env,
            base_url=base_url.strip() if isinstance(base_url, str) else None,
            supports_tools=tools,
            supports_reasoning=reasoning,
        )


class SqliteModelSelectionStore:
    """在 application.sqlite 中以 CAS revision 保存应用级模型选择。"""

    def __init__(
        self,
        path: Path,
        default_primary: str,
        default_goal: str | None = None,
    ) -> None:
        self._path = path
        self._lock = RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS model_selection (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    primary_model TEXT NOT NULL,
                    goal_model TEXT,
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """INSERT OR IGNORE INTO model_selection(
                    singleton, primary_model, goal_model, revision, updated_at
                ) VALUES (1, ?, ?, 0, datetime('now'))""",
                (default_primary, default_goal),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self) -> ModelSelection:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT primary_model, goal_model, revision FROM model_selection WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise ModelProfileError("Model selection is not initialized")
        return ModelSelection(str(row[0]), row[1], int(row[2]))

    def update(
        self,
        primary_model: str,
        goal_model: str | None,
        *,
        expected_revision: int,
    ) -> ModelSelection:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """UPDATE model_selection
                SET primary_model = ?, goal_model = ?, revision = revision + 1,
                    updated_at = datetime('now')
                WHERE singleton = 1 AND revision = ?""",
                (primary_model, goal_model, expected_revision),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT revision FROM model_selection WHERE singleton = 1"
                ).fetchone()
                raise ModelSelectionConflictError(
                    f"Model selection revision conflict: expected {expected_revision}, "
                    f"current {row[0] if row else 'missing'}"
                )
        return self.get()


class ModelConfigurationService:
    """组合 Profile、持久选择、模型构造与安全连接检查。"""

    def __init__(self, settings: Settings, *, model_factory=create_chat_model) -> None:
        self.settings = settings
        self.catalog = ModelProfileCatalog.load(settings.models_config_path, settings)
        environment_ready = any(
            p.name == "environment-default" and environment_model(settings)
            for p in self.catalog.profiles
        )
        tool_capable = next(
            (profile.name for profile in self.catalog.profiles if profile.supports_tools),
            self.catalog.profiles[0].name,
        )
        default = "environment-default" if environment_ready else tool_capable
        default_goal = (
            "environment-goal"
            if any(p.name == "environment-goal" for p in self.catalog.profiles)
            else None
        )
        self.store = SqliteModelSelectionStore(
            settings.application_database_path,
            default,
            default_goal,
        )
        self._model_factory = model_factory
        persisted = self.store.get()
        known = {profile.name for profile in self.catalog.profiles}
        persisted_primary = next(
            (p for p in self.catalog.profiles if p.name == persisted.primary_model),
            None,
        )
        if persisted_primary is None or not persisted_primary.supports_tools:
            self.store.update(default, None, expected_revision=persisted.revision)
        elif persisted.goal_model is not None and persisted.goal_model not in known:
            self.store.update(
                persisted.primary_model,
                None,
                expected_revision=persisted.revision,
            )

    def list_profiles(self) -> tuple[ModelProfileView, ...]:
        return tuple(
            ModelProfileView(
                name=p.name,
                display_name=p.display_name,
                provider=p.provider,
                model=p.model,
                base_url=p.base_url,
                api_key_env=p.api_key_env,
                api_key_configured=self._api_key(p) is not None,
                supports_tools=p.supports_tools,
                supports_reasoning=p.supports_reasoning,
                source=p.source,
            )
            for p in self.catalog.profiles
        )

    def selection(self) -> ModelSelection:
        value = self.store.get()
        self.catalog.get(value.primary_model)
        if value.goal_model is not None:
            self.catalog.get(value.goal_model)
        return value

    def update_selection(
        self,
        primary_model: str,
        goal_model: str | None,
        *,
        expected_revision: int,
    ) -> ModelSelection:
        primary = self.catalog.get(primary_model)
        if not primary.supports_tools:
            raise ModelProfileError(
                f"Primary model profile does not support tools: {primary_model}"
            )
        if goal_model is not None:
            goal = self.catalog.get(goal_model)
        else:
            goal = None
        # 在 CAS 提交前完成本地模型构造。缺失凭据或适配器配置错误不能
        # 先污染持久默认值，再让之后的 Run 才失败。
        self._create_model_from_profile(primary)
        if goal is not None:
            self._create_model_from_profile(goal)
        return self.store.update(primary_model, goal_model, expected_revision=expected_revision)

    def _api_key(self, profile: ModelProfile) -> SecretStr | None:
        if profile.source == "environment" and self.settings.api_key is not None:
            value = self.settings.api_key.get_secret_value().strip()
        else:
            value = os.environ.get(profile.api_key_env, "").strip()
        return SecretStr(value) if value else None

    def create_model(self, profile_name: str) -> BaseChatModel:
        profile = self.catalog.get(profile_name)
        return self._create_model_from_profile(profile)

    def _create_model_from_profile(self, profile: ModelProfile) -> BaseChatModel:
        key = self._api_key(profile)
        if key is None:
            raise ModelProfileError(f"API key environment variable is missing: {profile.api_key_env}")
        configured = self.settings.model_copy(
            update={
                "model_provider": profile.provider,
                "model_name": profile.model,
                "api_key": key,
                "api_base_url": profile.base_url,
            }
        )
        try:
            return self._model_factory(configured)
        except Exception as exc:
            raise ModelProfileError(
                f"Cannot construct model profile: {profile.name}"
            ) from exc

    def create_primary_snapshot(self) -> ModelSnapshot:
        value = self.selection()
        profile = self.catalog.get(value.primary_model)
        if not profile.supports_tools:
            raise ModelProfileError(
                f"Primary model profile does not support tools: {value.primary_model}"
            )
        return ModelSnapshot(
            value.primary_model,
            self.catalog.revision,
            value.revision,
            self.create_model(value.primary_model),
            profile,
        )

    def restore_primary_snapshot(
        self,
        *,
        profile: ModelProfile,
        profile_revision: str,
        selection_revision: int,
    ) -> ModelSnapshot:
        """从 Goal 持久快照恢复同一非敏感 Profile，不读取当前默认选择。"""
        if not profile.supports_tools:
            raise ModelProfileError(
                f"Stored primary model profile does not support tools: {profile.name}"
            )
        return ModelSnapshot(
            profile.name,
            profile_revision,
            selection_revision,
            self._create_model_from_profile(profile),
            profile,
        )

    def create_goal_model(self) -> BaseChatModel:
        value = self.selection()
        return self.create_model(value.goal_model or value.primary_model)

    def create_goal_snapshot(self) -> ModelSnapshot:
        """解析本次独立 Goal 评估实际使用的 Profile。"""
        value = self.selection()
        profile_name = value.goal_model or value.primary_model
        profile = self.catalog.get(profile_name)
        return ModelSnapshot(
            profile_name,
            self.catalog.revision,
            value.revision,
            self._create_model_from_profile(profile),
            profile,
        )

    async def probe(self, name: str, *, timeout_seconds: float = 15.0) -> ModelProbeResult:
        profile = self.catalog.get(name)
        if not profile.supports_tools:
            return ModelProbeResult(
                False,
                "capability",
                "该 Profile 未声明工具调用能力，不能作为主 Agent 模型。",
            )
        try:
            await asyncio.wait_for(
                self.create_model(name).ainvoke("Reply only with OK."),
                timeout_seconds,
            )
            return ModelProbeResult(True, "success", "连接成功")
        except ModelProfileError as exc:
            return ModelProbeResult(False, "missing_key", str(exc))
        except Exception as exc:
            lowered = f"{type(exc).__name__} {exc}".lower()
            if "auth" in lowered or "401" in lowered or "403" in lowered:
                return ModelProbeResult(False, "authentication", "认证失败，请检查模型凭据。")
            if "timeout" in lowered or "connect" in lowered or "network" in lowered:
                return ModelProbeResult(False, "network", "网络连接失败或超时。")
            if "tool" in lowered or "capab" in lowered:
                return ModelProbeResult(False, "capability", "模型能力与当前 Agent 不兼容。")
            return ModelProbeResult(False, "unknown", "连接检查失败。")


def environment_model(settings: Settings) -> bool:
    return bool((settings.model_name or "").strip())


__all__ = [
    "ModelConfigurationService", "ModelProbeResult", "ModelProfile",
    "ModelProfileCatalog", "ModelProfileError", "ModelProfileView",
    "ModelSelection", "ModelSelectionConflictError", "ModelSnapshot",
    "SqliteModelSelectionStore",
]
