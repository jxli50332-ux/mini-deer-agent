import type {
  ChatTimelineItem,
  HumanInputResponseMetadata,
  ToolTimelineItem,
} from "@/entities/message/model/types";

type UnknownRecord = Record<string, unknown>;

export type HumanInputResponse = HumanInputResponseMetadata;

export interface HumanInputOption {
  readonly id: string;
  readonly label: string;
  readonly value: string;
}

interface HumanInputRequestBase {
  readonly kind: "human_input_request";
  readonly source: "ask_clarification";
  readonly requestId: string;
  readonly clarificationType:
    | "missing_info"
    | "ambiguous_requirement"
    | "approach_choice"
    | "risk_confirmation"
    | "suggestion";
  readonly question: string;
  readonly context?: string;
}

export interface HumanInputFreeTextRequest extends HumanInputRequestBase {
  readonly version: 1;
  readonly inputMode: "free_text";
}

export interface HumanInputChoiceRequest extends HumanInputRequestBase {
  readonly version: 1;
  readonly inputMode: "choice_with_other";
  readonly options: readonly HumanInputOption[];
}

interface HumanInputFormFieldBase {
  readonly name: string;
  readonly label: string;
  readonly required: boolean;
  readonly placeholder?: string;
}

export interface HumanInputScalarField extends HumanInputFormFieldBase {
  readonly type: "text" | "textarea" | "number" | "date";
}

export interface HumanInputOptionField extends HumanInputFormFieldBase {
  readonly type: "select" | "multi_select";
  readonly options: readonly HumanInputOption[];
}

export interface HumanInputCheckboxField extends HumanInputFormFieldBase {
  readonly type: "checkbox";
}

export type HumanInputFormField =
  HumanInputScalarField | HumanInputOptionField | HumanInputCheckboxField;

export interface HumanInputFormRequest extends HumanInputRequestBase {
  readonly version: 2;
  readonly inputMode: "form";
  readonly fields: readonly HumanInputFormField[];
}

export type HumanInputRequest =
  HumanInputFreeTextRequest | HumanInputChoiceRequest | HumanInputFormRequest;

export type HumanInputFormValue = string | number | boolean | string[];
export type HumanInputFormValues = Readonly<
  Record<string, HumanInputFormValue>
>;

export interface HumanInputThreadState {
  readonly requestsByToolItemId: ReadonlyMap<string, HumanInputRequest>;
  readonly answeredResponses: ReadonlyMap<string, HumanInputResponse>;
  readonly latestOpenRequestId: string | null;
}

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function parseContext(value: unknown): string | undefined | null {
  if (value === undefined) {
    return undefined;
  }
  return nonEmptyString(value) ? value : null;
}

function isClarificationType(
  value: unknown,
): value is HumanInputRequest["clarificationType"] {
  return (
    value === "missing_info" ||
    value === "ambiguous_requirement" ||
    value === "approach_choice" ||
    value === "risk_confirmation" ||
    value === "suggestion"
  );
}

function parseOptions(value: unknown): readonly HumanInputOption[] | null {
  if (!Array.isArray(value) || value.length < 2 || value.length > 8) {
    return null;
  }
  const options: HumanInputOption[] = [];
  const ids = new Set<string>();
  const values = new Set<string>();
  for (const item of value) {
    if (
      !isRecord(item) ||
      !nonEmptyString(item.id) ||
      !nonEmptyString(item.label) ||
      !nonEmptyString(item.value) ||
      ids.has(item.id) ||
      values.has(item.value)
    ) {
      return null;
    }
    ids.add(item.id);
    values.add(item.value);
    options.push({ id: item.id, label: item.label, value: item.value });
  }
  return options;
}

const RESERVED_FIELD_NAMES = new Set([
  "__proto__",
  "constructor",
  "prototype",
  "toString",
  "toLocaleString",
  "valueOf",
  "hasOwnProperty",
  "isPrototypeOf",
  "propertyIsEnumerable",
  "__defineGetter__",
  "__defineSetter__",
  "__lookupGetter__",
  "__lookupSetter__",
]);

function parsePlaceholder(value: unknown): string | undefined | null {
  if (value === undefined) {
    return undefined;
  }
  return nonEmptyString(value) ? value : null;
}

function parseFormFields(
  value: unknown,
): readonly HumanInputFormField[] | null {
  if (!Array.isArray(value) || value.length < 1 || value.length > 8) {
    return null;
  }
  const fields: HumanInputFormField[] = [];
  const names = new Set<string>();
  for (const item of value) {
    if (
      !isRecord(item) ||
      !nonEmptyString(item.name) ||
      !nonEmptyString(item.label) ||
      typeof item.required !== "boolean" ||
      names.has(item.name) ||
      RESERVED_FIELD_NAMES.has(item.name)
    ) {
      return null;
    }
    const placeholder = parsePlaceholder(item.placeholder);
    if (placeholder === null) {
      return null;
    }
    const common = {
      name: item.name,
      label: item.label,
      required: item.required,
      ...(placeholder === undefined ? {} : { placeholder }),
    };
    if (item.type === "select" || item.type === "multi_select") {
      const options = parseOptions(item.options);
      if (options === null) {
        return null;
      }
      fields.push({ ...common, type: item.type, options });
    } else if (
      (item.type === "text" ||
        item.type === "textarea" ||
        item.type === "number" ||
        item.type === "date" ||
        item.type === "checkbox") &&
      item.options === undefined
    ) {
      fields.push({ ...common, type: item.type });
    } else {
      return null;
    }
    names.add(item.name);
  }
  return fields;
}

/** 把不可信工具结果校验为当前前端明确支持的 v1 / v2 请求。 */
export function parseHumanInputRequest(
  value: unknown,
): HumanInputRequest | null {
  if (
    !isRecord(value) ||
    (value.version !== 1 && value.version !== 2) ||
    value.kind !== "human_input_request" ||
    value.source !== "ask_clarification" ||
    !nonEmptyString(value.request_id) ||
    !isClarificationType(value.clarification_type) ||
    !nonEmptyString(value.question)
  ) {
    return null;
  }
  const context = parseContext(value.context);
  if (context === null) {
    return null;
  }
  const common = {
    kind: "human_input_request" as const,
    source: "ask_clarification" as const,
    requestId: value.request_id,
    clarificationType: value.clarification_type,
    question: value.question,
    ...(context === undefined ? {} : { context }),
  };
  if (value.version === 2) {
    if (value.input_mode !== "form") {
      return null;
    }
    const fields = parseFormFields(value.fields);
    return fields === null
      ? null
      : { ...common, version: 2, inputMode: "form", fields };
  }
  if (value.input_mode === "free_text") {
    return { ...common, version: 1, inputMode: "free_text" };
  }
  if (value.input_mode !== "choice_with_other") {
    return null;
  }
  const options = parseOptions(value.options);
  return options === null
    ? null
    : { ...common, version: 1, inputMode: "choice_with_other", options };
}

export function readHumanInputFormValue(
  values: HumanInputFormValues,
  name: string,
): HumanInputFormValue | undefined {
  return Object.prototype.hasOwnProperty.call(values, name)
    ? values[name]
    : undefined;
}

export function buildInitialHumanInputFormValues(
  fields: readonly HumanInputFormField[],
): Record<string, HumanInputFormValue> {
  const values: Record<string, HumanInputFormValue> = {};
  for (const field of fields) {
    if (field.type === "checkbox") {
      values[field.name] = false;
    }
  }
  return values;
}

function isEmptyFormValue(value: HumanInputFormValue | undefined): boolean {
  if (value === undefined) {
    return true;
  }
  if (typeof value === "string") {
    return value.trim().length === 0;
  }
  if (Array.isArray(value)) {
    return value.length === 0;
  }
  return false;
}

export function findMissingRequiredHumanInputFields(
  request: HumanInputFormRequest,
  values: HumanInputFormValues,
): readonly HumanInputFormField[] {
  return request.fields.filter((field) => {
    if (!field.required) {
      return false;
    }
    const value = readHumanInputFormValue(values, field.name);
    return field.type === "checkbox" ? value !== true : isEmptyFormValue(value);
  });
}

function normalizedFormValue(value: HumanInputFormValue): HumanInputFormValue {
  if (typeof value === "string") {
    return value.trim();
  }
  return Array.isArray(value) ? [...value] : value;
}

function formatFormValue(value: HumanInputFormValue): string {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  return String(value);
}

export function buildHumanInputFormSummary(
  request: HumanInputFormRequest,
  values: HumanInputFormValues,
): string {
  const summary: string[] = [];
  for (const field of request.fields) {
    const value = readHumanInputFormValue(values, field.name);
    if (isEmptyFormValue(value)) {
      continue;
    }
    summary.push(
      `${field.label}: ${formatFormValue(normalizedFormValue(value!))}`,
    );
  }
  return summary.join("; ");
}

/** 同时保留用户可读摘要和可供下一 Run 稳定解析的字段映射。 */
export function buildHumanInputFormSubmissionValue(
  request: HumanInputRequest,
  values: HumanInputFormValues,
): string {
  if (request.inputMode !== "form") {
    throw new Error("human input request is not a form");
  }
  const submittedValues: Record<string, HumanInputFormValue> = {};
  for (const field of request.fields) {
    const value = readHumanInputFormValue(values, field.name);
    if (isEmptyFormValue(value)) {
      continue;
    }
    submittedValues[field.name] = normalizedFormValue(value!);
  }
  return `${buildHumanInputFormSummary(request, values)} [values: ${JSON.stringify(submittedValues)}]`;
}

/** 校验浏览器或历史 API 中携带的 v1 回答元数据。 */
export function parseHumanInputResponse(
  value: unknown,
): HumanInputResponse | null {
  if (
    !isRecord(value) ||
    value.version !== 1 ||
    value.kind !== "human_input_response" ||
    !nonEmptyString(value.request_id) ||
    !nonEmptyString(value.value)
  ) {
    return null;
  }
  if (value.response_kind === "text") {
    return {
      version: 1,
      kind: "human_input_response",
      request_id: value.request_id,
      response_kind: "text",
      value: value.value,
    };
  }
  if (value.response_kind === "option" && nonEmptyString(value.option_id)) {
    return {
      version: 1,
      kind: "human_input_response",
      request_id: value.request_id,
      response_kind: "option",
      option_id: value.option_id,
      value: value.value,
    };
  }
  return null;
}

export function humanInputRequestFromTool(
  item: ToolTimelineItem,
): HumanInputRequest | null {
  if (
    item.name !== "ask_clarification" ||
    item.status !== "completed" ||
    item.result === null
  ) {
    return null;
  }
  try {
    return parseHumanInputRequest(JSON.parse(item.result));
  } catch {
    return null;
  }
}

/**
 * 从原始时间线恢复卡片状态。结构化隐藏消息按 request_id 精确关联；
 * 普通 Composer 消息只兼容关闭它之前最新的一张未回答卡片。
 */
export function deriveHumanInputThreadState(
  timeline: readonly ChatTimelineItem[],
): HumanInputThreadState {
  const requestsByToolItemId = new Map<string, HumanInputRequest>();
  const requestOrder: HumanInputRequest[] = [];
  const answeredResponses = new Map<string, HumanInputResponse>();

  for (const item of timeline) {
    if (item.kind === "tool") {
      const request = humanInputRequestFromTool(item);
      if (request !== null) {
        requestsByToolItemId.set(item.id, request);
        requestOrder.push(request);
      }
      continue;
    }
    if (item.role !== "user") {
      continue;
    }

    const response = parseHumanInputResponse(item.humanInputResponse);
    if (
      response !== null &&
      requestOrder.some((request) => request.requestId === response.request_id)
    ) {
      answeredResponses.set(response.request_id, response);
      continue;
    }
    if (item.hiddenFromUi === true) {
      continue;
    }
    const latestOpen = [...requestOrder]
      .reverse()
      .find((request) => !answeredResponses.has(request.requestId));
    if (latestOpen !== undefined) {
      answeredResponses.set(latestOpen.requestId, {
        version: 1,
        kind: "human_input_response",
        request_id: latestOpen.requestId,
        response_kind: "text",
        value: item.content,
      });
    }
  }

  const latestOpen = [...requestOrder]
    .reverse()
    .find((request) => !answeredResponses.has(request.requestId));
  return {
    requestsByToolItemId,
    answeredResponses,
    latestOpenRequestId: latestOpen?.requestId ?? null,
  };
}

export function buildHumanInputResponseText(
  request: HumanInputRequest,
  response: HumanInputResponse,
): string {
  return `针对澄清问题“${request.question}”，我的回答是：${response.value}`;
}
