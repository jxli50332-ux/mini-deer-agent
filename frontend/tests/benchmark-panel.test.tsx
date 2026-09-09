import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BenchmarkPanel } from "@/features/benchmarks/ui/BenchmarkPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("能力基准面板", () => {
  it("加载固定任务，并阻止未打开项目时选择项目案例", async () => {
    const fetcher = vi.fn((input: RequestInfo | URL) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      if (url.endsWith("/cases")) {
        return Promise.resolve(
          Response.json([
            {
              case_id: "simple-qa",
              title: "简单问答",
              category: "simple_qa",
              prompt: "解释幂等",
              expected_behavior: "直接回答",
              requires_project: false,
            },
            {
              case_id: "single-file-fix",
              title: "单文件缺陷修复",
              category: "coding",
              prompt: "修复缺陷",
              expected_behavior: "复现并检查",
              requires_project: true,
            },
          ]),
        );
      }
      if (url.endsWith("/regression")) {
        return Promise.resolve(
          Response.json({
            version: 1,
            case_count: 8,
            rerun_case_count: 3,
            all_cases_rerun: false,
            ready_to_close: false,
            baseline: {
              run_count: 4,
              evaluated_complex_cases: 1,
              completed_complex_cases: 0,
              complex_completion_rate: 0,
              repeated_tool_calls: 2,
              simple_qa_tool_calls: null,
              p95_duration_ms: null,
              p95_total_tokens: null,
            },
            current: {
              run_count: 4,
              evaluated_complex_cases: 1,
              completed_complex_cases: 1,
              complex_completion_rate: 1,
              repeated_tool_calls: 0,
              simple_qa_tool_calls: null,
              p95_duration_ms: null,
              p95_total_tokens: null,
            },
            gates: {
              complex_completion: "insufficient_data",
              convergence: "insufficient_data",
              simple_tool_calls: "insufficient_data",
              p95_duration: "insufficient_data",
              p95_tokens: "insufficient_data",
            },
          }),
        );
      }
      return Promise.resolve(Response.json([]));
    });
    vi.stubGlobal("fetch", fetcher);
    const onUseCase = vi.fn();

    render(
      <BenchmarkPanel
        open
        hasProject={false}
        onClose={vi.fn()}
        onUseCase={onUseCase}
      />,
    );

    await waitFor(() => expect(screen.getByText("简单问答")).toBeVisible());
    expect(screen.getByText(/已复测 3\/8/)).toBeVisible();
    expect(screen.getAllByText(/数据不足/)).toHaveLength(5);
    expect(screen.getByText("简单问答工具调用")).toBeVisible();
    expect(screen.getByRole("button", { name: "请先打开项目" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "填入固定输入" }));
    expect(onUseCase).toHaveBeenCalledWith(
      expect.objectContaining({ caseId: "simple-qa" }),
    );
  });
});
