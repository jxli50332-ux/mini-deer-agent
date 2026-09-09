"""线程级 Goal 状态与变更请求契约。"""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mini_deer_agent.application import (
    DEFAULT_MAX_CONTINUATIONS,
    MAX_GOAL_CONTINUATIONS,
    MAX_GOAL_OBJECTIVE_CHARS,
)


class GoalSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=MAX_GOAL_OBJECTIVE_CHARS)
    max_continuations: int = Field(
        default=DEFAULT_MAX_CONTINUATIONS,
        ge=1,
        le=MAX_GOAL_CONTINUATIONS,
    )
    expected_revision: UUID | None = None


class GoalRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: UUID


class GoalResumeRequest(GoalRevisionRequest):
    message_id: UUID


class GoalEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    satisfied: bool
    blocker: Literal[
        "none",
        "missing_evidence",
        "needs_user_input",
        "run_failed",
        "external_wait",
        "goal_not_met_yet",
    ]
    reason: str = Field(min_length=1)
    evidence_summary: str = Field(min_length=1)
    evaluated_at: datetime


class GoalResponse(BaseModel):
    version: Literal[1]
    revision: UUID
    objective: str = Field(min_length=1, max_length=MAX_GOAL_OBJECTIVE_CHARS)
    continuation_count: int = Field(ge=0)
    max_continuations: int = Field(ge=1, le=MAX_GOAL_CONTINUATIONS)
    no_progress_count: int = Field(ge=0)
    last_evaluation: GoalEvaluationResponse | None
    status: Literal["active", "paused", "stopped", "completed"]
    stop_reason: str | None = Field(default=None, min_length=1)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_state_invariants(self) -> Self:
        if self.continuation_count > self.max_continuations:
            raise ValueError("continuation_count exceeds max_continuations")
        if self.status in {"active", "completed"} and self.stop_reason is not None:
            raise ValueError("active/completed Goal cannot have stop_reason")
        if self.status in {"paused", "stopped"} and self.stop_reason is None:
            raise ValueError("paused/stopped Goal requires stop_reason")
        if self.status == "completed" and (
            self.last_evaluation is None or not self.last_evaluation.satisfied
        ):
            raise ValueError("completed Goal requires satisfied evaluation")
        return self
