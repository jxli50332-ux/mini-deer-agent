"""编排一次 Agent 流式运行，不依赖 FastAPI 或具体传输协议。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import asdict, dataclass
from functools import partial
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from mini_deer_agent.agents import build_agent_graph
from mini_deer_agent.agents.middleware import RunBudgetPolicy, RunBudgetTracker
from mini_deer_agent.application.memory import MemoryStore
from mini_deer_agent.domain import TextAttachment
from mini_deer_agent.skills import BuiltInSkill, BuiltInSkillCatalog, SkillResource
from mini_deer_agent.streaming import (
    AgentMessageEvent,
    astream_agent_messages,
    stream_agent_messages,
)
from mini_deer_agent.streaming.events import RunEvent
from mini_deer_agent.streaming.projector import aproject_run_events

if TYPE_CHECKING:
    from mini_deer_agent.application.workspaces import FileAccess
    from mini_deer_agent.llms import ModelSnapshot
    from mini_deer_agent.skills.management import SkillManagementService
    from mini_deer_agent.skills.marketplace import SkillMarketplaceService


type AgentGraphFactory = Callable[..., CompiledStateGraph]
type FileAccessResolver = Callable[[str, str], "FileAccess | None"]
type SkillCatalogFactory = Callable[[], BuiltInSkillCatalog]
type ModelSnapshotFactory = Callable[[], "ModelSnapshot"]
type ModelSnapshotRestorer = Callable[..., "ModelSnapshot"]


@dataclass(frozen=True, slots=True)
class RunContextSnapshot:
    """一次产品 Run 固定的模型与 Skill 目录。"""

    model: "ModelSnapshot | None"
    skill_catalog: BuiltInSkillCatalog | None
    skill_catalog_hash: str
    skill_creation_enabled: bool = False

    @property
    def metadata(self) -> dict[str, str | int]:
        result: dict[str, str | int] = {
            "skill_catalog_hash": self.skill_catalog_hash,
            "skill_agent_creation_enabled": int(self.skill_creation_enabled),
        }
        if self.model is not None:
            result.update(self.model.metadata)
        return result


def _catalog_hash(catalog: BuiltInSkillCatalog | None) -> str:
    payload = [] if catalog is None else [
        {
            "name": skill.name,
            "description": skill.description,
            "source": skill.source,
            "instructions": skill.instructions,
            "allowed_tools": skill.allowed_tools,
            "resources": [(item.path, item.content) for item in skill.resources],
        }
        for skill in catalog.skills
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _human_message(
    message: str,
    attachments: tuple[TextAttachment, ...],
    human_input_response: dict[str, object] | None = None,
    internal_continuation: bool = False,
) -> HumanMessage:
    """构造 checkpoint 用户消息；正文、附件和澄清关联保持分离。"""
    additional_kwargs: dict[str, object] = {}
    if internal_continuation:
        additional_kwargs.update(
            {
                "hide_from_ui": True,
                "kind": "goal_continuation",
            }
        )
    if attachments:
        additional_kwargs["text_attachments"] = [
            {
                "filename": item.filename,
                "media_type": item.media_type,
                "size_bytes": item.size_bytes,
                "content": item.content,
            }
            for item in attachments
        ]
    if human_input_response is not None:
        additional_kwargs["hide_from_ui"] = True
        additional_kwargs["human_input_response"] = dict(human_input_response)
    if not additional_kwargs:
        return HumanMessage(content=message)
    return HumanMessage(
        content=message,
        additional_kwargs=additional_kwargs,
    )


def build_default_agent_graph(
    checkpointer: BaseCheckpointSaver,
    file_access: FileAccess | None = None,
    *,
    memory_store: MemoryStore | None = None,
    mcp_tools: tuple[BaseTool, ...] = (),
    mcp_tool_routing_keywords: Mapping[str, tuple[str, ...]] | None = None,
    skill_catalog: BuiltInSkillCatalog | None = None,
    run_budget_tracker: RunBudgetTracker | None = None,
    model_snapshot: "ModelSnapshot | None" = None,
    skill_management_service: "SkillManagementService | None" = None,
    skill_marketplace_service: "SkillMarketplaceService | None" = None,
    skill_creation_enabled: bool | None = None,
) -> CompiledStateGraph:
    """使用应用持有的 checkpointer 构建默认主 Agent 图。"""
    # 默认路径在真正开始请求时才创建模型，健康检查不依赖模型密钥是否已经配置。
    return build_agent_graph(
        model=model_snapshot.model if model_snapshot is not None else None,
        checkpointer=checkpointer,
        memory_store=memory_store,
        mcp_tools=mcp_tools,
        mcp_tool_routing_keywords=mcp_tool_routing_keywords,
        skill_catalog=skill_catalog,
        file_access=file_access,
        run_budget_tracker=run_budget_tracker,
        skill_management_service=skill_management_service,
        skill_marketplace_service=skill_marketplace_service,
        skill_creation_enabled=skill_creation_enabled,
    )


class RunStreamService:
    """把线程消息转换为同步学习流或可取消的异步 Web Run 事件流。"""

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver,
        *,
        memory_store: MemoryStore | None = None,
        mcp_tools: tuple[BaseTool, ...] = (),
        mcp_tool_routing_keywords: Mapping[str, tuple[str, ...]] | None = None,
        graph_factory: AgentGraphFactory = build_default_agent_graph,
        file_access_resolver: FileAccessResolver | None = None,
        skill_catalog_factory: SkillCatalogFactory | None = None,
        run_budget_policy: RunBudgetPolicy | None = None,
        model_snapshot_factory: ModelSnapshotFactory | None = None,
        model_snapshot_restorer: ModelSnapshotRestorer | None = None,
        skill_management_service: "SkillManagementService | None" = None,
        skill_marketplace_service: "SkillMarketplaceService | None" = None,
    ) -> None:
        """保存 checkpoint 和可替换构图工厂，不负责 HTTP 或 Run 注册。"""
        self._checkpointer = checkpointer
        self._uses_default_graph_factory = graph_factory is build_default_agent_graph
        self._graph_factory = (
            partial(
                graph_factory,
                memory_store=memory_store,
                mcp_tools=mcp_tools,
                mcp_tool_routing_keywords=mcp_tool_routing_keywords,
                skill_management_service=skill_management_service,
                skill_marketplace_service=skill_marketplace_service,
            )
            if graph_factory is build_default_agent_graph
            else graph_factory
        )
        self._file_access_resolver = file_access_resolver
        self._skill_catalog_factory = skill_catalog_factory
        self._run_budget_policy = run_budget_policy or RunBudgetPolicy()
        self._model_snapshot_factory = model_snapshot_factory
        self._model_snapshot_restorer = model_snapshot_restorer
        self._skill_management_service = skill_management_service

    def create_context_snapshot(self) -> RunContextSnapshot:
        """在产品 Run 开始边界冻结模型与 Skill，隐藏续轮复用同一对象。"""
        model = (
            self._model_snapshot_factory()
            if self._model_snapshot_factory is not None
            else None
        )
        catalog = (
            self._skill_catalog_factory()
            if self._skill_catalog_factory is not None
            else None
        )
        skill_creation_enabled = (
            self._skill_management_service.agent_settings().creation_enabled
            if self._skill_management_service is not None
            else False
        )
        return RunContextSnapshot(
            model,
            catalog,
            _catalog_hash(catalog),
            skill_creation_enabled,
        )

    def serialize_context_snapshot(self, snapshot: RunContextSnapshot) -> str:
        """序列化 Goal 可恢复的非敏感模型配置和完整 Skill 目录。"""
        model_payload: dict[str, object] | None = None
        if snapshot.model is not None:
            if snapshot.model.profile is None:
                raise ValueError("Model snapshot does not contain a restorable profile")
            model_payload = {
                "profile_name": snapshot.model.profile_name,
                "profile_revision": snapshot.model.profile_revision,
                "selection_revision": snapshot.model.selection_revision,
                "profile": asdict(snapshot.model.profile),
            }
        catalog_payload = (
            None
            if snapshot.skill_catalog is None
            else [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "instructions": skill.instructions,
                    "allowed_tools": (
                        list(skill.allowed_tools)
                        if skill.allowed_tools is not None
                        else None
                    ),
                    "resources": [
                        {"path": resource.path, "content": resource.content}
                        for resource in skill.resources
                    ],
                    "source": skill.source,
                }
                for skill in snapshot.skill_catalog.skills
            ]
        )
        return json.dumps(
            {
                "version": 1,
                "model": model_payload,
                "skill_catalog": catalog_payload,
                "skill_catalog_hash": snapshot.skill_catalog_hash,
                "skill_creation_enabled": snapshot.skill_creation_enabled,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    def restore_context_snapshot(self, serialized: str) -> RunContextSnapshot:
        """恢复 Goal 快照；损坏或缺少恢复器时失败关闭，绝不换成当前默认值。"""
        try:
            payload = json.loads(serialized)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Stored Goal context snapshot is invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("Stored Goal context snapshot has an unsupported version")
        model_payload = payload.get("model")
        model = None
        if model_payload is not None:
            if not isinstance(model_payload, dict) or self._model_snapshot_restorer is None:
                raise ValueError("Stored Goal model snapshot cannot be restored")
            profile_payload = model_payload.get("profile")
            if not isinstance(profile_payload, dict):
                raise ValueError("Stored Goal model profile is invalid")
            from mini_deer_agent.llms import ModelProfile

            try:
                profile = ModelProfile(**profile_payload)
                profile_revision = model_payload["profile_revision"]
                selection_revision = model_payload["selection_revision"]
            except (KeyError, TypeError) as exc:
                raise ValueError("Stored Goal model snapshot is invalid") from exc
            if not isinstance(profile_revision, str) or not isinstance(
                selection_revision, int
            ):
                raise ValueError("Stored Goal model revisions are invalid")
            model = self._model_snapshot_restorer(
                profile=profile,
                profile_revision=profile_revision,
                selection_revision=selection_revision,
            )
        raw_catalog = payload.get("skill_catalog")
        catalog: BuiltInSkillCatalog | None = None
        if raw_catalog is not None:
            if not isinstance(raw_catalog, list):
                raise ValueError("Stored Goal Skill catalog is invalid")
            skills: list[BuiltInSkill] = []
            for raw_skill in raw_catalog:
                if not isinstance(raw_skill, dict):
                    raise ValueError("Stored Goal Skill entry is invalid")
                try:
                    name = raw_skill["name"]
                    description = raw_skill["description"]
                    instructions = raw_skill["instructions"]
                    source = raw_skill["source"]
                    allowed_tools = raw_skill["allowed_tools"]
                    raw_resources = raw_skill["resources"]
                except KeyError as exc:
                    raise ValueError("Stored Goal Skill entry is incomplete") from exc
                if (
                    not all(isinstance(item, str) for item in (name, description, instructions))
                    or source not in {"builtin", "user", "market"}
                    or not isinstance(raw_resources, list)
                    or (
                        allowed_tools is not None
                        and (
                            not isinstance(allowed_tools, list)
                            or not all(isinstance(item, str) for item in allowed_tools)
                        )
                    )
                ):
                    raise ValueError("Stored Goal Skill entry has invalid fields")
                resources: list[SkillResource] = []
                for raw_resource in raw_resources:
                    if (
                        not isinstance(raw_resource, dict)
                        or not isinstance(raw_resource.get("path"), str)
                        or not isinstance(raw_resource.get("content"), str)
                    ):
                        raise ValueError("Stored Goal Skill resource is invalid")
                    resources.append(
                        SkillResource(raw_resource["path"], raw_resource["content"])
                    )
                skills.append(
                    BuiltInSkill(
                        name=name,
                        description=description,
                        instructions=instructions,
                        source_file=Path(".goal-snapshot") / name / "SKILL.md",
                        allowed_tools=(
                            tuple(allowed_tools) if allowed_tools is not None else None
                        ),
                        resources=tuple(resources),
                        source=source,
                    )
                )
            catalog = BuiltInSkillCatalog(tuple(skills))
        expected_hash = payload.get("skill_catalog_hash")
        actual_hash = _catalog_hash(catalog)
        if not isinstance(expected_hash, str) or expected_hash != actual_hash:
            raise ValueError("Stored Goal Skill catalog hash does not match its content")
        skill_creation_enabled = payload.get("skill_creation_enabled", False)
        if not isinstance(skill_creation_enabled, bool):
            raise ValueError("Stored Goal Skill creation setting is invalid")
        return RunContextSnapshot(
            model,
            catalog,
            actual_hash,
            skill_creation_enabled,
        )

    def _graph_for_thread(
        self,
        thread_id: str,
        message: str,
        run_budget_tracker: RunBudgetTracker | None = None,
        model_snapshot: "ModelSnapshot | None" = None,
        skill_catalog: BuiltInSkillCatalog | None = None,
        skill_creation_enabled: bool | None = None,
    ) -> CompiledStateGraph:
        """从可信持久归属解析本轮 Scope，再为该 Thread 独立构图。"""
        file_access = (
            self._file_access_resolver(thread_id, message)
            if self._file_access_resolver is not None
            else None
        )
        if self._uses_default_graph_factory:
            return self._graph_factory(
                self._checkpointer,
                file_access,
                run_budget_tracker=run_budget_tracker,
                model_snapshot=model_snapshot,
                skill_catalog=(
                    skill_catalog
                    if skill_catalog is not None
                    else (
                        self._skill_catalog_factory()
                        if self._skill_catalog_factory is not None
                        else None
                    )
                ),
                skill_creation_enabled=skill_creation_enabled,
            )
        return self._graph_factory(self._checkpointer, file_access)

    def stream_messages(
        self,
        message: str,
        thread_id: str,
        attachments: tuple[TextAttachment, ...] = (),
    ) -> Iterator[AgentMessageEvent]:
        """恢复指定线程，只提交本轮用户消息，并惰性产生 LangGraph 消息。"""
        # 每轮构建独立 CompiledStateGraph；共享 checkpointer 负责跨轮状态和线程隔离。
        graph = self._graph_for_thread(thread_id, message)
        config = {"configurable": {"thread_id": thread_id}}
        yield from stream_agent_messages(
            graph,
            [_human_message(message, attachments)],
            config,
        )

    async def astream_messages(
        self,
        message: str,
        thread_id: str,
        attachments: tuple[TextAttachment, ...] = (),
        human_input_response: dict[str, object] | None = None,
        run_id: str | None = None,
        run_budget_tracker: RunBudgetTracker | None = None,
        internal_continuation: bool = False,
        model_snapshot: "ModelSnapshot | None" = None,
        skill_catalog: BuiltInSkillCatalog | None = None,
        skill_creation_enabled: bool | None = None,
    ) -> AsyncIterator[AgentMessageEvent]:
        """异步运行指定 Thread，供后台 asyncio Task 驱动。"""
        graph = self._graph_for_thread(
            thread_id,
            message,
            run_budget_tracker,
            model_snapshot,
            skill_catalog,
            skill_creation_enabled,
        )
        configurable = {"thread_id": thread_id}
        if run_id is not None:
            configurable["run_id"] = run_id
        config = {"configurable": configurable}
        async for event in astream_agent_messages(
            graph,
            [
                _human_message(
                    message,
                    attachments,
                    human_input_response,
                    internal_continuation,
                )
            ],
            config,
        ):
            yield event

    def bind_skill_install_authorization(
        self,
        authorization_token: str,
        *,
        thread_id: str,
        run_id: str,
    ) -> None:
        """把隐藏请求携带的一次性授权精确绑定到刚创建的产品 Run。"""
        if self._skill_management_service is None:
            raise RuntimeError("Skill install authorization is unavailable")
        self._skill_management_service.bind_automatic_authorization_to_run(
            authorization_token,
            thread_id=thread_id,
            run_id=run_id,
        )

    async def astream_run_events(
        self,
        message: str,
        thread_id: str,
        run_id: str,
        attachments: tuple[TextAttachment, ...] = (),
        human_input_response: dict[str, object] | None = None,
        *,
        run_budget_tracker: RunBudgetTracker | None = None,
        internal_continuation: bool = False,
        model_snapshot: "ModelSnapshot | None" = None,
        skill_catalog: BuiltInSkillCatalog | None = None,
        skill_creation_enabled: bool | None = None,
    ) -> AsyncIterator[RunEvent]:
        """把异步 LangGraph 消息投影为当前 Run 的版本化产品事件。"""
        active_budget_tracker = run_budget_tracker or RunBudgetTracker(
            self._run_budget_policy
        )
        active_budget_tracker.pin_run(run_id)
        projected_events = aproject_run_events(
            self.astream_messages(
                message,
                thread_id,
                attachments,
                human_input_response,
                run_id,
                active_budget_tracker,
                internal_continuation,
                model_snapshot,
                skill_catalog,
                skill_creation_enabled,
            ),
            run_id=run_id,
            thread_id=thread_id,
            terminal_payload=active_budget_tracker.terminal_payload,
        )
        async for event in projected_events:
            yield event

    def create_run_budget_tracker(self, run_id: str) -> RunBudgetTracker:
        """创建并固定可跨 Goal 隐藏续轮复用的产品 Run 预算。"""
        tracker = RunBudgetTracker(self._run_budget_policy)
        tracker.pin_run(run_id)
        return tracker
