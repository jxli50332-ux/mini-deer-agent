"""Agent 可见但不能安装的受限 Skill 草稿工具。"""

import json
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from mini_deer_agent.skills.management import SkillDraftPayload, SkillManagementService


def create_skill_manage_tool(service: SkillManagementService) -> BaseTool:
    def resource_pairs(
        resources: list[dict[str, str]] | None,
    ) -> tuple[tuple[str, str], ...]:
        if resources is None:
            return ()
        pairs: list[tuple[str, str]] = []
        for item in resources:
            if set(item) != {"path", "content"}:
                raise ValueError("Each resource requires only path and content")
            pairs.append((item["path"], item["content"]))
        return tuple(pairs)

    def run_context(config: RunnableConfig) -> tuple[str, str]:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        run_id = configurable.get("run_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Automatic install requires the current thread context")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("Automatic install requires the current run context")
        return thread_id, run_id

    def resolved_authorization_token(
        config: RunnableConfig,
        provided: str | None,
        *,
        name: str,
        draft_id: str | None = None,
    ) -> str | None:
        if provided is not None:
            return provided
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        run_id = configurable.get("run_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None
        if not isinstance(run_id, str) or not run_id:
            return None
        return service.automatic_authorization_token_for_run(
            thread_id=thread_id,
            run_id=run_id,
            expected_name=name,
            draft_id=draft_id,
        )

    @tool("skill_manage")
    def skill_manage(
        config: RunnableConfig,
        action: Literal["create_draft", "update_draft", "validate_draft", "request_install"],
        draft_id: str | None = None,
        revision: int | None = None,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        allowed_tools: list[str] | None = None,
        resources: list[dict[str, str]] | None = None,
        authorization_token: str | None = None,
    ) -> str:
        """创建、更新或检查用户 Skill 草稿；仅一次性自动授权可直接安装新 Skill。"""
        service.require_agent_creation_enabled()
        if action == "create_draft":
            if not name or not description or not instructions:
                raise ValueError("create_draft requires name, description and instructions")
            automatic_token = resolved_authorization_token(
                config,
                authorization_token,
                name=name,
            )
            if automatic_token is not None:
                thread_id, run_id = run_context(config)
                service.bind_automatic_authorization(
                    automatic_token,
                    thread_id=thread_id,
                    run_id=run_id,
                    expected_name=name,
                )
            record = service.create_draft(
                SkillDraftPayload(
                    name,
                    description,
                    instructions,
                    tuple(allowed_tools) if allowed_tools is not None else None,
                    resource_pairs(resources),
                ),
                author="agent",
            )
            if automatic_token is not None:
                thread_id, run_id = run_context(config)
                service.bind_automatic_authorization(
                    automatic_token,
                    thread_id=thread_id,
                    run_id=run_id,
                    expected_name=record.payload.name,
                    draft_id=record.draft_id,
                )
            return json.dumps({"status": "draft_created", "draft_id": record.draft_id, "revision": record.revision, "name": record.payload.name}, ensure_ascii=False)
        if not draft_id:
            raise ValueError(f"{action} requires draft_id")
        if action == "update_draft":
            if revision is None or not name or not description or not instructions:
                raise ValueError("update_draft requires revision, name, description and instructions")
            service.require_agent_draft(draft_id)
            record = service.update_draft(
                draft_id,
                SkillDraftPayload(
                    name,
                    description,
                    instructions,
                    tuple(allowed_tools) if allowed_tools is not None else None,
                    resource_pairs(resources),
                ),
                expected_revision=revision,
            )
            return json.dumps({"status": "draft_updated", "draft_id": record.draft_id, "revision": record.revision}, ensure_ascii=False)
        result = service.check_draft(draft_id)
        record = next(
            item for item in service.list_drafts() if item.draft_id == draft_id
        )
        automatic_token = resolved_authorization_token(
            config,
            authorization_token,
            name=record.payload.name,
            draft_id=draft_id,
        )
        if action == "validate_draft":
            if automatic_token is not None and result.valid and result.content_hash:
                thread_id, run_id = run_context(config)
                service.bind_automatic_authorization(
                    automatic_token,
                    thread_id=thread_id,
                    run_id=run_id,
                    expected_name=record.payload.name,
                    draft_id=draft_id,
                    content_hash=result.content_hash,
                )
            return json.dumps({"status": "validated", "valid": result.valid, "errors": result.errors, "warnings": result.warnings, "content_hash": result.content_hash}, ensure_ascii=False)
        if automatic_token is not None:
            if not result.valid:
                return json.dumps(
                    {
                        "status": "validation_failed",
                        "valid": False,
                        "draft_id": draft_id,
                        "errors": result.errors,
                    },
                    ensure_ascii=False,
                )
            thread_id, run_id = run_context(config)
            detail, content_hash = service.install_authorized_draft(
                draft_id,
                authorization_token=automatic_token,
                thread_id=thread_id,
                run_id=run_id,
            )
            return json.dumps(
                {
                    "status": "installed",
                    "name": detail.name,
                    "enabled": detail.enabled,
                    "content_hash": content_hash,
                    "message": "Skill 已安装并启用，将从下一次 Run 开始生效。",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "confirmation_required",
                "valid": result.valid,
                "draft_id": draft_id,
                "content_hash": result.content_hash,
                "message": "请用户在设置 → Skills → 草稿中检查并确认安装。",
            },
            ensure_ascii=False,
        )

    return skill_manage


__all__ = ["create_skill_manage_tool"]
