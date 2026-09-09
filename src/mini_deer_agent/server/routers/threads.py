"""提供版本化 Thread、Run 与可见消息历史查询接口。"""

from dataclasses import asdict
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mini_deer_agent.application import (
    ActiveThreadDeleteConflictError,
    ConversationHistoryService,
    RunEventHistoryService,
    ThreadLifecycleService,
    GoalMutationConflictError,
    GoalNotFoundError,
    GoalStateService,
    CancelOutcome,
    RunExecutionManager,
)
from mini_deer_agent.domain import MessageHistoryItem, ToolExecutionHistoryItem
from mini_deer_agent.server.dependencies import (
    get_conversation_history_service,
    get_run_event_history_service,
    get_thread_lifecycle_service,
    get_goal_state_service,
    get_run_execution_manager,
)
from mini_deer_agent.server.schemas import (
    HistoryItemResponse,
    MessageHistoryItemResponse,
    RunEventResponse,
    RunResponse,
    ThreadHistoryPageResponse,
    ThreadResponse,
    ThreadTitleUpdateRequest,
    TextAttachmentResponse,
    ToolHistoryItemResponse,
    GoalResponse,
    GoalRevisionRequest,
    GoalSetRequest,
)


router = APIRouter(prefix="/api/v1/threads", tags=["threads"])


def _not_found(thread_id: str) -> HTTPException:
    """构造不泄露数据库细节的 Thread 404。"""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "thread_not_found",
            "message": f"Thread {thread_id} does not exist",
        },
    )


def _run_not_found() -> HTTPException:
    """构造不区分 Run 缺失与跨 Thread 错配的安全 404。"""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "run_not_found",
            "message": "Run does not exist in this thread",
        },
    )


def _goal_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "goal_not_found",
            "message": "This thread does not have an active goal",
        },
    )


def _goal_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "goal_conflict",
            "message": "Goal changed concurrently or its Run could not be stopped",
        },
    )


async def _cancel_run_before_goal_mutation(
    thread_id: str,
    service: GoalStateService,
    manager: RunExecutionManager,
    *,
    reason: str,
) -> None:
    """Goal 控制面必须先收敛同 Thread 的 Run，避免 revision 与 busy 状态分叉。"""
    thread = service.get_thread(thread_id)
    if thread is None:
        return
    if thread.status != "busy":
        releaser = getattr(manager, "release_goal_context", None)
        if callable(releaser):
            await releaser(thread_id)
        return
    outcome = await manager.cancel_active_run(thread_id, reason=reason)
    refreshed = service.get_thread(thread_id)
    if outcome not in {CancelOutcome.cancelled, CancelOutcome.not_cancellable}:
        raise _goal_conflict()
    if refreshed is not None and refreshed.status == "busy":
        raise _goal_conflict()


@router.get("/{thread_id}/goal", response_model=GoalResponse)
async def get_thread_goal(
    thread_id: UUID,
    service: Annotated[GoalStateService, Depends(get_goal_state_service)],
) -> GoalResponse:
    normalized_thread_id = str(thread_id)
    if service.get_thread(normalized_thread_id) is None:
        raise _not_found(normalized_thread_id)
    goal = await service.get_goal(normalized_thread_id)
    if goal is None:
        raise _goal_not_found()
    return GoalResponse.model_validate(goal)


@router.put("/{thread_id}/goal", response_model=GoalResponse)
async def set_thread_goal(
    thread_id: UUID,
    body: GoalSetRequest,
    service: Annotated[GoalStateService, Depends(get_goal_state_service)],
    manager: Annotated[
        RunExecutionManager, Depends(get_run_execution_manager)
    ],
) -> GoalResponse:
    if body.expected_revision is None:
        if await service.get_goal(str(thread_id)) is not None:
            raise _goal_conflict()
    else:
        try:
            await service.require_current_revision(
                str(thread_id), str(body.expected_revision)
            )
        except GoalNotFoundError as error:
            raise _goal_not_found() from error
        except LookupError as error:
            raise _not_found(str(thread_id)) from error
        except GoalMutationConflictError as error:
            raise _goal_conflict() from error
    await _cancel_run_before_goal_mutation(
        str(thread_id), service, manager, reason="goal_replaced"
    )
    try:
        goal = await service.set_goal(
            str(thread_id),
            objective=body.objective,
            max_continuations=body.max_continuations,
            expected_revision=(
                str(body.expected_revision)
                if body.expected_revision is not None
                else None
            ),
        )
    except GoalNotFoundError as error:
        raise _goal_not_found() from error
    except LookupError as error:
        raise _not_found(str(thread_id)) from error
    except GoalMutationConflictError as error:
        raise _goal_conflict() from error
    return GoalResponse.model_validate(goal)


@router.delete("/{thread_id}/goal", status_code=status.HTTP_204_NO_CONTENT)
async def clear_thread_goal(
    thread_id: UUID,
    revision: UUID,
    service: Annotated[GoalStateService, Depends(get_goal_state_service)],
    manager: Annotated[
        RunExecutionManager, Depends(get_run_execution_manager)
    ],
) -> None:
    try:
        await service.require_current_revision(str(thread_id), str(revision))
    except GoalNotFoundError as error:
        raise _goal_not_found() from error
    except LookupError as error:
        raise _not_found(str(thread_id)) from error
    except GoalMutationConflictError as error:
        raise _goal_conflict() from error
    await _cancel_run_before_goal_mutation(
        str(thread_id), service, manager, reason="goal_cleared"
    )
    try:
        cleared = await service.clear_goal(
            str(thread_id), expected_revision=str(revision)
        )
    except GoalNotFoundError as error:
        raise _goal_not_found() from error
    except LookupError as error:
        raise _not_found(str(thread_id)) from error
    except GoalMutationConflictError as error:
        raise _goal_conflict() from error
    if not cleared:
        raise _goal_not_found()


@router.post("/{thread_id}/goal/stop", response_model=GoalResponse)
async def stop_thread_goal(
    thread_id: UUID,
    body: GoalRevisionRequest,
    service: Annotated[GoalStateService, Depends(get_goal_state_service)],
    manager: Annotated[
        RunExecutionManager, Depends(get_run_execution_manager)
    ],
) -> GoalResponse:
    try:
        await service.require_current_revision(
            str(thread_id), str(body.revision)
        )
    except GoalNotFoundError as error:
        raise _goal_not_found() from error
    except LookupError as error:
        raise _not_found(str(thread_id)) from error
    except GoalMutationConflictError as error:
        raise _goal_conflict() from error
    await _cancel_run_before_goal_mutation(
        str(thread_id), service, manager, reason="goal_stopped"
    )
    try:
        goal = await service.stop_goal(
            str(thread_id), expected_revision=str(body.revision)
        )
    except GoalNotFoundError as error:
        raise _goal_not_found() from error
    except LookupError as error:
        raise _not_found(str(thread_id)) from error
    except GoalMutationConflictError as error:
        raise _goal_conflict() from error
    if goal is None:
        raise _goal_not_found()
    return GoalResponse.model_validate(goal)


@router.get("", response_model=list[ThreadResponse])
def list_threads(
    service: Annotated[
        ConversationHistoryService,
        Depends(get_conversation_history_service),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    scope: Literal["all", "standalone"] = "all",
) -> list[ThreadResponse]:
    """返回最近活动的产品 Thread，不读取 Checkpointer 内部状态。"""
    return [
        ThreadResponse(**asdict(record))
        for record in service.list_threads(
            limit=limit,
            offset=offset,
            standalone_only=scope == "standalone",
        )
    ]


@router.get("/{thread_id}", response_model=ThreadResponse)
def get_thread(
    thread_id: UUID,
    service: Annotated[
        ConversationHistoryService,
        Depends(get_conversation_history_service),
    ],
) -> ThreadResponse:
    """返回一个已经由服务端创建的 Thread。"""
    record = service.get_thread(str(thread_id))
    if record is None:
        raise _not_found(str(thread_id))
    return ThreadResponse(**asdict(record))


@router.patch("/{thread_id}", response_model=ThreadResponse)
def update_thread_title(
    thread_id: UUID,
    body: ThreadTitleUpdateRequest,
    service: Annotated[
        ConversationHistoryService,
        Depends(get_conversation_history_service),
    ],
) -> ThreadResponse:
    """更新业务数据库中的 Thread 标题，不触碰 LangGraph checkpoint。"""
    normalized_thread_id = str(thread_id)
    record = service.update_thread_title(normalized_thread_id, body.title)
    if record is None:
        raise _not_found(normalized_thread_id)
    return ThreadResponse(**asdict(record))


@router.delete("/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: UUID,
    service: Annotated[
        ThreadLifecycleService,
        Depends(get_thread_lifecycle_service),
    ],
) -> None:
    """删除空闲 Thread 的 checkpoint 与全部产品历史。"""
    normalized_thread_id = str(thread_id)
    try:
        deleted = await service.delete_thread(normalized_thread_id)
    except ActiveThreadDeleteConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "thread_busy",
                "message": "Thread has an active run and cannot be deleted",
            },
        ) from error
    if not deleted:
        raise _not_found(normalized_thread_id)


@router.get("/{thread_id}/runs", response_model=list[RunResponse])
def list_thread_runs(
    thread_id: UUID,
    service: Annotated[
        ConversationHistoryService,
        Depends(get_conversation_history_service),
    ],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[RunResponse]:
    """返回 Thread 最近的 Run 生命周期记录。"""
    normalized_thread_id = str(thread_id)
    if service.get_thread(normalized_thread_id) is None:
        raise _not_found(normalized_thread_id)
    return [
        RunResponse(**asdict(record))
        for record in service.list_runs(
            normalized_thread_id,
            limit=limit,
        )
    ]


@router.get("/{thread_id}/runs/{run_id}", response_model=RunResponse)
def get_thread_run(
    thread_id: UUID,
    run_id: UUID,
    service: Annotated[
        ConversationHistoryService,
        Depends(get_conversation_history_service),
    ],
) -> RunResponse:
    """返回归属于路径 Thread 的单个持久化 Run。"""
    record = service.get_run(str(thread_id), str(run_id))
    if record is None:
        raise _run_not_found()
    return RunResponse(**asdict(record))


@router.get(
    "/{thread_id}/runs/{run_id}/events",
    response_model=list[RunEventResponse],
)
def list_thread_run_events(
    thread_id: UUID,
    run_id: UUID,
    service: Annotated[
        RunEventHistoryService,
        Depends(get_run_event_history_service),
    ],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[RunEventResponse]:
    """返回归属于路径 Thread 的原始 RunEvent，供审计和后续恢复使用。"""
    records = service.list_events(
        str(thread_id),
        str(run_id),
        after_sequence=after_sequence,
        limit=limit,
    )
    if records is None:
        raise _run_not_found()
    return [RunEventResponse(**asdict(record)) for record in records]


def _history_item_response(
    item: MessageHistoryItem | ToolExecutionHistoryItem,
) -> HistoryItemResponse:
    """把领域时间线投影为不暴露数据库模型的 HTTP union。"""
    common = {
        "id": item.item_id,
        "run_id": item.run_id,
        "thread_sequence": item.thread_sequence,
        "created_at": item.created_at,
    }
    if isinstance(item, MessageHistoryItem):
        return MessageHistoryItemResponse(
            kind="message",
            role=item.role,
            content=item.content,
            reasoning=item.reasoning,
            attachments=[
                TextAttachmentResponse(**asdict(attachment))
                for attachment in item.attachments
            ],
            hidden_from_ui=item.hidden_from_ui,
            human_input_response=item.human_input_response,
            **common,
        )
    return ToolHistoryItemResponse(
        kind="tool",
        tool_call_id=item.tool_call_id,
        name=item.name,
        input=item.input,
        result=item.result,
        status=item.status,
        **common,
    )


@router.get(
    "/{thread_id}/messages",
    response_model=ThreadHistoryPageResponse,
)
def list_thread_messages(
    thread_id: UUID,
    service: Annotated[
        ConversationHistoryService,
        Depends(get_conversation_history_service),
    ],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    before_sequence: Annotated[int | None, Query(ge=1)] = None,
) -> ThreadHistoryPageResponse:
    """返回一页可见历史；尚未提交过消息的本地 Thread 返回空页。"""
    page = service.list_history(
        str(thread_id),
        limit=limit,
        before_sequence=before_sequence,
    )
    return ThreadHistoryPageResponse(
        thread_id=page.thread_id,
        thread_exists=page.thread_exists,
        items=[_history_item_response(item) for item in page.items],
        has_more=page.has_more,
        next_before_sequence=page.next_before_sequence,
    )
