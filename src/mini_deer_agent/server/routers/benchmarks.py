"""暴露固定能力基准目录、运行报告和人工评分。"""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from mini_deer_agent.application import BenchmarkReport, BenchmarkService
from mini_deer_agent.server.dependencies import get_benchmark_service
from mini_deer_agent.server.schemas import (
    BenchmarkCaseResponse,
    BenchmarkReportResponse,
    BenchmarkRegressionSummaryResponse,
    BenchmarkScoreRequest,
)


router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])


def _response(report: BenchmarkReport) -> BenchmarkReportResponse:
    return BenchmarkReportResponse(**asdict(report))


@router.get("/cases", response_model=list[BenchmarkCaseResponse])
def list_benchmark_cases(
    service: Annotated[BenchmarkService, Depends(get_benchmark_service)],
) -> list[BenchmarkCaseResponse]:
    return [BenchmarkCaseResponse(**asdict(case)) for case in service.list_cases()]


@router.get("/attempts", response_model=list[BenchmarkReportResponse])
def list_benchmark_attempts(
    service: Annotated[BenchmarkService, Depends(get_benchmark_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[BenchmarkReportResponse]:
    return [_response(report) for report in service.list_reports(limit=limit)]


@router.get("/regression", response_model=BenchmarkRegressionSummaryResponse)
def get_benchmark_regression(
    service: Annotated[BenchmarkService, Depends(get_benchmark_service)],
) -> BenchmarkRegressionSummaryResponse:
    """返回固定口径的最早基线与每案例最新复测对比。"""
    return BenchmarkRegressionSummaryResponse(
        **asdict(service.regression_summary())
    )


@router.get("/attempts/{run_id}", response_model=BenchmarkReportResponse)
def get_benchmark_attempt(
    run_id: UUID,
    service: Annotated[BenchmarkService, Depends(get_benchmark_service)],
) -> BenchmarkReportResponse:
    report = service.get_report(str(run_id))
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "benchmark_attempt_not_found", "message": "Benchmark attempt does not exist"},
        )
    return _response(report)


@router.patch("/attempts/{run_id}/score", response_model=BenchmarkReportResponse)
def score_benchmark_attempt(
    run_id: UUID,
    request: BenchmarkScoreRequest,
    service: Annotated[BenchmarkService, Depends(get_benchmark_service)],
) -> BenchmarkReportResponse:
    report = service.score(
        str(run_id),
        task_completed=request.task_completed,
        score=request.score,
        notes=request.notes,
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "benchmark_attempt_not_found", "message": "Benchmark attempt does not exist"},
        )
    return _response(report)
