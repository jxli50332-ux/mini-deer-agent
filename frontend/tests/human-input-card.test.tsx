import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  HumanInputChoiceRequest,
  HumanInputFormRequest,
} from "@/features/chat/model/human-input";
import { HumanInputCard } from "@/features/chat/ui/HumanInputCard";

const REQUEST: HumanInputChoiceRequest = {
  version: 1,
  kind: "human_input_request",
  source: "ask_clarification",
  requestId: "clarification:call-1",
  clarificationType: "approach_choice",
  question: "请选择输出格式",
  context: "不同格式会影响后续排版。",
  inputMode: "choice_with_other",
  options: [
    { id: "option-1", label: "Markdown", value: "Markdown" },
    { id: "option-2", label: "纯文本", value: "纯文本" },
  ],
};

const FORM_REQUEST: HumanInputFormRequest = {
  version: 2,
  kind: "human_input_request",
  source: "ask_clarification",
  requestId: "clarification:form-1",
  clarificationType: "missing_info",
  question: "请补充发布说明参数",
  inputMode: "form",
  fields: [
    {
      name: "project_name",
      label: "项目名",
      type: "text",
      required: true,
      placeholder: "例如 Mini Deer",
    },
    {
      name: "format",
      label: "输出格式",
      type: "select",
      required: true,
      options: [
        { id: "format-option-1", label: "Markdown", value: "Markdown" },
        { id: "format-option-2", label: "纯文本", value: "纯文本" },
      ],
    },
    {
      name: "notes",
      label: "补充说明",
      type: "textarea",
      required: false,
    },
  ],
};

const EXTENDED_FORM_REQUEST: HumanInputFormRequest = {
  version: 2,
  kind: "human_input_request",
  source: "ask_clarification",
  requestId: "clarification:extended-form",
  clarificationType: "missing_info",
  question: "请补充活动参数",
  inputMode: "form",
  fields: [
    { name: "budget", label: "预算", type: "number", required: true },
    {
      name: "due_date",
      label: "截止日期",
      type: "date",
      required: true,
    },
    {
      name: "channels",
      label: "发布渠道",
      type: "multi_select",
      required: true,
      options: [
        { id: "channels-option-1", label: "网站", value: "web" },
        { id: "channels-option-2", label: "邮件", value: "email" },
      ],
    },
    { name: "urgent", label: "加急", type: "checkbox", required: false },
    {
      name: "terms",
      label: "同意发布条款",
      type: "checkbox",
      required: true,
    },
  ],
};

describe("HumanInputCard", () => {
  it("直接提交选项，并提供可填写的其他答案", async () => {
    const onSubmit = vi.fn(() => Promise.resolve(true));
    render(<HumanInputCard request={REQUEST} onSubmit={onSubmit} />);

    expect(screen.getByRole("group", { name: "需要你确认" })).toHaveTextContent(
      "请选择输出格式",
    );
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        version: 1,
        kind: "human_input_response",
        request_id: "clarification:call-1",
        response_kind: "option",
        option_id: "option-1",
        value: "Markdown",
      }),
    );
  });

  it("已回答卡片只展示答案，不允许重复提交", () => {
    render(
      <HumanInputCard
        request={REQUEST}
        answeredResponse={{
          version: 1,
          kind: "human_input_response",
          request_id: "clarification:call-1",
          response_kind: "text",
          value: "请同时提供两种格式",
        }}
      />,
    );

    expect(screen.getByText("已回答")).toBeInTheDocument();
    expect(screen.getByText("请同时提供两种格式")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Markdown" })).toBeNull();
  });

  it("表单拦截缺失必填字段，并以 v1 text response 提交完整映射", async () => {
    const onSubmit = vi.fn(() => Promise.resolve(true));
    render(<HumanInputCard request={FORM_REQUEST} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请填写所有必填字段");
    expect(onSubmit).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("textbox", { name: /项目名/ }), {
      target: { value: "Mini Deer" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /输出格式/ }), {
      target: { value: "Markdown" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: /补充说明/ }), {
      target: { value: "面向开发者" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        version: 1,
        kind: "human_input_response",
        request_id: "clarification:form-1",
        response_kind: "text",
        value:
          '项目名: Mini Deer; 输出格式: Markdown; 补充说明: 面向开发者 [values: {"project_name":"Mini Deer","format":"Markdown","notes":"面向开发者"}]',
      }),
    );
  });

  it("渲染并提交 number、date、multi_select、checkbox", async () => {
    const onSubmit = vi.fn(() => Promise.resolve(true));
    render(
      <HumanInputCard request={EXTENDED_FORM_REQUEST} onSubmit={onSubmit} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));
    expect(screen.getByRole("alert")).toHaveTextContent("请填写所有必填字段");

    fireEvent.change(screen.getByRole("spinbutton", { name: /预算/ }), {
      target: { value: "300.5" },
    });
    fireEvent.change(screen.getByLabelText(/截止日期/), {
      target: { value: "2026-09-15" },
    });
    fireEvent.click(screen.getByRole("button", { name: "网站" }));
    fireEvent.click(screen.getByRole("button", { name: "邮件" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /同意发布条款/ }));

    expect(screen.getByRole("button", { name: "网站" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("checkbox", { name: /加急/ })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "提交回答" }));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        version: 1,
        kind: "human_input_response",
        request_id: "clarification:extended-form",
        response_kind: "text",
        value:
          '预算: 300.5; 截止日期: 2026-09-15; 发布渠道: web, email; 加急: 否; 同意发布条款: 是 [values: {"budget":"300.5","due_date":"2026-09-15","channels":["web","email"],"urgent":false,"terms":true}]',
      }),
    );
  });
});
