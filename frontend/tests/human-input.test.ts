import { describe, expect, it } from "vitest";

import type { ChatTimelineItem } from "@/entities/message/model/types";
import {
  buildInitialHumanInputFormValues,
  buildHumanInputResponseText,
  buildHumanInputFormSubmissionValue,
  deriveHumanInputThreadState,
  findMissingRequiredHumanInputFields,
  parseHumanInputRequest,
  type HumanInputResponse,
} from "@/features/chat/model/human-input";

const FORM_REQUEST = {
  version: 2,
  kind: "human_input_request",
  source: "ask_clarification",
  request_id: "clarification:form-1",
  clarification_type: "missing_info",
  question: "请补充发布说明参数。",
  input_mode: "form",
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
} as const;

const EXTENDED_FORM_REQUEST = {
  version: 2,
  kind: "human_input_request",
  source: "ask_clarification",
  request_id: "clarification:extended-form",
  clarification_type: "missing_info",
  question: "请补充活动参数。",
  input_mode: "form",
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
} as const;

const CHOICE_REQUEST = {
  version: 1,
  kind: "human_input_request",
  source: "ask_clarification",
  request_id: "clarification:call-1",
  clarification_type: "approach_choice",
  question: "你希望采用哪种输出格式？",
  input_mode: "choice_with_other",
  options: [
    { id: "option-1", label: "Markdown", value: "Markdown" },
    { id: "option-2", label: "纯文本", value: "纯文本" },
  ],
} as const;

const RESPONSE: HumanInputResponse = {
  version: 1,
  kind: "human_input_response",
  request_id: "clarification:call-1",
  response_kind: "option",
  option_id: "option-1",
  value: "Markdown",
};

function clarificationTool(): ChatTimelineItem {
  return {
    kind: "tool",
    id: "tool-1",
    toolCallId: "call-1",
    name: "ask_clarification",
    input: "{}",
    result: JSON.stringify(CHOICE_REQUEST),
    status: "completed",
  };
}

describe("Human Input v1 协议", () => {
  it("只把完整的 free_text / choice_with_other 请求解析为结构化卡片", () => {
    expect(parseHumanInputRequest(CHOICE_REQUEST)).toEqual({
      version: 1,
      kind: "human_input_request",
      source: "ask_clarification",
      requestId: "clarification:call-1",
      clarificationType: "approach_choice",
      question: "你希望采用哪种输出格式？",
      inputMode: "choice_with_other",
      options: [
        { id: "option-1", label: "Markdown", value: "Markdown" },
        { id: "option-2", label: "纯文本", value: "纯文本" },
      ],
    });
    expect(
      parseHumanInputRequest({ ...CHOICE_REQUEST, version: 2 }),
    ).toBeNull();
    expect(
      parseHumanInputRequest({ ...CHOICE_REQUEST, options: [] }),
    ).toBeNull();
  });

  it("隐藏回答按 request_id 精确关闭卡片，普通可见消息兼容关闭最新卡片", () => {
    const exactTimeline: readonly ChatTimelineItem[] = [
      clarificationTool(),
      {
        kind: "message",
        id: "answer-1",
        role: "user",
        content: "我选择 Markdown",
        hiddenFromUi: true,
        humanInputResponse: RESPONSE,
      },
    ];
    const exactState = deriveHumanInputThreadState(exactTimeline);
    expect(exactState.answeredResponses.get("clarification:call-1")).toEqual(
      RESPONSE,
    );
    expect(exactState.latestOpenRequestId).toBeNull();

    const fallbackState = deriveHumanInputThreadState([
      clarificationTool(),
      {
        kind: "message",
        id: "answer-visible",
        role: "user",
        content: "请使用纯文本",
      },
    ]);
    expect(
      fallbackState.answeredResponses.get("clarification:call-1"),
    ).toMatchObject({ response_kind: "text", value: "请使用纯文本" });
  });

  it("为下一 Run 生成同时包含问题和答案的可读正文", () => {
    const request = parseHumanInputRequest(CHOICE_REQUEST);
    expect(request).not.toBeNull();
    expect(buildHumanInputResponseText(request!, RESPONSE)).toBe(
      "针对澄清问题“你希望采用哪种输出格式？”，我的回答是：Markdown",
    );
  });
});

describe("Human Input v2 form 协议", () => {
  it("严格绑定 version 2 与 form，并拒绝危险或不完整字段", () => {
    expect(parseHumanInputRequest(FORM_REQUEST)).toMatchObject({
      version: 2,
      requestId: "clarification:form-1",
      inputMode: "form",
      fields: [
        { name: "project_name", type: "text", required: true },
        { name: "format", type: "select", required: true },
        { name: "notes", type: "textarea", required: false },
      ],
    });
    expect(parseHumanInputRequest({ ...FORM_REQUEST, version: 1 })).toBeNull();
    expect(
      parseHumanInputRequest({
        ...FORM_REQUEST,
        input_mode: "free_text",
        fields: undefined,
      }),
    ).toBeNull();
    expect(
      parseHumanInputRequest({
        ...FORM_REQUEST,
        fields: [{ name: "constructor", label: "危险", type: "text" }],
      }),
    ).toBeNull();
  });

  it("把可读摘要与按稳定字段名编码的 JSON 一起提交", () => {
    const request = parseHumanInputRequest(FORM_REQUEST);
    expect(request?.inputMode).toBe("form");
    expect(
      buildHumanInputFormSubmissionValue(request!, {
        project_name: "Mini Deer",
        format: "Markdown",
        notes: "面向开发者",
      }),
    ).toBe(
      '项目名: Mini Deer; 输出格式: Markdown; 补充说明: 面向开发者 [values: {"project_name":"Mini Deer","format":"Markdown","notes":"面向开发者"}]',
    );
  });

  it("解析四种扩展字段，并按各自空值语义校验必填项", () => {
    const request = parseHumanInputRequest(EXTENDED_FORM_REQUEST);
    expect(request?.inputMode).toBe("form");
    if (request?.inputMode !== "form") {
      throw new Error("扩展字段请求应解析为 form");
    }
    expect(request).toMatchObject({
      fields: [
        { name: "budget", type: "number" },
        { name: "due_date", type: "date" },
        { name: "channels", type: "multi_select" },
        { name: "urgent", type: "checkbox" },
        { name: "terms", type: "checkbox" },
      ],
    });
    expect(buildInitialHumanInputFormValues(request.fields)).toEqual({
      urgent: false,
      terms: false,
    });
    expect(
      findMissingRequiredHumanInputFields(
        request,
        buildInitialHumanInputFormValues(request.fields),
      ).map((field) => field.name),
    ).toEqual(["budget", "due_date", "channels", "terms"]);
    expect(
      parseHumanInputRequest({
        ...EXTENDED_FORM_REQUEST,
        fields: [
          {
            name: "channels",
            label: "发布渠道",
            type: "multi_select",
            required: false,
          },
        ],
      }),
    ).toBeNull();
    expect(
      parseHumanInputRequest({
        ...EXTENDED_FORM_REQUEST,
        fields: [
          {
            name: "urgent",
            label: "加急",
            type: "checkbox",
            required: false,
            options: EXTENDED_FORM_REQUEST.fields[2].options,
          },
        ],
      }),
    ).toBeNull();
  });

  it("保留数组和布尔值，并生成可读的扩展表单摘要", () => {
    const request = parseHumanInputRequest(EXTENDED_FORM_REQUEST)!;
    expect(
      buildHumanInputFormSubmissionValue(request, {
        budget: "300.5",
        due_date: "2026-09-15",
        channels: ["web", "email"],
        urgent: false,
        terms: true,
      }),
    ).toBe(
      '预算: 300.5; 截止日期: 2026-09-15; 发布渠道: web, email; 加急: 否; 同意发布条款: 是 [values: {"budget":"300.5","due_date":"2026-09-15","channels":["web","email"],"urgent":false,"terms":true}]',
    );
  });
});
