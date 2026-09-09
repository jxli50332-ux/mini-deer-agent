"""定义固定能力基准及其可持久化的人工评分。"""

from dataclasses import dataclass
from typing import Literal


type BenchmarkCategory = Literal[
    "simple_qa",
    "clarification",
    "research",
    "convergence",
    "output_budget",
    "coding",
    "delegation",
]


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """一个跨版本保持稳定、可从真实页面发起的基准输入。"""

    case_id: str
    title: str
    category: BenchmarkCategory
    prompt: str
    expected_behavior: str
    requires_project: bool = False


@dataclass(frozen=True, slots=True)
class BenchmarkScore:
    """人工验收结论；空值表示尚未评分。"""

    task_completed: bool | None
    score: int | None
    notes: str | None
    scored_at: str | None


@dataclass(frozen=True, slots=True)
class BenchmarkAttempt:
    """一次与普通 Run 共用事实链的基准运行摘要。"""

    case_id: str
    run_id: str
    thread_id: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    finish_reason: str | None
    error_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    model_calls: int | None
    task_completed: bool | None
    score: int | None
    notes: str | None
    scored_at: str | None


BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        case_id="simple-qa",
        title="简单问答",
        category="simple_qa",
        prompt="请用不超过三句话解释什么是幂等操作，并给出一个 HTTP 示例。",
        expected_behavior="直接给出准确、简短的回答，不调用工具或创建 Todo。",
    ),
    BenchmarkCase(
        case_id="ambiguous-request",
        title="模糊需求澄清",
        category="clarification",
        prompt="帮我规划一次旅行。",
        expected_behavior="先澄清目的地、日期或预算等会实质改变方案的条件。",
    ),
    BenchmarkCase(
        case_id="multi-source-research",
        title="多源调研",
        category="research",
        prompt=(
            "调研 Python 3.13 free-threaded CPython 的当前限制与适用场景。"
            "请分解问题，搜索并深读至少两个一手来源，最后给出可核验引用。"
        ),
        expected_behavior="分解、搜索、读取多个一手来源并在结论中正确引用。",
    ),
    BenchmarkCase(
        case_id="repeated-empty-results",
        title="重复空结果",
        category="convergence",
        prompt=(
            "查找名称为 mini-deer-benchmark-no-result-9f41 的公开项目。"
            "如果搜索没有结果，请改变查询策略；仍无证据时明确收尾，不要原样重试。"
        ),
        expected_behavior="空结果后改变查询或工具，并在证据不足时停止扩张。",
    ),
    BenchmarkCase(
        case_id="large-tool-output",
        title="超长工具输出",
        category="output_budget",
        prompt=(
            "在当前项目中生成或读取一份超过 100KB 的结构化命令输出，"
            "定位其中最后一个 error 字段并说明依据；不要把完整输出复制到回答。"
        ),
        expected_behavior="保留结构摘要，通过续读定位关键段，最终回答保持有界。",
        requires_project=True,
    ),
    BenchmarkCase(
        case_id="single-file-fix",
        title="单文件缺陷修复",
        category="coding",
        prompt=(
            "在当前项目中选择一个已有失败测试对应的单文件缺陷：先复现，"
            "只修改必要文件，运行聚焦检查并交付变更与结果。若没有失败测试则说明阻塞。"
        ),
        expected_behavior="先复现，再做最小修改并运行聚焦检查。",
        requires_project=True,
    ),
    BenchmarkCase(
        case_id="small-multi-file-feature",
        title="多文件小功能",
        category="coding",
        prompt=(
            "在当前项目选择一个明确的小型待办，定位最小文件集合，实现后补充聚焦测试；"
            "不要顺带重构无关代码。若没有明确待办则先说明阻塞。"
        ),
        expected_behavior="定位最小文件集合，实现小功能并补充、运行聚焦测试。",
        requires_project=True,
    ),
    BenchmarkCase(
        case_id="parallel-delegation",
        title="并发委派",
        category="delegation",
        prompt=(
            "把任务拆成两个互不依赖的子任务并并发委派：一个调研 Python 3.13 free-threading，"
            "另一个只读定位当前项目的测试入口；最后综合两边结果。"
        ),
        expected_behavior="并行完成独立任务，保留部分结果并正确综合。",
        requires_project=True,
    ),
)


BENCHMARK_CASES_BY_ID = {case.case_id: case for case in BENCHMARK_CASES}


def require_benchmark_case(case_id: str) -> BenchmarkCase:
    """返回可信的固定案例，拒绝客户端自造案例身份。"""
    try:
        return BENCHMARK_CASES_BY_ID[case_id]
    except KeyError as exc:
        raise ValueError("Unknown benchmark case") from exc
