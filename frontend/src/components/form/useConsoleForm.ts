"use client";

import {
  useForm,
  type FormErrors,
  type UseFormInput,
  type UseFormReturnType,
} from "@mantine/form";
import { useTranslate } from "@refinedev/core";
import { useRef, useState, type SyntheticEvent } from "react";
import { flushSync } from "react-dom";

import {
  releaseLeaveGuardSuppression,
  useLeaveGuardRegistration,
} from "@/components/navigation/leaveGuard";
import { ApiError, type ApiFieldDetail } from "@/lib/api";

export type ApplyApiErrorResult = {
  mapped: ApiFieldDetail[];
  unmapped: ApiFieldDetail[];
};

export type UseConsoleFormReturn<Values, TransformedValues = Values> =
  UseFormReturnType<Values, TransformedValues> & {
    /** Current values differ from the loaded snapshot. */
    dirty: boolean;
    /** True while the submit runner is in progress. A second submit is ignored. */
    submitting: boolean;
    /** Replace the loaded snapshot with the current values. */
    markSaved: () => void;
    submit: (
      handler: (values: TransformedValues) => void | Promise<void>,
    ) => Promise<void>;
    applyApiError: (
      error: unknown,
      alias?: Record<string, string>,
    ) => ApplyApiErrorResult;
    fieldProps: UseFormReturnType<Values, TransformedValues>["getInputProps"];
  };

type SubmitHandler<TransformedValues> = (
  values: TransformedValues,
  event: SyntheticEvent<HTMLFormElement> | undefined,
) => void | Promise<void>;

type ValidationFailure<Values> = (
  errors: FormErrors,
  values: Values,
  event: SyntheticEvent<HTMLFormElement> | undefined,
) => void;

const LOC_PREFIXES = new Set(["body", "query", "path", "header", "cookie"]);

function fieldCandidates(field: string | undefined): string[] {
  const name = field?.trim() ?? "";
  if (!name) return [];
  const parts = name.split(".");
  const head = parts[0] ?? "";
  if (!LOC_PREFIXES.has(head) || parts.length < 2) return [name];
  const stripped = parts.slice(1).join(".");
  return stripped && stripped !== name ? [name, stripped] : [name];
}

function hasFormPath(values: unknown, path: string): boolean {
  if (!path) return false;
  let current = values;
  for (const part of path.split(".")) {
    if (Array.isArray(current)) {
      const index = Number(part);
      if (!Number.isInteger(index) || index < 0 || index >= current.length) return false;
      current = current[index];
      continue;
    }
    if (current == null || typeof current !== "object") return false;
    if (!Object.prototype.hasOwnProperty.call(current, part)) return false;
    current = (current as Record<string, unknown>)[part];
  }
  return true;
}

function resolveFieldPath(
  values: unknown,
  field: string | undefined,
  alias: Record<string, string> | undefined,
): string | null {
  for (const name of fieldCandidates(field)) {
    if (hasFormPath(values, name)) return name;
    const aliased = alias?.[name]?.trim() ?? "";
    if (aliased && hasFormPath(values, aliased)) return aliased;
  }
  return null;
}

function detailText(detail: ApiFieldDetail, fallback: string): string {
  const message = detail.message?.trim();
  if (message) return message;
  const code = detail.code?.trim();
  if (code) return code;
  return fallback;
}

function firstErrorPath(errors: FormErrors): string | null {
  for (const [path, error] of Object.entries(errors)) {
    if (error) return path;
  }
  return null;
}

function cssEscape(value: string): string {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") return CSS.escape(value);
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function focusElement(node: HTMLElement | null) {
  if (!node) return;
  const target = node.matches("input, textarea, select, button, [tabindex]")
    ? node
    : node.querySelector<HTMLElement>("input, textarea, select");
  target?.focus();
}

function focusField(getInputNode: (path: string) => HTMLElement | null, path: string) {
  const named =
    typeof document === "undefined"
      ? null
      : document.querySelector<HTMLElement>(`[name="${cssEscape(path)}"]`);
  focusElement(getInputNode(path) ?? named);
}

export function useConsoleForm<
  Values extends Record<string, unknown> = Record<string, unknown>,
  TransformedValues = Values,
>(
  input: UseFormInput<Values, TransformedValues> = {},
): UseConsoleFormReturn<Values, TransformedValues> {
  const t = useTranslate();
  const formRef = useRef<UseFormReturnType<Values, TransformedValues> | null>(null);
  const lock = useRef(false);
  const reportedFailure = useRef(false);
  const [submitting, setSubmitting] = useState(false);

  const form = useForm<Values, TransformedValues>({
    ...input,
    clearInputErrorOnChange: false,
    validateInputOnBlur: false,
    validateInputOnChange: false,
    enhanceGetInputProps: (payload) => {
      const previousOnChange = payload.inputProps.onChange as
        | ((value: unknown) => void)
        | undefined;
      const previousOnBlur = payload.inputProps.onBlur as
        | ((value: unknown) => void)
        | undefined;
      const userExtra = input.enhanceGetInputProps?.(payload);
      const extra =
        userExtra && typeof userExtra === "object" ? userExtra : {};
      const userOnChange = extra.onChange as ((value: unknown) => void) | undefined;
      const userOnBlur = extra.onBlur as ((value: unknown) => void) | undefined;
      const path = String(payload.field);
      return {
        ...extra,
        onChange: (value: unknown) => {
          const hadError = Boolean(formRef.current?.errors[path]);
          previousOnChange?.(value);
          userOnChange?.(value);
          if (hadError) void formRef.current?.validateField(payload.field);
        },
        onBlur: (value: unknown) => {
          previousOnBlur?.(value);
          userOnBlur?.(value);
          if (formRef.current?.isTouched(payload.field)) {
            void formRef.current.validateField(payload.field);
          }
        },
      };
    },
  });
  formRef.current = form;

  const dirty = form.isDirty();
  useLeaveGuardRegistration(dirty);

  function focusInvalid(errors: FormErrors) {
    const path = firstErrorPath(errors);
    if (!path) return;
    focusField((field) => form.getInputNode(field), path);
  }

  function acceptSnapshot() {
    flushSync(() => {
      form.resetDirty();
    });
  }

  async function runSubmit(
    handleSubmit: SubmitHandler<TransformedValues>,
    handleValidationFailure?: ValidationFailure<Values>,
    event?: SyntheticEvent<HTMLFormElement>,
  ): Promise<void> {
    if (lock.current) return;
    lock.current = true;
    reportedFailure.current = false;
    setSubmitting(true);
    try {
      const validation = form.validate();
      const result = validation instanceof Promise ? await validation : validation;
      if (result.hasErrors) {
        focusInvalid(result.errors);
        handleValidationFailure?.(result.errors, form.getValues(), event);
        return;
      }
      await handleSubmit(form.getTransformedValues(), event);
      if (reportedFailure.current) {
        releaseLeaveGuardSuppression();
        return;
      }
      acceptSnapshot();
    } catch {
      releaseLeaveGuardSuppression();
    } finally {
      lock.current = false;
      setSubmitting(false);
    }
  }

  const submit = (handler: (values: TransformedValues) => void | Promise<void>) =>
    runSubmit((values) => handler(values));

  const onSubmit: UseFormReturnType<Values, TransformedValues>["onSubmit"] = (
    handleSubmit,
    handleValidationFailure,
  ) => (event) => {
    event?.preventDefault();
    void runSubmit(handleSubmit, handleValidationFailure, event);
  };

  const markSaved = () => {
    form.resetDirty();
  };

  const applyApiError = (
    error: unknown,
    alias?: Record<string, string>,
  ): ApplyApiErrorResult => {
    reportedFailure.current = true;
    if (!(error instanceof ApiError) || error.status !== 422) {
      return { mapped: [], unmapped: [] };
    }
    const details = error.details ?? [];
    const values = form.getValues();
    const mapped: ApiFieldDetail[] = [];
    const unmapped: ApiFieldDetail[] = [];
    const errors: FormErrors = {};
    let first: string | null = null;
    for (const detail of details) {
      const path = resolveFieldPath(values, detail.field, alias);
      if (!path) {
        unmapped.push(detail);
        continue;
      }
      mapped.push(detail);
      const text = detailText(detail, t("form.error.field"));
      const previous = errors[path];
      errors[path] = previous ? `${String(previous)}\n${text}` : text;
      if (!first) first = path;
    }
    form.setErrors(errors);
    if (first) focusField((field) => form.getInputNode(field), first);
    return { mapped, unmapped };
  };

  return {
    ...form,
    submitting,
    setSubmitting,
    onSubmit,
    dirty,
    markSaved,
    resetDirty: form.resetDirty,
    submit,
    applyApiError,
    fieldProps: form.getInputProps,
  };
}
