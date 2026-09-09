"""提供版本化 Agent run SSE 接口和旧聊天接口兼容层。"""

from collections.abc import AsyncIterable, Iterable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse

from mini_deer_agent.application import (
    ActiveRunConflictError,
    CancelOutcome,
    GoalMutationConflictError,
    GoalNotFoundError,
    GoalStateService,
    RunExecutionManager,
    RunStreamService,
)
from mini_deer_agent.server.dependencies import (
    get_goal_state_service,
    get_run_execution_manager,
    get_run_stream_service,
)
from mini_deer_agent.server.schemas import (
    GoalResumeRequest,
    LegacyChatStreamRequest,
    RunStreamRequest,
)
from mini_deer_agent.streaming import aiter_run_sse_frames, aiter_sse_frames


router = APIRouter(prefix="/api/v1/threads", tags=["runs"])
legacy_router = APIRouter()

# 所有流式端点复用同一组代理提示，避免新增路由时遗漏禁用缓冲配置。
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _streaming_response(
    frames: Iterable[str] | AsyncIterable[str],
    *,
    run_id: str | None = None,
) -> StreamingResponse:
    """创建统一 SSE 响应，并在 v1 响应头中暴露本轮 run ID。"""
    headers = dict(SSE_HEADERS)
    if run_id is not None:
        # run ID 不是授权凭证，只用于客户端状态关联、日志和未来取消接口。
        headers["X-Run-ID"] = run_id
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers=headers,
    )


def _goal_resume_failure(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_404_NOT_FOUND
            if code in {"thread_not_found", "goal_not_found"}
            else status.HTTP_409_CONFLICT
        ),
        detail={"code": code, "message": message},
    )


@router.post("/{thread_id}/runs/stream")
async def stream_thread_run(
    thread_id: UUID,
    request: RunStreamRequest,
    run_manager: Annotated[
        RunExecutionManager,
        Depends(get_run_execution_manager),
    ],
) -> StreamingResponse:
    """为指定线程启动 run，并返回带版本、ID 和序号的 SSE 事件。"""
    try:
        benchmark_kwargs = (
            {"benchmark_case_id": request.benchmark_case_id}
            if request.benchmark_case_id is not None
            else {}
        )
        started_run = await run_manager.start_run(
            request.message,
            str(thread_id),
            str(request.message_id),
            request.to_domain_attachments(),
            request.to_domain_human_input_response(),
            **benchmark_kwargs,
        )
    except ActiveRunConflictError as exc:
        # 并发 Run 和重复客户端消息 ID 都是稳定冲突，不能作为内部异常泄露。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "run_conflict",
                "message": "Thread already has an active run",
            },
        ) from exc
    return _streaming_response(
        aiter_run_sse_frames(started_run.events),
        run_id=started_run.run_id,
    )


@router.post("/{thread_id}/goal/resume", tags=["goals"])
async def resume_thread_goal(
    thread_id: UUID,
    request: GoalResumeRequest,
    goal_service: Annotated[GoalStateService, Depends(get_goal_state_service)],
    run_manager: Annotated[
        RunExecutionManager,
        Depends(get_run_execution_manager),
    ],
) -> StreamingResponse:
    """显式恢复 Goal，并以隐藏控制消息立即启动新的产品 Run。"""
    normalized_thread_id = str(thread_id)
    if goal_service.get_thread(normalized_thread_id) is None:
        raise _goal_resume_failure("thread_not_found", "Thread does not exist")
    try:
        previous_goal = await goal_service.require_current_revision(
            normalized_thread_id,
            str(request.revision),
        )
        goal = await goal_service.resume_goal(
            normalized_thread_id,
            expected_revision=str(request.revision),
        )
    except GoalNotFoundError as exc:
        raise _goal_resume_failure("goal_not_found", "Goal does not exist") from exc
    except LookupError as exc:
        raise _goal_resume_failure("thread_not_found", "Thread does not exist") from exc
    except GoalMutationConflictError as exc:
        raise _goal_resume_failure(
            "goal_conflict", "Goal changed before it could be resumed"
        ) from exc

    continuation_message = (
        "[Goal continuation] 用户通过 Goal 控制栏明确要求恢复并继续执行。"
        f"继续完成线程目标：{goal['objective']}\n"
        "这是 Runtime 控制消息，不是新的用户对话内容。"
    )
    try:
        started_run = await run_manager.start_run(
            continuation_message,
            normalized_thread_id,
            str(request.message_id),
            internal_continuation=True,
        )
    except ActiveRunConflictError as exc:
        await goal_service.restore_after_failed_resume(
            normalized_thread_id,
            failed_revision=goal["revision"],
            previous_goal=previous_goal,
        )
        raise _goal_resume_failure(
            "run_conflict", "Thread already has an active run"
        ) from exc
    except BaseException:
        # Goal 和 Run 位于两个存储。启动在写入 Goal 后失败时，仅在 Thread
        # 仍空闲且 revision 未被后续操作替换的情况下恢复原状态。
        thread = goal_service.get_thread(normalized_thread_id)
        if thread is None or thread.status != "busy":
            await goal_service.restore_after_failed_resume(
                normalized_thread_id,
                failed_revision=goal["revision"],
                previous_goal=previous_goal,
            )
        raise
    return _streaming_response(
        aiter_run_sse_frames(started_run.events),
        run_id=started_run.run_id,
    )


@router.post(
    "/{thread_id}/runs/{run_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_thread_run(
    thread_id: UUID,
    run_id: UUID,
    run_manager: Annotated[
        RunExecutionManager,
        Depends(get_run_execution_manager),
    ],
) -> Response:
    """幂等取消当前进程拥有的 pending 或 running Run。"""
    outcome = await run_manager.cancel_run(str(thread_id), str(run_id))
    if outcome is CancelOutcome.cancelled:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if outcome is CancelOutcome.not_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "run_not_found",
                "message": "Run does not exist in this thread",
            },
        )
    if outcome is CancelOutcome.not_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "run_not_active",
                "message": "Run is not active on this worker",
            },
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "run_not_cancellable",
            "message": "Run has already reached a non-interrupted terminal state",
        },
    )


@legacy_router.post("/chat/stream", include_in_schema=False)
async def legacy_chat_stream(
    request: LegacyChatStreamRequest,
    run_service: Annotated[
        RunStreamService,
        Depends(get_run_stream_service),
    ],
) -> StreamingResponse:
    """保持原请求体和原 SSE 字节格式，供历史课程与脚本迁移使用。"""
    message_events = run_service.astream_messages(
        request.message,
        request.thread_id,
    )
    return _streaming_response(aiter_sse_frames(message_events))
