import { useState, type FormEvent } from "react";

import type {
  HumanInputFormValue,
  HumanInputFormValues,
  HumanInputRequest,
  HumanInputResponse,
} from "@/features/chat/model/human-input";
import {
  buildHumanInputFormSummary,
  buildHumanInputFormSubmissionValue,
  buildInitialHumanInputFormValues,
  findMissingRequiredHumanInputFields,
  readHumanInputFormValue,
} from "@/features/chat/model/human-input";

interface HumanInputCardProps {
  readonly request: HumanInputRequest;
  readonly answeredResponse?: HumanInputResponse;
  readonly onSubmit?: (response: HumanInputResponse) => Promise<boolean>;
}

export function HumanInputCard({
  request,
  answeredResponse,
  onSubmit,
}: HumanInputCardProps) {
  const [draft, setDraft] = useState("");
  const [formValues, setFormValues] = useState<
    Record<string, HumanInputFormValue>
  >(() =>
    request.inputMode === "form"
      ? buildInitialHumanInputFormValues(request.fields)
      : {},
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [invalidFieldNames, setInvalidFieldNames] = useState<Set<string>>(
    () => new Set(),
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = async (response: HumanInputResponse) => {
    if (isSubmitting || onSubmit === undefined) {
      return;
    }
    setIsSubmitting(true);
    const accepted = await onSubmit(response);
    if (!accepted) {
      setIsSubmitting(false);
      return;
    }
    setDraft("");
  };

  const submitDraft = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = draft.trim();
    if (value.length === 0) {
      return;
    }
    void submit({
      version: 1,
      kind: "human_input_response",
      request_id: request.requestId,
      response_kind: "text",
      value,
    });
  };

  const updateFormValue = (name: string, value: HumanInputFormValue) => {
    setFormValues((current) => ({ ...current, [name]: value }));
    const remaining = new Set(invalidFieldNames);
    remaining.delete(name);
    setInvalidFieldNames(remaining);
    if (remaining.size === 0) {
      setFormError(null);
    }
  };

  const submitForm = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (request.inputMode !== "form") {
      return;
    }
    const values: HumanInputFormValues = formValues;
    const missing = findMissingRequiredHumanInputFields(request, values);
    if (missing.length > 0) {
      setInvalidFieldNames(new Set(missing.map((field) => field.name)));
      setFormError("请填写所有必填字段");
      return;
    }
    if (buildHumanInputFormSummary(request, values).length === 0) {
      setFormError("请至少填写一个字段");
      return;
    }
    setInvalidFieldNames(new Set());
    setFormError(null);
    void submit({
      version: 1,
      kind: "human_input_response",
      request_id: request.requestId,
      response_kind: "text",
      value: buildHumanInputFormSubmissionValue(request, values),
    });
  };

  return (
    <article
      className="human-input-card"
      role="group"
      aria-label="需要你确认"
      data-state={answeredResponse === undefined ? "open" : "answered"}
    >
      <header className="human-input-card__header">
        <span aria-hidden="true">?</span>
        <div>
          <strong>需要你确认</strong>
          <small>
            {answeredResponse === undefined
              ? "回答后会开始下一轮"
              : "回答已记录"}
          </small>
        </div>
      </header>
      <div className="human-input-card__body">
        <p className="human-input-card__question">{request.question}</p>
        {request.context !== undefined && (
          <p className="human-input-card__context">{request.context}</p>
        )}

        {answeredResponse !== undefined ? (
          <div className="human-input-card__answer">
            <span>已回答</span>
            <strong>{answeredResponse.value}</strong>
          </div>
        ) : (
          <>
            {request.inputMode === "form" ? (
              <form
                className="human-input-card__fields"
                noValidate
                onSubmit={submitForm}
              >
                {request.fields.map((field) => {
                  const fieldId = `human-input:${request.requestId}:${field.name}`;
                  const value = readHumanInputFormValue(formValues, field.name);
                  const invalid = invalidFieldNames.has(field.name);
                  if (field.type === "checkbox") {
                    return (
                      <div
                        className="human-input-card__field human-input-card__checkbox"
                        key={field.name}
                      >
                        <label htmlFor={fieldId}>
                          <input
                            id={fieldId}
                            type="checkbox"
                            checked={value === true}
                            aria-required={field.required}
                            aria-invalid={invalid}
                            disabled={isSubmitting || onSubmit === undefined}
                            onChange={(event) =>
                              updateFormValue(field.name, event.target.checked)
                            }
                          />
                          <span>
                            {field.label}
                            {field.required && (
                              <span
                                className="human-input-card__required"
                                aria-hidden="true"
                              >
                                {" "}
                                *
                              </span>
                            )}
                          </span>
                        </label>
                      </div>
                    );
                  }
                  const stringValue =
                    typeof value === "string" || typeof value === "number"
                      ? String(value)
                      : "";
                  return (
                    <div className="human-input-card__field" key={field.name}>
                      <label htmlFor={fieldId}>
                        {field.label}
                        {field.required && (
                          <span
                            className="human-input-card__required"
                            aria-hidden="true"
                          >
                            {" "}
                            *
                          </span>
                        )}
                      </label>
                      {field.type === "textarea" ? (
                        <textarea
                          id={fieldId}
                          value={stringValue}
                          rows={3}
                          maxLength={32_768}
                          required={field.required}
                          aria-invalid={invalid}
                          disabled={isSubmitting || onSubmit === undefined}
                          placeholder={field.placeholder}
                          onChange={(event) =>
                            updateFormValue(field.name, event.target.value)
                          }
                        />
                      ) : field.type === "select" ? (
                        <select
                          id={fieldId}
                          value={stringValue}
                          required={field.required}
                          aria-invalid={invalid}
                          disabled={isSubmitting || onSubmit === undefined}
                          onChange={(event) =>
                            updateFormValue(field.name, event.target.value)
                          }
                        >
                          <option value="">请选择</option>
                          {field.options.map((option) => (
                            <option key={option.id} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      ) : field.type === "multi_select" ? (
                        <div
                          id={fieldId}
                          className="human-input-card__multi-select"
                          role="group"
                          aria-label={field.label}
                          aria-required={field.required}
                          aria-invalid={invalid}
                        >
                          {field.options.map((option) => {
                            const selectedValues = Array.isArray(value)
                              ? value
                              : [];
                            const selected = selectedValues.includes(
                              option.value,
                            );
                            return (
                              <button
                                key={option.id}
                                type="button"
                                aria-pressed={selected}
                                disabled={
                                  isSubmitting || onSubmit === undefined
                                }
                                onClick={() =>
                                  updateFormValue(
                                    field.name,
                                    selected
                                      ? selectedValues.filter(
                                          (entry) => entry !== option.value,
                                        )
                                      : [...selectedValues, option.value],
                                  )
                                }
                              >
                                <span aria-hidden="true">
                                  {selected ? "✓" : ""}
                                </span>
                                {option.label}
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <input
                          id={fieldId}
                          type={field.type}
                          value={stringValue}
                          maxLength={field.type === "text" ? 32_768 : undefined}
                          required={field.required}
                          aria-invalid={invalid}
                          disabled={isSubmitting || onSubmit === undefined}
                          placeholder={field.placeholder}
                          onChange={(event) =>
                            updateFormValue(field.name, event.target.value)
                          }
                        />
                      )}
                    </div>
                  );
                })}
                {formError !== null && (
                  <p className="human-input-card__error" role="alert">
                    {formError}
                  </p>
                )}
                <div className="human-input-card__actions">
                  <button
                    type="submit"
                    disabled={isSubmitting || onSubmit === undefined}
                  >
                    {isSubmitting ? "正在提交…" : "提交回答"}
                  </button>
                </div>
              </form>
            ) : (
              <>
                {request.inputMode === "choice_with_other" && (
                  <div
                    className="human-input-card__options"
                    role="group"
                    aria-label="可选回答"
                  >
                    {request.options.map((option) => (
                      <button
                        type="button"
                        key={option.id}
                        disabled={isSubmitting || onSubmit === undefined}
                        onClick={() =>
                          void submit({
                            version: 1,
                            kind: "human_input_response",
                            request_id: request.requestId,
                            response_kind: "option",
                            option_id: option.id,
                            value: option.value,
                          })
                        }
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                )}
                <form className="human-input-card__form" onSubmit={submitDraft}>
                  <label htmlFor={`human-input:${request.requestId}`}>
                    {request.inputMode === "choice_with_other"
                      ? "其他回答"
                      : "你的回答"}
                  </label>
                  <div>
                    <textarea
                      id={`human-input:${request.requestId}`}
                      value={draft}
                      rows={2}
                      maxLength={32_768}
                      disabled={isSubmitting || onSubmit === undefined}
                      placeholder="请输入补充信息"
                      onChange={(event) => setDraft(event.target.value)}
                    />
                    <button
                      type="submit"
                      disabled={
                        isSubmitting ||
                        onSubmit === undefined ||
                        draft.trim().length === 0
                      }
                    >
                      {isSubmitting ? "正在提交…" : "提交回答"}
                    </button>
                  </div>
                </form>
              </>
            )}
          </>
        )}
      </div>
    </article>
  );
}
